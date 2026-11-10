"""scripts/counted_once.py: Medicaid's value and the premium tax credit, counted once.

Invariants:
1. Under the credit's 2017 income test, and when the raise doesn't lower
   income, a tax unit fails the test after the raise exactly when the raise
   lifts it from an eligible start past 400% of the poverty line.
2. Scaling every Medicaid value by f adds (f - 1) times the Medicaid change to
   the counted-once change in net income (differential test against a fresh
   simulation with Medicaid's denominators divided by f).
3. Combining adds disjoint parts up, and refuses parts that differ in their
   settings, miss a part or don't add up to the final run.
On one household, a 60-year-old just under 400% of the poverty line in 2017
loses the whole credit to the raise, and one well under it faces no cliff.
"""

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.counted_once import (  # noqa: E402
    HEADLINE,
    LIMIT,
    OUTCOMES,
    combine,
    compute,
    ptc_outcomes,
    summarize,
)


def eligible_2017(fraction):
    """gov.aca.ptc_income_eligibility in 2017: from 100% up to, not including, 400%."""
    fraction = np.asarray(fraction, dtype=float)
    return (fraction >= 1) & (fraction < LIMIT)


def test_outcomes_on_examples():
    found = ptc_outcomes(
        base_fraction=[3.95, 3.50, 4.00, 0.95, 3.99],
        alt_fraction=[4.04, 3.60, 4.10, 1.05, 3.99],
        base_credit=[5_000, 1_000, 0, 0, 200],
        alt_credit=[0, 900, 0, 300, 0],
        income_eligible=eligible_2017,
    )
    assert found["lifted_past_400"].tolist() == [True, False, False, False, False]
    assert found["lose_income_test"].tolist() == [True, False, False, False, False]
    # The last adult's credit ends without their income crossing the limit.
    assert found["lose_whole_credit"].tolist() == [True, False, False, False, True]


@pytest.mark.parametrize("year, at_limit", [(2017, False), (2025, True)])
def test_limit_matches_the_model(system, year, at_limit):
    """LIMIT is where the model's income test ends in 2017, and not in 2025."""
    calc = system.parameters(year).gov.aca.ptc_income_eligibility.calc
    eligible = np.asarray(calc(np.array([LIMIT - 0.01, LIMIT]))).astype(bool)
    assert eligible.tolist() == [True, at_limit]


fractions = st.floats(0, 8, allow_nan=False).map(lambda x: np.floor(100 * x) / 100)


@given(st.lists(st.tuples(fractions, fractions), min_size=1, max_size=50))
def test_losing_the_test_means_crossing_400(pairs):
    base = np.array([min(a, b) for a, b in pairs])
    alt = np.array([max(a, b) for a, b in pairs])
    zeros = np.zeros(len(pairs))
    found = ptc_outcomes(base, alt, zeros, zeros, eligible_2017)
    np.testing.assert_array_equal(found["lose_income_test"], found["lifted_past_400"] & (base >= 1))


def test_summarize_weights_each_outcome():
    flags = {name: np.array([True, False, True]) for name in OUTCOMES}
    flags["lose_whole_credit"] = np.array([False, False, False])
    out = summarize([1.0, 2.0, 4.0], flags)
    assert out["people"] == 7.0 and out["sample_people"] == 3
    assert out["lifted_past_400"] == 5.0 and out["sample_lifted_past_400"] == 2
    assert out["lose_whole_credit"] == 0.0 and out["sample_lose_whole_credit"] == 0


def parts_and_final():
    shared = dict(
        year=2017,
        health_benefits_in_net_income=True,
        aca_before_2018=True,
        leave_out_csfp=False,
        parts=2,
        seed=0,
        versions={"policyengine-us": "2.116.0", "policyengine-core": "3.34.10"},
        dataset="d",
        code={"commit": "c"},
    )
    parts = []
    for i in range(2):
        counts = {k: 10.0 * (i + 1) + j for j, k in enumerate(HEADLINE)}
        ptc = dict(people=1.0 + i, sample_people=1)
        for name in OUTCOMES:
            ptc[name] = 1.0 + i
            ptc[f"sample_{name}"] = 1
        parts.append(
            dict(
                shared,
                part=i,
                counted_once=counts,
                medicaid_value_scaled_counted_once={"0.8": counts},
                medicaid_value_scaled_model={"0.8": counts},
                premium_tax_credit_largest_loss=ptc,
            )
        )
    total = {k: parts[0]["counted_once"][k] + parts[1]["counted_once"][k] for k in HEADLINE}
    final = {
        key: shared[key]
        for key in ("year", "health_benefits_in_net_income", "aca_before_2018", "leave_out_csfp", "parts", "seed", "versions", "dataset")
    }
    final["premium_tax_credit_counted_once"] = dict(total, people_on_cliff_by_driver={"assigned_aca_ptc": 3.0})
    final["medicaid_value_scaled"] = {"0.8": total}
    return parts, final


