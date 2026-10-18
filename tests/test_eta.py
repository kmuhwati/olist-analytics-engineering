"""Leak-freedom and correctness checks for the ETA feature builders and trade-off math."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from olist_analysis import eta  # noqa: E402


def orders():
    t0 = pd.Timestamp("2018-01-01")
    return pd.DataFrame({
        "seller_id": ["s1", "s1", "s1", "s2"],
        "purchased_at": [t0, t0 + pd.Timedelta(days=1), t0 + pd.Timedelta(days=20), t0 + pd.Timedelta(days=21)],
        "delivered_at": [t0 + pd.Timedelta(days=10), t0 + pd.Timedelta(days=30), t0 + pd.Timedelta(days=25), t0 + pd.Timedelta(days=22)],
        "days_to_deliver": [10.0, 29.0, 5.0, 1.0],
    })


def test_seller_history_only_counts_orders_already_delivered():
    d = orders()
    prior = eta._prior_delivered_mean(d)
    assert np.isnan(prior.iloc[0])          # nothing before the first order
    assert np.isnan(prior.iloc[1])          # order 0 not yet delivered on day 1
    assert prior.iloc[2] == 10.0            # by day 20 only order 0 has arrived (order 1 arrives day 30)
    assert np.isnan(prior.iloc[3])          # seller s2 has no history


def test_recent_network_mean_uses_only_past_deliveries():
    d = pd.concat([orders()] * 3, ignore_index=True)  # 3 copies so the n>=5 floor is met
    recent = eta._recent_delivered_mean(d, d.index, window_days=14)
    # Purchases on day 21: deliveries in (day 7, day 21) -> the three day-10 deliveries (10 days each)
    assert recent[d.purchased_at == pd.Timestamp("2018-01-22")].isna().all()  # only 3 deliveries -> below floor
    d2 = pd.concat([orders()] * 6, ignore_index=True)
    r2 = eta._recent_delivered_mean(d2, d2.index, window_days=14)
    assert r2[d2.purchased_at == pd.Timestamp("2018-01-21")].iloc[0] == pytest.approx(10.0)


def test_promise_tradeoff_on_time_uses_grace_day():
    test = pd.DataFrame({"days_to_deliver": [5.0, 10.0], "promised_days": [4.5, 20.0]})
    t = eta.promise_tradeoff(test, {0.5: np.array([4.2, 8.0])})
    assert t.iloc[0].on_time_rate == 1.0          # 5.0 <= 4.5 + 1
    assert t.iloc[1].on_time_rate == 0.5          # ceil(4.2)=5 -> on time; ceil(8)=8 -> 10 > 9 late
