"""Delivery-time (ETA) model: can Olist promise earlier dates without more late orders?

Olist's promised dates are padded: the median order arrives about 11 days
early. Long promises cost conversion, and blown promises cost reviews. A
quantile model of delivery time lets the business pick the promise as a
chosen percentile of each order's own delivery-time distribution.

All features are known at checkout. Seller history is computed from strictly
earlier orders, and the split is by time.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

FEATURES = [
    "distance_km", "same_state", "customer_state", "seller_state", "category",
    "log_freight", "log_item_value", "log_weight", "log_volume", "n_items", "n_sellers",
    "dow", "month", "seller_prior_orders", "seller_prior_days_to_carrier", "seller_prior_days_to_deliver",
    "freight_to_value", "recent_network_days", "recent_state_days",
]
CATEGORICAL = ["customer_state", "seller_state", "category"]


def build_frame(fct: pd.DataFrame) -> pd.DataFrame:
    d = fct[(fct.order_status == "delivered") & fct.days_to_deliver.notna() & fct.promised_days.notna()
            & fct.seller_id.notna()].copy()
    d = d.sort_values("purchased_at").reset_index(drop=True)
    d["log_freight"] = np.log1p(d.freight_value)
    d["log_item_value"] = np.log1p(d.item_value)
    d["log_weight"] = np.log1p(d.total_weight_g)
    d["log_volume"] = np.log1p(d.total_volume_cm3)
    d["freight_to_value"] = d.freight_value / d.item_value.clip(lower=1)
    d["dow"] = d.purchased_at.dt.dayofweek
    d["month"] = d.purchased_at.dt.month
    d["same_state"] = d.same_state.astype(float)
    # Seller history from strictly earlier orders. Delivery outcomes of earlier orders
    # are only known once delivered, so only orders delivered before this purchase count.
    g = d.groupby("seller_id", sort=False)
    d["seller_prior_orders"] = g.cumcount()
    d["seller_prior_days_to_carrier"] = g.days_to_carrier.transform(lambda s: s.shift(1).expanding().mean())
    d["seller_prior_days_to_deliver"] = _prior_delivered_mean(d)
    d["recent_network_days"] = _recent_delivered_mean(d, d.index, window_days=14)
    d["recent_state_days"] = np.nan
    for _, idx in d.groupby("customer_state", sort=False).indices.items():
        d.loc[d.index[idx], "recent_state_days"] = _recent_delivered_mean(d.iloc[idx], d.index[idx], window_days=30).to_numpy()
    for c in CATEGORICAL:
        d[c] = d[c].fillna("unknown").astype("category")
    return d


def _recent_delivered_mean(d: pd.DataFrame, index, window_days: int) -> pd.Series:
    """Nowcast: mean delivery time of orders that *arrived* in the ``window_days`` before purchase.

    Known at checkout, and it moves within days when the network slows down
    (peak season, the May 2018 truckers' strike), unlike a model retrained monthly.
    """
    deliv = d.delivered_at.to_numpy()
    order = np.argsort(deliv)
    deliv_sorted = deliv[order]
    csum = np.concatenate([[0.0], np.cumsum(d.days_to_deliver.to_numpy()[order])])
    p = d.purchased_at.to_numpy()
    hi = np.searchsorted(deliv_sorted, p, side="left")
    lo = np.searchsorted(deliv_sorted, p - np.timedelta64(window_days, "D"), side="left")
    n = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        return pd.Series(np.where(n >= 5, (csum[hi] - csum[lo]) / np.maximum(n, 1), np.nan), index=index)


def _prior_delivered_mean(d: pd.DataFrame) -> pd.Series:
    """Mean delivery time of the seller's earlier orders that had *arrived* by purchase time."""
    out = np.full(len(d), np.nan)
    for _, idx in d.groupby("seller_id", sort=False).indices.items():
        sub = d.iloc[idx]
        p = sub.purchased_at.to_numpy()
        deliv = sub.delivered_at.to_numpy()
        days = sub.days_to_deliver.to_numpy()
        order = np.argsort(deliv)
        deliv_sorted, days_sorted = deliv[order], days[order]
        csum = np.concatenate([[0.0], np.cumsum(days_sorted)])
        k = np.searchsorted(deliv_sorted, p, side="left")
        with np.errstate(invalid="ignore", divide="ignore"):
            out[idx] = np.where(k > 0, csum[k] / np.maximum(k, 1), np.nan)
    return pd.Series(out, index=d.index)


def fit_quantiles(train: pd.DataFrame, quantiles, seed: int = 3) -> dict:
    models = {}
    for q in quantiles:
        params = dict(objective="quantile", alpha=q, learning_rate=0.05, num_leaves=63, min_child_samples=50,
                      feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, seed=seed, verbose=-1)
        models[q] = lgb.train(params, lgb.Dataset(train[FEATURES], train.days_to_deliver, categorical_feature=CATEGORICAL),
                              num_boost_round=600)
    return models


def rolling_monthly(frame: pd.DataFrame, start: pd.Timestamp, quantiles, seed: int = 3, maturity_days: int = 45):
    """Retrain at the start of every month on orders whose delivery is already known.

    Two traps this avoids:
    * leakage: an order bought on 30 January has no label on 1 February;
    * censoring bias: keeping only *already delivered* recent orders keeps the
      fast ones and drops the slow ones, so the model learns that delivery is
      quicker than it is. Training stops ``maturity_days`` before the retrain
      date, when ~99% of orders have arrived; the nowcast features carry the
      recent signal instead.
    Returns (test frame, {quantile: predictions aligned to the test frame}).
    """
    months = pd.date_range(start, frame.purchased_at.max(), freq="MS")
    parts, preds = [], {q: [] for q in quantiles}
    for m in months:
        nxt = m + pd.offsets.MonthBegin(1)
        cutoff = m - pd.Timedelta(days=maturity_days)
        train = frame[(frame.purchased_at < cutoff) & (frame.delivered_at < m)]
        test = frame[(frame.purchased_at >= m) & (frame.purchased_at < nxt)]
        if len(test) < 200:
            continue
        models = fit_quantiles(train, quantiles, seed)
        parts.append(test)
        for q, model in models.items():
            preds[q].append(model.predict(test[FEATURES]))
    test = pd.concat(parts)
    return test, {q: np.concatenate(v) for q, v in preds.items()}


def promise_tradeoff(test: pd.DataFrame, preds: dict) -> pd.DataFrame:
    """On-time rate vs average promised days, for Olist's promise and each model quantile.

    'On time' uses the same one-day grace period as the dbt mart.
    """
    rows = [{"policy": "Olist estimate (actual)", "quantile": np.nan,
             "avg_promised_days": test.promised_days.mean(),
             "on_time_rate": float((test.days_to_deliver <= test.promised_days + 1).mean())}]
    for q, p in sorted(preds.items()):
        promise = np.ceil(p)
        rows.append({"policy": f"Model P{int(q * 100)}", "quantile": q, "avg_promised_days": float(promise.mean()),
                     "on_time_rate": float((test.days_to_deliver <= promise + 1).mean())})
    return pd.DataFrame(rows)
