"""Invariants of the cliff test with other changes in earnings (cliffs2017.changes).

Properties, for any inputs:
1. a change's label parses back to the same change;
2. no change takes more earnings than the adult has, a raise in dollars reaches
   every measured adult, a cut in dollars only those whose earnings reach it,
   a change in proportion to earnings only adults with earnings, and nobody
   the test doesn't measure;
3. the rule for "net income moves against earnings" is symmetric: flipping the
   signs of both the change and the change in net income gives the same flag.

On about 300 Microcosm households, in 2017 and 2025:
4. the $1,000 raise reproduces cliffs2017.decompose row for row (differential
   test against the code that made the committed counts);
5. for every change, the parts add up to the change in net income;
6. the change outside health coverage, taken from a run that counts health
   coverage, equals the change a run that doesn't count it computes (the
   premise that lets one run give both counts);
7. a cut matches a fresh simulation of the same households with the adult's
   earnings lowered (differential test of the branch machinery for cuts).

Test 6 allows a dollar, as tests/test_decompose.py does: the model holds
household values in float32, so the sum of the parts and a run's own total
differ by rounding.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cliffs2017.changes import (
    EARNINGS,
    Change,
    decompose_change,
    health_parts,
    moves_against,
    parse,
    person_changes,
    positive_earnings,
    without_health,
)
from cliffs2017.decompose import NET, decompose, household_values
from cliffs2017.medicaid import load_totals
from cliffs2017.simulation import build_simulation


YEARS = (2017, 2025)
MEDICAID_TOTALS = Path(__file__).parents[1] / "results" / "medicaid"


def configured(dataset, system, year, health):
    """The small dataset and the options the final runs use, as tests/test_decompose.py builds them,
    with CSFP left out from 2024 as scripts/run_final.sh does."""
    from cliffs2017.deflate import deflate

    data = dataset
    if year < int(dataset.time_period):
        data, _ = deflate(dataset, system, year)
    options = dict(health=health, aca_before_2018=year < 2018, leave_out_csfp=year >= 2024)
    if health:
        path = MEDICAID_TOTALS / f"totals_{year}_p4_s0.json"
        if not path.exists():
            pytest.fail(f"{path} is missing: run scripts/medicaid_totals.sh 4 0 first")
        options["medicaid_totals"] = load_totals(path)[0]
    return data, options

changes = st.one_of(
    st.integers(1, 100_000).map(lambda a: a * 1.0),
    st.integers(-100_000, -1).map(lambda a: a * 1.0),
).map(lambda a: Change(amount=a)) | st.integers(-99, 99).filter(bool).map(lambda s: Change(share=s / 100))


@given(changes)
def test_labels_parse_back(change):
    assert parse(change.label) == change
    assert parse(change.label).key == change.key


def test_parse_examples():
    assert parse("+1000") == Change(amount=1000)
    assert parse("-5,000") == Change(amount=-5000)
    assert parse("+1%") == Change(share=0.01)
    assert parse("-10%") == Change(share=-0.1)
    assert [parse(t).key for t in ("+1000", "-5000", "+1%", "-10%")] == [
        "raise_1000", "cut_5000", "raise_1pct", "cut_10pct"
    ]
    for bad in ("1000", "+", "+1e3", "--5", "+100%", "+0", "+0%"):
        with pytest.raises(ValueError):
            parse(bad)


people = st.lists(
    st.tuples(st.booleans(), st.floats(-50_000, 500_000, allow_nan=False), st.floats(-20_000, 50_000, allow_nan=False)),
    min_size=1,
    max_size=40,
)


@given(changes, people)
def test_person_changes(change, rows):
    measured = np.array([r[0] for r in rows])
    wages = np.array([r[1] for r in rows])
    self_employment = np.array([r[2] for r in rows])
    earnings = positive_earnings(wages, self_employment, np.zeros(len(rows)))
    amounts = person_changes(change, measured, earnings)
    reached = amounts != 0
    assert not reached[~measured].any()
    assert (earnings[reached] + amounts[reached] >= -1e-9 * np.maximum(1, earnings[reached])).all()
    assert (np.sign(amounts[reached]) == change.sign).all()
    if change.share:
        np.testing.assert_array_equal(reached, measured & (earnings > 0))
        np.testing.assert_allclose(amounts[reached], change.share * earnings[reached])
    elif change.amount > 0:
        np.testing.assert_array_equal(reached, measured)
        assert (amounts[reached] == change.amount).all()
    else:
        np.testing.assert_array_equal(reached, measured & (earnings >= -change.amount))
        assert (amounts[reached] == change.amount).all()


# Dollar amounts: zero, or at least a hundredth of a cent either way, so the product can't underflow.
dollars = st.one_of(st.just(0.0), st.floats(1e-4, 1e5), st.floats(-1e5, -1e-4))


@given(st.lists(st.tuples(dollars, dollars), min_size=1, max_size=30))
def test_moves_against_is_symmetric(pairs):
    c = np.array([p[0] for p in pairs])
    d = np.array([p[1] for p in pairs])
    np.testing.assert_array_equal(moves_against(c, d), moves_against(-c, -d))
    np.testing.assert_array_equal(moves_against(c, d), (c > 0) & (d < 0) | (c < 0) & (d > 0))


def test_moves_against_handles_tiny_values():
    # The product of these underflows to -0.0; the signs still disagree (review round 1, F5).
    assert moves_against([5.8e-205, 1e-300, -1e-300, 0.0], [-6.4e-167, -1e-300, 1e-300, -5.0]).tolist() == [
        True, True, True, False,
    ]


@pytest.mark.parametrize("year", YEARS)
def test_raise_of_1000_reproduces_decompose(system, small_dataset, year):
    data, options = configured(small_dataset, system, year, True)
    sim = build_simulation(data, year, **options)
    ours = decompose_change(sim, year, Change(amount=1000))
    theirs = decompose(sim, year)
    assert len(ours) == len(theirs) > 100
    for column in theirs.columns:
        if column == "delta":
            assert (ours["change"] == theirs["delta"]).all()
            continue
        np.testing.assert_array_equal(ours[column].to_numpy(), theirs[column].to_numpy(), err_msg=column)


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("text", ["-1000", "+5000", "-5000", "+1%", "-10%"])
def test_parts_add_up_and_one_run_gives_both_counts(system, small_dataset, year, text):
    change = parse(text)
    data, options = configured(small_dataset, system, year, True)
    health = build_simulation(data, year, **options)
    frame = decompose_change(health, year, change)
    assert len(frame) > 50
    np.testing.assert_allclose(frame["d_parts"], frame["d_net"], atol=1.0)
    assert (np.sign(frame["change"]) == change.sign).all()
    plain_options = {k: v for k, v in options.items() if k != "medicaid_totals"}
    plain = build_simulation(data, year, **dict(plain_options, health=False))
    other = decompose_change(plain, year, change)
    assert health_parts(plain, year) == []
    merged = frame.merge(other[["person_index", "rank", "change", "d_net"]], on=["person_index", "rank"], suffixes=("", "_plain"))
    assert len(merged) == len(frame) == len(other)
    np.testing.assert_array_equal(merged["change"], merged["change_plain"])
    # without_health reads a decompose_change frame; the plain run's change rides alongside, so drop it first.
    rest = without_health(merged.drop(columns=["d_net_plain"]), health_parts(health, year))
    # The model holds household values in float32, so the sum of the parts and the plain run's
    # total differ by rounding: $0.125 is float32's step between $1 million and $2 million.
    # A dollar, as tests/test_decompose.py allows.
    np.testing.assert_allclose(rest, merged["d_net_plain"], atol=1.0)
    clear = np.abs(merged["d_net_plain"]) > 1.0
    np.testing.assert_array_equal(
        moves_against(merged["change"][clear], rest[clear]),
        moves_against(merged["change"][clear], merged["d_net_plain"][clear]),
    )


@pytest.mark.parametrize("year", YEARS)
def test_cut_matches_fresh_simulation(system, small_dataset, year):
    from policyengine_us.variables.gov.simulation.behavioral_response_measurements import (
        PRE_RESPONSE_INPUTS,
    )
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        earnings_increments,
        user_set_variables,
    )

    change = Change(amount=-5000)
    data, options = configured(small_dataset, system, year, True)
    base = build_simulation(data, year, **options)
    frame = decompose_change(base, year, change, ("aca_magi_fraction",))
    base_net = household_values(base, [NET], year)[NET]
    person = base.populations["person"]
    household_index = np.asarray(base.populations["household"].members_entity_id)
    rank = np.asarray(base.calculate("adult_earnings_index", year))
    is_adult = np.asarray(base.calculate("is_adult", year)).astype(bool)
    earnings = positive_earnings(*(np.asarray(base.calculate(v, year)) for v in EARNINGS))
    inputs = user_set_variables(base, year)
    for k in sorted(frame["rank"].unique()):
        amounts = person_changes(change, is_adult & (rank == k), earnings)
        lowered = {}
        for variable, increment in earnings_increments(person, year, amounts).items():
            name = variable if variable in inputs else PRE_RESPONSE_INPUTS.get(variable, variable)
            before = np.asarray(base.calculate(name, year), dtype=np.float64)
            lowered[name] = before + increment
            # A cut moves only positive parts of earnings, and none below zero.
            assert (increment[before <= 0] == 0).all(), name
            assert (lowered[name][before > 0] >= -1e-6).all(), name
        fresh = build_simulation(data, year, **options)
        for name, value in lowered.items():
            fresh.set_input(name, year, value)
        fresh_net = household_values(fresh, [NET], year)[NET]
        fresh_fraction = np.asarray(fresh.calculate("aca_magi_fraction", year, map_to="person"), dtype=float)
        rows = frame[frame["rank"] == k]
        expected = (fresh_net - base_net)[household_index[rows["person_index"]]]
        np.testing.assert_allclose(rows["d_net"], expected, atol=1.0)
        np.testing.assert_allclose(rows["alt_aca_magi_fraction"], fresh_fraction[rows["person_index"]], atol=1e-6)


def test_without_health_drops_only_health_parts():
    frame = pd.DataFrame(
        {
            "d_household_market_income": [-1000.0],
            "d_snap": [300.0],
            "d_medicaid_cost": [5000.0],
            "d_marketplace_net_premium": [-200.0],
            "d_net": [4100.0],
            "d_parts": [4100.0],
            "d_net_single_ptc": [4300.0],
        }
    )
    got = without_health(frame, ["d_medicaid_cost", "d_marketplace_net_premium"])
    assert got.tolist() == [-700.0]
