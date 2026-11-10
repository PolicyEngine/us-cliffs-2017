"""scripts/take_up_bounds.py counts the cliffs that rest on full take-up."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("take_up_bounds", ROOT / "scripts" / "take_up_bounds.py")
tub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tub)

COLUMNS = sorted({c for cols in tub.groups(True).values() for c in cols})


def frame(**columns) -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    base = {c: np.zeros(n) for c in COLUMNS}
    base.update({"weight": np.ones(n), "d_net": np.zeros(n), "d_net_single_ptc": np.zeros(n)})
    base.update({k: np.asarray(v, dtype=float) for k, v in columns.items()})
    return pd.DataFrame(base)


def test_a_cliff_that_rests_on_a_state_benefit_disappears():
    # row 0: loses $300 of a state benefit and net income falls $100, so without it net income rises $200
    # row 1: loses $300 of a state benefit but net income falls $400, so it stays a cliff
    # row 2: no cliff
    rows = frame(d_net=[-100, -400, 50], d_household_state_benefits=[-300, -300, 0], weight=[2, 3, 5])
    result = tub.bounds(rows, "d_net", tub.groups(False))
    assert result["people_on_cliff"] == 5
    assert result["groups"]["state_benefits"]["cliffs_that_disappear"] == 2
    assert result["groups"]["state_benefits"]["share"] == pytest.approx(0.4)
    assert result["groups"]["school_meals"]["cliffs_that_disappear"] == 0


def test_wic_takes_up_as_drawn_so_no_group_holds_it():
    # WIC follows Microcosm's stored draw (cliffs2017.wic_take_up), so a cliff
    # that rests on WIC alone stays a cliff here
    rows = frame(d_net=[-100], d_wic=[-300])
    result = tub.bounds(rows, "d_net", tub.groups(True))
    assert not any("d_wic" in g["columns"] for g in result["groups"].values())
    assert result["groups"]["all_of_these"]["cliffs_that_disappear"] == 0


def test_rises_count_cliff_rows_where_the_group_rises():
    # row 0: CHIP rises $500 as Medicaid falls $900, still a cliff; row 1: CHIP falls
    rows = frame(d_net=[-400, -100], d_net_single_ptc=[-400, -100], d_chip=[500, -50], weight=[3, 4])
    result = tub.bounds(rows, "d_net_single_ptc", tub.groups(True))
    assert result["groups"]["chip"]["rises_in_cliff_rows"] == 3
    assert result["groups"]["chip"]["cliffs_that_disappear"] == 0
    assert result["groups"]["medicare_savings_programs"]["rises_in_cliff_rows"] == 0


def test_the_chip_group_removes_the_premium_too():
    # CHIP's value doesn't change but its premium rises $200 (a -200 contribution
    # to net income); a family that doesn't enroll pays no premium
    rows = frame(d_net=[-150], d_net_single_ptc=[-150], d_chip=[0], d_chip_premium=[-200])
    result = tub.bounds(rows, "d_net_single_ptc", tub.groups(True))
    assert result["groups"]["chip"]["columns"] == ["d_chip", "d_chip_premium"]
    assert result["groups"]["chip"]["cliffs_that_disappear"] == 1


def test_a_cliff_that_ends_exactly_at_zero_disappears():
    # the test needs net income to fall, so a change of exactly zero is no cliff
    rows = frame(d_net=[-250], d_free_school_meals=[-150], d_reduced_price_school_meals=[-100])
    result = tub.bounds(rows, "d_net", tub.groups(False))
    assert result["groups"]["school_meals"]["cliffs_that_disappear"] == 1
    assert result["groups"]["state_benefits"]["cliffs_that_disappear"] == 0


def test_groups_add_their_losses_together():
    # neither loss alone ends the cliff, together they do
    rows = frame(d_net=[-100], d_household_state_benefits=[-60], d_free_school_meals=[-60])
    result = tub.bounds(rows, "d_net", tub.groups(False))
    assert result["groups"]["state_benefits"]["cliffs_that_disappear"] == 0
    assert result["groups"]["school_meals"]["cliffs_that_disappear"] == 0
    assert result["groups"]["all_of_these"]["cliffs_that_disappear"] == 1


def test_health_groups_only_in_health_runs():
    assert set(tub.groups(False)) == {"school_meals", "state_benefits", "all_of_these"}
    assert set(tub.groups(True)) == {
        "school_meals", "state_benefits", "chip", "medicare_savings_programs", "state_health_programs",
        "all_of_these",
    }
    assert "d_chip" not in tub.groups(False)["all_of_these"]


def test_counted_once_uses_its_own_column():
    # the credit counted twice puts this adult on a cliff; counted once, it doesn't
    rows = frame(d_net=[-50], d_net_single_ptc=[30], d_chip=[-80])
    twice = tub.bounds(rows, "d_net", tub.groups(True))
    once = tub.bounds(rows, "d_net_single_ptc", tub.groups(True))
    assert twice["people_on_cliff"] == 1 and twice["groups"]["chip"]["cliffs_that_disappear"] == 1
    assert once["people_on_cliff"] == 0 and once["groups"]["chip"]["share"] == 0.0


def test_check_refuses_rows_that_miss_the_committed_count():
    rows = frame(d_net=[-1, -1], weight=[10, 10])
    result = tub.bounds(rows, "d_net", tub.groups(False))
    tub.check("run", result, 20.0)
    with pytest.raises(ValueError):
        tub.check("run", result, 21.0)


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.floats(-2000, 2000, allow_nan=False),
            st.floats(-1000, 0, allow_nan=False),
            st.floats(-1000, 0, allow_nan=False),
            st.floats(0.1, 1e4, allow_nan=False),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_bounds_never_exceed_the_count_and_grow_with_the_group(data):
    """For losses (changes at or below zero), a larger group removes at least as many cliffs."""
    d_net, d_state, d_meals, weight = map(list, zip(*data))
    rows = frame(d_net=d_net, d_household_state_benefits=d_state, d_free_school_meals=d_meals, weight=weight)
    result = tub.bounds(rows, "d_net", tub.groups(False))
    total = result["people_on_cliff"]
    for g in result["groups"].values():
        assert 0 <= g["cliffs_that_disappear"] <= total + 1e-9
    every = result["groups"]["all_of_these"]["cliffs_that_disappear"]
    for name in ("state_benefits", "school_meals"):
        assert result["groups"][name]["cliffs_that_disappear"] <= every + 1e-9
