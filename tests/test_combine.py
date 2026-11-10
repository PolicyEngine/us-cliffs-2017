"""Invariants of adding disjoint household parts (cliffs2017.combine).

1. Splitting households into parts at full weight and adding the parts'
   headline counts gives the counts of the whole sample (differential test
   against cliffs2017.run.headline on the unsplit data).
2. The result does not depend on the order of the parts.
3. Combined standard errors add the parts' variances.
4. Parts that disagree on configuration, or that leave a gap, are refused.
"""

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cliffs2017.combine import HEADLINE, combine
from cliffs2017.run import bootstrap, headline


@st.composite
def split_households(draw):
    sizes = draw(st.lists(st.integers(1, 5), min_size=3, max_size=30))
    weights = draw(
        st.lists(st.floats(1, 5_000, allow_nan=False), min_size=len(sizes), max_size=len(sizes))
    )
    parts = draw(st.integers(1, 4))
    groups = draw(st.lists(st.integers(0, parts - 1), min_size=len(sizes), max_size=len(sizes)))
    rows = [(h, w) for h, (size, w) in enumerate(zip(sizes, weights)) for _ in range(size)]
    people = pd.DataFrame(rows, columns=["household_id", "weight"])
    n = len(people)
    people["worker"] = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    on_cliff = np.array(draw(st.lists(st.booleans(), min_size=n, max_size=n)))
    group = np.array(groups)[people["household_id"].to_numpy()]
    return people, on_cliff, parts, group


def part_result(people, on_cliff, parts, index, year=2017):
    counts = headline(people, on_cliff)
    return dict(
        year=year,
        health_benefits_in_net_income=False,
        aca_before_2018=True,
        parts=parts,
        part=index,
        seed=0,
        versions={"policyengine-us": "x"},
        dataset="d",
        python="3",
        deflation=[],
        people_total=float(people["weight"].sum()),
        households_total=float(people.groupby("household_id")["weight"].first().sum()),
        workers=float(people["weight"][people["worker"]].sum()) or 1.0,
        workers_evaluated=0.0,
        cliff_gap_total=0.0,
        sample_people_on_cliff=int(on_cliff.sum()),
        sample_households=int(people["household_id"].nunique()),
        standard_errors=bootstrap(people, on_cliff, draws=10, seed=index),
        program_totals={"snap": 1.0},
        people_in_recipient_units={"snap": 2.0},
        timing_seconds={"total": 1.0},
        **counts,
    )


def split(people, on_cliff, parts, group):
    results = []
    for i in range(parts):
        keep = group == i
        results.append(
            part_result(people[keep].reset_index(drop=True), on_cliff[keep], parts, i)
        )
    return results


@given(split_households())
def test_parts_add_up_to_the_whole(data):
    people, on_cliff, parts, group = data
    combined = combine(split(people, on_cliff, parts, group))
    whole = headline(people, on_cliff)
    for key in HEADLINE:
        assert combined[key] == pytest.approx(whole[key], rel=1e-9, abs=1e-6)
    assert combined["sample_people_on_cliff"] == int(on_cliff.sum())
    assert combined["sample_households"] == people["household_id"].nunique()


@given(split_households(), st.randoms())
def test_order_does_not_matter(data, rng):
    people, on_cliff, parts, group = data
    results = split(people, on_cliff, parts, group)
    shuffled = results[:]
    rng.shuffle(shuffled)
    a, b = combine(results), combine(shuffled)
    for key in HEADLINE:
        assert a[key] == pytest.approx(b[key], rel=1e-12, abs=1e-9)
    for key in HEADLINE:
        assert a["standard_errors"][key] == pytest.approx(b["standard_errors"][key], rel=1e-12)


@given(split_households())
def test_variances_add(data):
    people, on_cliff, parts, group = data
    results = split(people, on_cliff, parts, group)
    combined = combine(results)
    for key in HEADLINE:
        expected = math.sqrt(sum(r["standard_errors"][key] ** 2 for r in results))
        assert combined["standard_errors"][key] == pytest.approx(expected)


def test_leaves_out_medicaid_value_without_full_sample_totals():
    """Parts without Medicaid's full-sample totals don't add up to its total value."""
    people = pd.DataFrame(dict(household_id=[0, 1], weight=[1.0, 2.0], worker=[True, False]))
    on_cliff = np.array([True, False])
    a = part_result(people.iloc[:1], on_cliff[:1], 2, 0)
    b = part_result(people.iloc[1:].reset_index(drop=True), on_cliff[1:], 2, 1)
    for part in (a, b):
        part["program_totals"] = {"snap": 1.0, "medicaid_cost": 5.0}
    combined = combine([a, b])
    assert "medicaid_cost" not in combined["program_totals"]
    assert combined["program_totals"]["snap"] == 2.0
    assert "medicaid_cost" in combined["program_totals_left_out"]


def test_refuses_mismatched_or_missing_parts():
    people = pd.DataFrame(dict(household_id=[0, 1], weight=[1.0, 2.0], worker=[True, False]))
    on_cliff = np.array([True, False])
    a = part_result(people.iloc[:1], on_cliff[:1], 2, 0)
    b = part_result(people.iloc[1:].reset_index(drop=True), on_cliff[1:], 2, 1)
    combine([a, b])
    with pytest.raises(ValueError, match="parts 0..1"):
        combine([a])
    with pytest.raises(ValueError, match="parts 0..1"):
        combine([a, dict(a)])
    with pytest.raises(ValueError, match="disagree on year"):
        combine([a, dict(b, year=2025)])


def test_runs_without_the_csfp_option_count_as_leaving_csfp_in():
    """A part from before --leave-out-csfp combines with a part that ran without it."""
    people = pd.DataFrame(dict(household_id=[0, 1], weight=[1.0, 2.0], worker=[True, False]))
    on_cliff = np.array([True, False])
    a = part_result(people.iloc[:1], on_cliff[:1], 2, 0)
    b = part_result(people.iloc[1:].reset_index(drop=True), on_cliff[1:], 2, 1)
    assert combine([a, dict(b, leave_out_csfp=False)])["leave_out_csfp"] is False
    assert combine([dict(a, leave_out_csfp=True), dict(b, leave_out_csfp=True)])["leave_out_csfp"] is True
    with pytest.raises(ValueError, match="disagree on leave_out_csfp"):
        combine([a, dict(b, leave_out_csfp=True)])