def test_combine_adds_the_parts():
    parts, final = parts_and_final()
    out = combine(parts, final)
    assert out["counted_once"]["people_on_cliff"] == 30.0
    assert out["medicaid_value_scaled_counted_once"]["0.8"]["people_in_those_households"] == 10 + 3 + 20 + 3
    assert out["premium_tax_credit_largest_loss"]["people"] == 3.0
    assert out["premium_tax_credit_largest_loss"]["sample_lifted_past_400"] == 2


@pytest.mark.parametrize(
    "spoil",
    [
        lambda parts, final: parts[1].update(seed=1),
        lambda parts, final: parts[1].update(code={"commit": "other"}),
        lambda parts, final: parts[1].update(part=0),
        lambda parts, final: parts.pop(),
        lambda parts, final: final.update(aca_before_2018=False),
        lambda parts, final: final["premium_tax_credit_counted_once"].update(people_on_cliff=31.0),
        lambda parts, final: final["medicaid_value_scaled"]["0.8"].update(workers_on_cliff=0.0),
        lambda parts, final: final["premium_tax_credit_counted_once"].update(people_on_cliff_by_driver={}),
    ],
    ids=["seed", "code", "duplicate part", "missing part", "final settings", "final count", "final scaling", "final drivers"],
)
def test_combine_refuses(spoil):
    parts, final = parts_and_final()
    parts, final = copy.deepcopy(parts), copy.deepcopy(final)
    spoil(parts, final)
    with pytest.raises(ValueError):
        combine(parts, final)


def household(year, earnings):
    """A 60-year-old in Wake County, North Carolina, with no employer coverage."""
    return {
        "people": {
            "adult": {"age": {year: 60}, "has_esi": {year: False}, "employment_income": {year: earnings}}
        },
        "tax_units": {"tu": {"members": ["adult"]}},
        "spm_units": {"spm": {"members": ["adult"]}},
        "households": {
            "h": {"members": ["adult"], "state_code": {year: "NC"}, "county_str": {year: "WAKE_COUNTY_NC"}}
        },
    }


def one_household(year, earnings):
    from policyengine_us import Simulation

    from cliffs2017.simulation import reforms

    sim = Simulation(situation=household(year, earnings), reform=reforms(health=True, aca_before_2018=year < 2018))
    people = pd.DataFrame(dict(household_id=[0], weight=[1.0], worker=[True]))
    return sim, compute(sim, year, people)


def test_raise_past_400_ends_the_credit():
    # $47,000 is 395% of the 2016 poverty line for one person ($11,880); $48,000 is 404%.
    sim, out = one_household(2017, 47_000)
    assert float(sim.calculate("aca_magi_fraction", 2017)[0]) == pytest.approx(3.95)
    assert float(sim.calculate("assigned_aca_ptc", 2017)[0]) > 1_000
    assert out["counted_once"]["people_on_cliff"] == 1.0
    ptc = out["premium_tax_credit_largest_loss"]
    assert ptc["sample_people"] == 1
    assert all(ptc[f"sample_{name}"] == 1 for name in OUTCOMES)
    # Losing Medicaid can't move this adult: they have none to lose.
    for counts in out["medicaid_value_scaled_counted_once"].values():
        assert counts == out["counted_once"]


def test_no_cliff_well_below_400():
    _, out = one_household(2017, 30_000)
    assert out["counted_once"]["people_on_cliff"] == 0.0
    assert out["premium_tax_credit_largest_loss"]["sample_people"] == 0


def test_scaling_medicaid_matches_a_fresh_simulation(system, small_dataset):
    """The counted-once shortcut: scaling Medicaid by f adds (f - 1) x its change."""
    from test_decompose import configured

    from cliffs2017.decompose import decompose
    from cliffs2017.simulation import build_simulation

    year, f = 2017, 0.8
    data, options = configured(small_dataset, system, year, True)
    frame = decompose(build_simulation(data, year, **options), year)
    totals = options["medicaid_totals"].copy()
    totals["denominator"] = totals["denominator"] / f
    scaled = decompose(build_simulation(data, year, **dict(options, medicaid_totals=totals)), year)
    assert (frame["person_index"].to_numpy() == scaled["person_index"].to_numpy()).all()
    predicted = frame["d_net_single_ptc"] + (f - 1) * frame["d_medicaid_cost"]
    np.testing.assert_allclose(scaled["d_net_single_ptc"], predicted, atol=1.0)
    assert (frame["d_medicaid_cost"] < 0).any()
