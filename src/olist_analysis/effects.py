"""How much does a late delivery cost in reviews and repeat purchases?

Late orders are not a random sample (they skew to remote states, heavy items,
some sellers), so the raw gap overstates or understates the effect. These
regressions add fixed effects for category, customer state, seller state and
month plus order controls, with standard errors clustered by seller. The
estimate is still observational: read it as "the late penalty after removing
the obvious confounders", not as an experiment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

CONTROLS = ("np.log1p(item_value) + np.log1p(freight_value) + n_items + np.log1p(distance_km) "
            "+ C(category) + C(customer_state) + C(seller_state) + C(month)")


def _prep(fct: pd.DataFrame) -> pd.DataFrame:
    d = fct[(fct.order_status == "delivered") & fct.review_score.notna() & fct.days_late.notna()
            & fct.distance_km.notna() & fct.seller_id.notna()].copy()
    d["late"] = d.is_late.astype(int)
    d["one_star"] = (d.review_score == 1).astype(int)
    d["month"] = d.purchase_month.astype(str)
    # rare levels -> 'other' so fixed effects are estimable
    for c in ("category", "customer_state", "seller_state"):
        counts = d[c].value_counts()
        d[c] = d[c].where(d[c].map(counts) >= 100, "other")
    return d


def late_effect_on_reviews(fct: pd.DataFrame) -> pd.DataFrame:
    d = _prep(fct)
    rows = []
    for outcome in ("review_score", "one_star"):
        raw = smf.ols(f"{outcome} ~ late", data=d).fit(cov_type="cluster", cov_kwds={"groups": d.seller_id})
        adj = smf.ols(f"{outcome} ~ late + {CONTROLS}", data=d).fit(cov_type="cluster", cov_kwds={"groups": d.seller_id})
        for name, m in (("raw", raw), ("adjusted", adj)):
            ci = m.conf_int().loc["late"]
            rows.append({"outcome": outcome, "model": name, "effect": m.params["late"], "ci_low": ci[0], "ci_high": ci[1],
                         "p_value": m.pvalues["late"], "n": int(m.nobs), "baseline_on_time": d.loc[d.late == 0, outcome].mean()})
    return pd.DataFrame(rows)


def dose_response(fct: pd.DataFrame) -> pd.DataFrame:
    """Adjusted 1-star probability by days-late bucket (relative to 'on time')."""
    d = _prep(fct)
    bins = [-np.inf, 0, 1, 3, 7, 14, np.inf]
    labels = ["on time", "0-1 late", "1-3 late", "3-7 late", "7-14 late", "14+ late"]
    d["bucket"] = pd.cut(d.days_late, bins, labels=labels).astype(str)
    m = smf.ols(f"one_star ~ C(bucket, Treatment('on time')) + {CONTROLS}", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": d.seller_id})
    rows = [{"bucket": "on time", "effect": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": int((d.bucket == "on time").sum())}]
    for lab in labels[1:]:
        k = f"C(bucket, Treatment('on time'))[T.{lab}]"
        ci = m.conf_int().loc[k]
        rows.append({"bucket": lab, "effect": m.params[k], "ci_low": ci[0], "ci_high": ci[1], "n": int((d.bucket == lab).sum())})
    return pd.DataFrame(rows)


def late_effect_on_repeat(fct: pd.DataFrame, horizon_days: int = 180) -> pd.DataFrame:
    """Does a late *first* order reduce the chance of a second order within ``horizon_days``?"""
    f = fct[fct.order_status.isin(["delivered"])].sort_values("purchased_at")
    first = f[f.customer_order_number == 1].copy()
    cutoff = f.purchased_at.max() - pd.Timedelta(days=horizon_days)
    first = first[(first.purchased_at <= cutoff) & first.is_late.notna() & first.distance_km.notna()]
    nxt = fct[fct.customer_order_number == 2][["customer_unique_id", "purchased_at"]].rename(columns={"purchased_at": "second_at"})
    first = first.merge(nxt, on="customer_unique_id", how="left")
    first["repeat"] = ((first.second_at - first.purchased_at).dt.days <= horizon_days).astype(int)
    d = _prep(first.assign(review_score=first.review_score.fillna(0)))
    raw = smf.ols("repeat ~ late", data=d).fit(cov_type="HC1")
    adj = smf.ols(f"repeat ~ late + {CONTROLS}", data=d).fit(cov_type="HC1")
    out = []
    for name, m in (("raw", raw), ("adjusted", adj)):
        ci = m.conf_int().loc["late"]
        out.append({"outcome": f"repeat_within_{horizon_days}d", "model": name, "effect": m.params["late"],
                    "ci_low": ci[0], "ci_high": ci[1], "p_value": m.pvalues["late"], "n": int(m.nobs),
                    "baseline_on_time": d.loc[d.late == 0, "repeat"].mean()})
    return pd.DataFrame(out)
