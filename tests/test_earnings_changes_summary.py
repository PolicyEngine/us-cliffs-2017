"""The summary's bookkeeping (scripts/earnings_changes_summary.py), on made-up rows.

1. Either side: every adult flagged under a raise or the cut of the same size
   gets exactly one row, whichever change reaches them.
2. The part that moves most against a change: the largest loss under a raise,
   the largest gain under a cut, never market income, and with health coverage
   counted once the marketplace premium net of the credit is left out.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.earnings_changes_summary import driver, either_side, moving_parts  # noqa: E402


@given(st.data())
def test_either_side_counts_each_adult_once(data):
    n = data.draw(st.integers(1, 30))
    reached_up = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    reached_down = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    person, keys, up_flags, down_flags = [], [], [], []
    for i in range(n):
        for key, reached in (("raise_1000", reached_up[i]), ("cut_1000", reached_down[i])):
            if reached:
                person.append(i)
                keys.append(key)
                flag = data.draw(st.booleans())
                up_flags.append(flag and key == "raise_1000")
                down_flags.append(flag and key == "cut_1000")
    person = np.array(person, dtype=int)
    keys = np.array(keys, dtype=object)
    either = either_side(person, keys, "raise_1000", "cut_1000", up_flags, down_flags)
    expected = set(person[np.array(up_flags, dtype=bool)]) | set(person[np.array(down_flags, dtype=bool)])
    assert sorted(person[either]) == sorted(expected)
    # The raise's row wins whenever the raise reaches the adult.
    for i in expected:
        row = np.flatnonzero(either & (person == i))[0]
        assert keys[row] == ("raise_1000" if reached_up[i] else "cut_1000")


def test_driver_and_parts():
    rows = pd.DataFrame(
        {
            "d_household_market_income": [1000.0, -1000.0],
            "d_snap": [-300.0, 250.0],
            "d_medicaid_cost": [-1500.0, 0.0],
            "d_marketplace_net_premium": [-2000.0, 0.0],
            "d_assigned_aca_ptc": [0.0, 900.0],
            "d_net": [-2800.0, 150.0],
            "d_parts": [-2800.0, 150.0],
            "d_net_single_ptc": [-800.0, 150.0],
            "d_net_without_health": [700.0, -750.0],
        }
    )
    health = ["d_medicaid_cost", "d_assigned_aca_ptc", "d_marketplace_net_premium"]
    with_health = moving_parts(rows, "with_health", health)
    assert "d_marketplace_net_premium" not in with_health and "d_household_market_income" not in with_health
    assert moving_parts(rows, "without_health", health) == ["d_snap"]
    assert list(driver(rows.iloc[[0]], with_health, 1)) == ["medicaid_cost"]
    assert list(driver(rows.iloc[[1]], with_health, -1)) == ["assigned_aca_ptc"]
