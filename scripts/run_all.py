"""Build the warehouse with dbt, then run the analyses on the marts.

Run from the project root:  python scripts/run_all.py   (add --skip-dbt to reuse the warehouse)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from olist_analysis import effects, eta, plotstyle  # noqa: E402

WAREHOUSE = ROOT / "data" / "warehouse" / "olist.duckdb"
FIGURES, TABLES = ROOT / "reports" / "figures", ROOT / "reports" / "tables"
TEST_START = pd.Timestamp("2018-01-01")
QUANTILES = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_dbt():
    env = {**os.environ, "OLIST_RAW_DIR": (ROOT / "data" / "raw").as_posix(), "OLIST_DUCKDB_PATH": WAREHOUSE.as_posix()}
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    dbt = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
    cmd = [str(dbt), "build", "--profiles-dir", ".", "--project-dir", "."]
    res = subprocess.run(cmd, cwd=ROOT / "dbt", env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary = [line for line in res.stdout.splitlines() if "Done." in line]
    log(summary[-1] if summary else res.stdout[-2000:])
    if res.returncode != 0:
        raise SystemExit(res.stdout[-4000:])
    return summary[-1] if summary else ""


def main():
    plotstyle.apply()
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    out: dict = {}
    if "--skip-dbt" not in sys.argv:
        out["dbt_build"] = run_dbt().split("Done.")[-1].strip()

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    q = lambda sql: con.sql(sql).df()  # noqa: E731
    fct = q("select * from marts.fct_orders")
    kpis = q("select * from marts.mart_monthly_kpis where purchase_month between '2017-01-01' and '2018-08-01'")
    cohorts = q("select * from marts.mart_cohort_retention")
    sellers = q("select * from marts.mart_seller_scorecard")
    dvr = q("select * from marts.mart_delivery_vs_review")
    customers = q("select * from marts.dim_customers")
    con.close()

    delivered = fct[fct.order_status == "delivered"]
    out["facts"] = {
        "orders": int(len(fct)), "customers": int(customers.shape[0]),
        "gmv_brl": float(fct.loc[~fct.order_status.isin(["canceled", "unavailable"]), "gmv"].sum()),
        "repeat_customer_share": float((customers.n_orders > 1).mean()),
        "late_rate": float(delivered.is_late.mean()),
        "median_days_early": float(-delivered.days_late.median()),
        "mean_days_to_deliver": float(delivered.days_to_deliver.mean()),
        "mean_promised_days": float(delivered.promised_days.mean()),
    }
    log(out["facts"])

    # ------------------------------------------------------------------ effects
    log("late-delivery effects")
    rev = effects.late_effect_on_reviews(fct)
    rep = effects.late_effect_on_repeat(fct)
    dose = effects.dose_response(fct)
    pd.concat([rev, rep]).to_csv(TABLES / "late_delivery_effects.csv", index=False)
    dose.to_csv(TABLES / "one_star_dose_response.csv", index=False)
    out["late_effects"] = pd.concat([rev, rep]).round(4).to_dict(orient="records")

    # Established sellers (30+ delivered orders): how much lateness is concentrated in the worst decile?
    est = sellers[sellers.orders >= 30].copy()
    med_late = float(est.late_rate.median())
    worst = est.sort_values("late_rate", ascending=False).head(int(np.ceil(0.1 * len(est))))
    rest = est.drop(worst.index)
    avoidable = float((worst.late_orders - worst.orders * med_late).clip(lower=0).sum())
    out["seller_concentration"] = {
        "established_sellers": int(len(est)), "established_share_of_orders": float(est.orders.sum() / sellers.orders.sum()),
        "worst_decile_sellers": int(len(worst)),
        "worst_decile_share_of_orders": float(worst.orders.sum() / sellers.orders.sum()),
        "worst_decile_share_of_late_orders": float(worst.late_orders.sum() / sellers.late_orders.sum()),
        "worst_decile_late_rate": float(worst.late_orders.sum() / worst.orders.sum()),
        "median_seller_late_rate": med_late,
        "late_orders_avoided_if_worst_at_median": avoidable,
        "share_of_all_late_orders_avoidable": avoidable / float(sellers.late_orders.sum()),
        "bad_review_rate_worst_vs_rest": [float(worst.bad_review_rate.mean()), float(rest.bad_review_rate.mean())],
    }
    sellers.sort_values("gmv", ascending=False).to_csv(TABLES / "seller_scorecard.csv", index=False)

    # ------------------------------------------------------------------ ETA model
    log("ETA quantile models")
    frame = eta.build_frame(fct)
    train = frame[frame.purchased_at < TEST_START]
    # Static model: trained once on 2017, applied to all of 2018 (shows the drift problem)
    static_models = eta.fit_quantiles(train, QUANTILES)
    test_static = frame[frame.purchased_at >= TEST_START]
    static_preds = {q_: m.predict(test_static[eta.FEATURES]) for q_, m in static_models.items()}
    static_trade = eta.promise_tradeoff(test_static, static_preds)
    # Production design: retrain monthly on orders already delivered
    test, preds = eta.rolling_monthly(frame, TEST_START, QUANTILES)
    models = eta.fit_quantiles(frame[frame.delivered_at < frame.purchased_at.max()], (0.9,))
    trade = eta.promise_tradeoff(test, preds)
    trade.to_csv(TABLES / "promise_tradeoff.csv", index=False)
    static_trade.to_csv(TABLES / "promise_tradeoff_static_model.csv", index=False)
    olist = trade.iloc[0]
    model_rows = trade.iloc[1:]
    # promise length the model needs to match Olist's on-time rate (linear interpolation on the curve)
    matched_days = float(np.interp(olist.on_time_rate, model_rows.on_time_rate, model_rows.avg_promised_days))
    # on-time rate the model achieves with Olist's average promise length
    matched_on_time = float(np.interp(olist.avg_promised_days, model_rows.avg_promised_days, model_rows.on_time_rate))
    p50 = preds[0.5]
    pair_median = train.groupby(["seller_state", "customer_state"], observed=True).days_to_deliver.median()
    naive = test.set_index(["seller_state", "customer_state"]).index.map(pair_median).to_numpy(dtype=float)
    naive = np.where(np.isnan(naive), train.days_to_deliver.median(), naive)
    imp = pd.Series(models[0.9].feature_importance("gain"), index=eta.FEATURES).sort_values(ascending=False)
    imp = imp / imp.sum()
    imp.to_csv(TABLES / "eta_feature_importance.csv")
    one_star_effect = rev.query("outcome == 'one_star' and model == 'adjusted'").effect.iloc[0]
    late_cut = (1 - olist.on_time_rate) - (1 - matched_on_time)
    out["eta"] = {
        "train_orders": int(len(train)), "test_orders": int(len(test)), "test_period": f"{TEST_START.date()} onward",
        "olist_avg_promised_days": float(olist.avg_promised_days), "olist_on_time_rate": float(olist.on_time_rate),
        "model_days_at_olist_on_time_rate": matched_days,
        "days_saved_at_same_on_time_rate": float(olist.avg_promised_days - matched_days),
        "model_on_time_at_olist_promise_length": matched_on_time,
        "late_orders_avoided_per_1000": float(1000 * late_cut),
        "one_star_reviews_avoided_per_1000_orders": float(1000 * late_cut * one_star_effect),
        "p50_mae_days": float(np.abs(p50 - test.days_to_deliver).mean()),
        "state_pair_median_mae_days": float(np.abs(naive - test.days_to_deliver).mean()),
        "coverage_monthly_retrain": {f"P{int(q_ * 100)}": float((test.days_to_deliver <= preds[q_]).mean()) for q_ in QUANTILES},
        "coverage_static_2017_model": {f"P{int(q_ * 100)}": float((test_static.days_to_deliver <= static_preds[q_]).mean()) for q_ in QUANTILES},
    }
    log(out["eta"])
    (ROOT / "reports" / "metrics.json").write_text(json.dumps(out, indent=2, default=float))

    # ------------------------------------------------------------------ figures
    log("figures")
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    axes[0].bar(kpis.purchase_month, kpis.gmv / 1e6, width=20, color=plotstyle.SERIES[0])
    axes[0].set_ylabel("GMV (BRL millions)")
    axes[0].set_title("Monthly GMV, 2017 to 2018")
    axes[1].plot(kpis.purchase_month, 100 * kpis.late_rate, marker="o", color=plotstyle.CRITICAL)
    axes[1].set_ylabel("Late deliveries (%)")
    axes[1].set_title("Late-delivery rate spikes with peak season and the May 2018 truckers' strike")
    for ax in axes:
        ax.tick_params(axis="x", rotation=45)
    plotstyle.save(fig, FIGURES / "01_kpis.png")

    fig, ax = plt.subplots(figsize=(9, 4))
    labels = dvr.delivery_bucket.str.slice(3)
    colors = [plotstyle.SERIES[2] if "early" in b else plotstyle.CRITICAL for b in dvr.delivery_bucket]
    ax.bar(labels, 100 * dvr.one_star_rate, color=colors, width=0.65)
    for i, (v, n) in enumerate(zip(dvr.one_star_rate, dvr.orders)):
        ax.annotate(f"{100 * v:.0f}%\n(n={n:,})", (i, 100 * v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
    ax.set_ylabel("1-star reviews (%)")
    ax.set_ylim(0, 85)
    ax.set_title("One-star rate jumps from 6% to 53%+ once an order is 3 days late")
    plotstyle.save(fig, FIGURES / "02_delivery_vs_review.png")

    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.errorbar(range(len(dose)), 100 * dose.effect, yerr=[100 * (dose.effect - dose.ci_low), 100 * (dose.ci_high - dose.effect)],
                fmt="o", color=plotstyle.CRITICAL, capsize=3, lw=1.5)
    ax.set_xticks(range(len(dose)), dose.bucket)
    ax.axhline(0, color=plotstyle.AXIS, lw=1)
    ax.set_ylabel("Change in 1-star probability vs on time (pp)")
    ax.set_title("Adjusted for category, geography, month, price and distance")
    plotstyle.save(fig, FIGURES / "03_dose_response.png")

    piv = cohorts[(cohorts.months_since_first.between(1, 12)) & (cohorts.cohort_month >= pd.Timestamp("2017-01-01"))
                  & (cohorts.cohort_month <= pd.Timestamp("2018-02-01"))].pivot(index="cohort_month", columns="months_since_first", values="retention")
    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(100 * piv.to_numpy(), cmap="Blues", aspect="auto", vmin=0, vmax=1.0)
    ax.set_xticks(range(piv.shape[1]), piv.columns)
    ax.set_yticks(range(piv.shape[0]), [d.strftime("%Y-%m") for d in piv.index])
    ax.grid(False)
    for (i, j), v in np.ndenumerate(100 * piv.to_numpy()):
        if not np.isnan(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7, color=plotstyle.INK if v < 0.6 else "white")
    ax.set_xlabel("Months since first order")
    ax.set_title("Monthly cohort retention (%): fewer than 1% come back in any later month")
    fig.colorbar(im, ax=ax, label="% of cohort ordering")
    plotstyle.save(fig, FIGURES / "04_cohort_retention.png")

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.scatter(rest.orders, 100 * rest.late_rate, s=12, color=plotstyle.NEUTRAL, alpha=0.6, label="Other established sellers")
    ax.scatter(worst.orders, 100 * worst.late_rate, s=18, color=plotstyle.CRITICAL, label=f"Worst 10% by late rate ({len(worst)} sellers)")
    ax.axhline(100 * med_late, color=plotstyle.AXIS, ls=":", lw=1)
    ax.annotate(f"median {100 * med_late:.1f}%", (est.orders.max(), 100 * med_late), xytext=(-4, 4), textcoords="offset points", ha="right", fontsize=8, color=plotstyle.INK_2)
    ax.set_xscale("log")
    ax.set_xlabel("Delivered orders per seller (log scale, sellers with 30+)")
    ax.set_ylabel("Late-delivery rate (%)")
    ax.set_title(f"{len(worst)} sellers cause {100 * out['seller_concentration']['worst_decile_share_of_late_orders']:.0f}% of late orders on {100 * out['seller_concentration']['worst_decile_share_of_orders']:.0f}% of volume")
    ax.legend(fontsize=8)
    plotstyle.save(fig, FIGURES / "05_seller_concentration.png")

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.plot(model_rows.avg_promised_days, 100 * model_rows.on_time_rate, marker="o", color=plotstyle.SERIES[0], label="ETA model, retrained monthly")
    st = static_trade.iloc[1:]
    ax.plot(st.avg_promised_days, 100 * st.on_time_rate, marker="o", ms=4, ls="--", color=plotstyle.NEUTRAL, label="ETA model, trained once on 2017")
    for _, r in model_rows.iterrows():
        ax.annotate(r.policy.split()[-1], (r.avg_promised_days, 100 * r.on_time_rate), xytext=(5, -10), textcoords="offset points", fontsize=8, color=plotstyle.INK_2)
    ax.scatter([olist.avg_promised_days], [100 * olist.on_time_rate], color=plotstyle.CRITICAL, s=60, zorder=3, label="Olist's actual promise")
    ax.annotate(f"same on-time rate,\n{out['eta']['days_saved_at_same_on_time_rate']:.1f} days shorter promise",
                (matched_days, 100 * olist.on_time_rate), xytext=(matched_days + 1, 100 * olist.on_time_rate - 9),
                arrowprops=dict(arrowstyle="->", color=plotstyle.INK_2), fontsize=9)
    ax.set_xlabel("Average promised delivery time (days)")
    ax.set_ylabel("Orders delivered by the promise (%)")
    ax.set_title("Olist sits close to the frontier: shorter promises cost on-time rate")
    ax.legend(loc="lower right")
    plotstyle.save(fig, FIGURES / "06_eta_tradeoff.png")

    fig, ax = plt.subplots(figsize=(7, 4.2))
    t = imp.head(10)[::-1]
    ax.barh(t.index, 100 * t.values, color=plotstyle.SERIES[0], height=0.6)
    ax.set_xlabel("Share of split gain, P90 model (%)")
    ax.set_title("What predicts delivery time")
    plotstyle.save(fig, FIGURES / "07_eta_importance.png")

    md = [
        "# Results (auto-generated by scripts/run_all.py)\n",
        f"dbt build: {out.get('dbt_build', 'skipped')}\n",
        f"```json\n{json.dumps(out['facts'], indent=2)}\n```\n",
        "## Late-delivery effects (OLS, seller-clustered SEs)\n", pd.concat([rev, rep]).to_markdown(index=False, floatfmt=".4f"),
        "\n## Adjusted 1-star dose response\n", dose.to_markdown(index=False, floatfmt=".4f"),
        "\n## Delivery bucket vs reviews (from mart_delivery_vs_review)\n", dvr.to_markdown(index=False, floatfmt=".3f"),
        f"\n## Seller concentration\n\n```json\n{json.dumps(out['seller_concentration'], indent=2)}\n```\n",
        "\n## ETA promise trade-off (test period)\n", trade.to_markdown(index=False, floatfmt=".3f"),
        f"\n```json\n{json.dumps(out['eta'], indent=2, default=float)}\n```\n",
        "\n## ETA feature importance (P90)\n", imp.to_frame("gain_share").to_markdown(floatfmt=".3f"),
    ]
    (ROOT / "reports" / "RESULTS.md").write_text("\n".join(md), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
