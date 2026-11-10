"""Invariants of the full-sample Medicaid totals (cliffs2017.medicaid).

1. The per-state sums add across disjoint sets of people, so totals built from
   the parts of a sample equal totals built from the whole (additivity).
2. The totals follow PolicyEngine-US's own formulas: a numpy replica of
   ``medicaid_slcsp_state_average_cost_index``, ``..._cost_index_filled``,
   ``..._state_denominator`` and ``medicaid_cost_if_enrolled`` on random people,
   and the model itself on Microcosm households (differential tests).
3. Over the sample the totals come from, Medicaid's value adds up to each
   state's spending, for every state with enrollees (conservation).
4. With the totals fixed, a household's Medicaid value is the same whichever
   part of the sample holds it. With the model's own formulas it is not, which
   is why the module exists (intended violation, asserted so a model change
   that removes it shows up here).
5. The average cost index lies between the smallest and largest positive index
   in its state (bounds).
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from cliffs2017.deflate import deflate, partition
from cliffs2017.medicaid import (
    add_sums,
    fixed_state_totals,
    simulation_sums,
    state_spending,
    sums_from_arrays,
    totals_from_sums,
)
from cliffs2017.simulation import build_simulation

STATES = np.array(["AK", "CA", "TX", "VT"])
SPENDING = {"AK": 2.5e9, "CA": 1.5e11, "TX": 4.0e10, "VT": 1.9e9}


@st.composite
def people(draw):
    n = draw(st.integers(1, 60))
    state = STATES[draw(hnp.arrays(np.int64, n, elements=st.integers(0, len(STATES) - 1)))]
    # Microcosm's positive household weights run from 5.5e-5 to 5.1e4. A weight
    # near the smallest double (5e-324) makes spending / denominator overflow to
    # infinity, in the model's formula as in this replica, so the weights stop at
    # 1e-6, and exact zeros stay in.
    weight = draw(
        hnp.arrays(np.float64, n, elements=st.one_of(st.just(0.0), st.floats(1e-6, 1e5)))
    )
    index = draw(
        hnp.arrays(np.float64, n, elements=st.one_of(st.just(0.0), st.floats(1e-3, 5e4)))
    )
    enrolled = draw(hnp.arrays(np.bool_, n))
    part = draw(hnp.arrays(np.int64, n, elements=st.integers(0, 3)))
    return state, weight, index, enrolled, part


def replica(state, weight, index, enrolled):
    """PolicyEngine-US's four formulas, line for line, over one simulation's people."""
    average = np.ones(len(state))
    denominator = np.zeros(len(state))
    positive = index > 0
    for s in np.unique(state):
        here = state == s
        state_weight = np.sum((weight * positive)[here])
        if state_weight > 0:
            average[here] = np.sum((weight * index * positive)[here]) / state_weight
    filled = np.where(positive, index, average)
    for s in np.unique(state):
        here = state == s
        denominator[here] = np.sum((weight * filled * enrolled)[here])
    spending = np.array([SPENDING[s] for s in state])
    cost = np.divide(spending * filled, denominator, out=np.zeros(len(state)), where=denominator > 0)
    return average, denominator, cost


@given(people())
def test_sums_add_across_parts(data):
    state, weight, index, enrolled, part = data
    whole = sums_from_arrays(state, weight, index, enrolled)
    pieces = [
        sums_from_arrays(state[part == k], weight[part == k], index[part == k], enrolled[part == k])
        for k in range(4)
        if (part == k).any()
    ]
    combined = add_sums(pieces)
    pd.testing.assert_frame_equal(combined, whole, check_exact=False, rtol=1e-9, atol=1e-6)
    pd.testing.assert_frame_equal(
        totals_from_sums(combined), totals_from_sums(whole), check_exact=False, rtol=1e-9, atol=1e-6
    )


@given(people())
def test_totals_match_the_model_formulas(data):
    state, weight, index, enrolled, _ = data
    average, denominator, _ = replica(state, weight, index, enrolled)
    totals = totals_from_sums(sums_from_arrays(state, weight, index, enrolled))
    np.testing.assert_allclose(
        totals.loc[state, "average_cost_index"], average, rtol=1e-9, atol=1e-9
    )
    np.testing.assert_allclose(totals.loc[state, "denominator"], denominator, rtol=1e-9, atol=1e-6)


@given(people())
def test_value_adds_up_to_spending(data):
    state, weight, index, enrolled, _ = data
    _, denominator, cost = replica(state, weight, index, enrolled)
    for s in np.unique(state):
        here = state == s
        if denominator[here][0] > 0:
            total = np.sum((weight * cost * enrolled)[here])
            np.testing.assert_allclose(total, SPENDING[s], rtol=1e-9)


@given(people())
def test_average_lies_within_the_state_indices(data):
    state, weight, index, enrolled, _ = data
    totals = totals_from_sums(sums_from_arrays(state, weight, index, enrolled))
    for s in np.unique(state):
        here = (state == s) & (index > 0) & (weight > 0)
        average = totals.loc[s, "average_cost_index"]
        if here.any():
            assert index[here].min() * (1 - 1e-9) <= average <= index[here].max() * (1 + 1e-9)
        else:
            assert average == 1.0


# Microcosm households: one module-level run per year shares its simulations.

YEARS = [2017, 2025]


def _people_frame(sim, year, variable):
    return pd.Series(
        np.asarray(sim.calculate(variable, year).values, dtype=np.float64),
        index=np.asarray(sim.calculate("person_id", year).values),
    )


@pytest.fixture(scope="module", params=YEARS)
def case(request, system, small_dataset):
    year = request.param
    data = small_dataset
    if year < int(small_dataset.time_period):
        data, _ = deflate(small_dataset, system, year)
    options = dict(health=True, aca_before_2018=year < 2018)

    # The model's own formulas over the whole sample. Sums come first: the
    # check in simulation_sums needs a simulation that hasn't computed the totals.
    stock = build_simulation(data, year, **options)
    sums = simulation_sums(stock, year)
    totals = totals_from_sums(sums)
    stock_cost = _people_frame(stock, year, "medicaid_cost_if_enrolled")

    fixed = build_simulation(data, year, **options, medicaid_totals=totals)
    fixed_cost = _people_frame(fixed, year, "medicaid_cost_if_enrolled")
    weight = _people_frame(fixed, year, "person_weight")
    enrolled_cost = _people_frame(fixed, year, "medicaid_cost")

    parts = []
    for k in range(2):
        piece = partition(small_dataset, 2, k, seed=3)
        if year < int(piece.time_period):
            piece, _ = deflate(piece, system, year)
        part_stock = build_simulation(piece, year, **options)
        part_sums = simulation_sums(part_stock, year)
        part_stock_cost = _people_frame(part_stock, year, "medicaid_cost_if_enrolled")
        part_fixed = build_simulation(piece, year, **options, medicaid_totals=totals)
        parts.append(
            dict(
                sums=part_sums,
                stock_cost=part_stock_cost,
                fixed_cost=_people_frame(part_fixed, year, "medicaid_cost_if_enrolled"),
            )
        )
    return dict(
        year=year,
        system=system,
        sums=sums,
        totals=totals,
        stock_cost=stock_cost,
        fixed_cost=fixed_cost,
        weight=weight,
        enrolled_cost=enrolled_cost,
        parts=parts,
    )


def test_model_sums_add_across_parts(case):
    combined = add_sums(part["sums"] for part in case["parts"])
    pd.testing.assert_frame_equal(combined, case["sums"], check_exact=False, rtol=1e-6, atol=1e-3)


def test_fixed_totals_reproduce_the_model(case):
    """Fixed at the sample's own totals, each person's value matches the model's.

    In 2025 the only reform turns on health benefits in net income, which leaves
    enrollment and cost indices alone, so the model's baseline denominator
    equals the reform's. In 2017 the pre-2018 premium tax credit reform changes
    the benchmark premium behind the cost index, and the model takes the
    denominator from the unreformed policy; the fixed totals take both from the
    reform, so the two differ there by design.
    """
    if case["year"] >= 2018:
        np.testing.assert_allclose(case["fixed_cost"], case["stock_cost"], rtol=1e-4, atol=1e-2)
    else:
        assert not np.allclose(case["fixed_cost"], case["stock_cost"], rtol=1e-4)


def test_value_adds_up_to_spending_in_the_model(case):
    totals = case["totals"]
    funded = totals.index[totals["denominator"] > 0]
    spending = state_spending(case["system"], case["year"], funded)
    total = float((case["weight"] * case["enrolled_cost"]).sum())
    np.testing.assert_allclose(total, spending.sum(), rtol=1e-4)


def test_fixed_value_does_not_depend_on_the_part(case):
    for part in case["parts"]:
        expected = case["fixed_cost"].loc[part["fixed_cost"].index]
        np.testing.assert_allclose(part["fixed_cost"], expected, rtol=1e-6, atol=1e-3)


def test_model_value_depends_on_the_part(case):
    """The model's own formulas value the same person differently in a part."""
    differs = [
        not np.allclose(part["stock_cost"], case["stock_cost"].loc[part["stock_cost"].index], rtol=1e-3)
        for part in case["parts"]
    ]
    assert all(differs)


def test_lookups_refuse_other_years_and_unknown_states(system, small_dataset):
    totals = pd.DataFrame(
        {"average_cost_index": [1.0], "denominator": [1.0]}, index=pd.Index(["ZZ"], name="state")
    )
    sim = build_simulation(small_dataset, 2025, health=True, medicaid_totals=totals)
    with pytest.raises(KeyError, match="no full-sample total"):
        sim.calculate("medicaid_slcsp_state_denominator", 2025)
    with pytest.raises(ValueError, match="cover 2025"):
        sim.calculate("medicaid_slcsp_state_average_cost_index", 2026)


def one_person_in(state, year):
    return {
        "people": {"p": {"age": {year: 30}}},
        "households": {"h": {"members": ["p"], "state_code": {year: state}}},
    }


def test_reform_returns_the_fixed_totals():
    from policyengine_us import Simulation

    reform = fixed_state_totals(
        pd.DataFrame({"average_cost_index": [2.0], "denominator": [3.0]}, index=["CA"]), 2025
    )
    sim = Simulation(situation=one_person_in("CA", 2025), reform=reform)
    assert sim.calculate("medicaid_slcsp_state_average_cost_index", 2025).tolist() == [2.0]
    assert sim.calculate("medicaid_slcsp_state_denominator", 2025).tolist() == [3.0]


def raise_on_aggregates():
    """A reform under which computing either state total raises, in any branch."""
    from policyengine_core.reforms import Reform
    from policyengine_us.model_api import USD, YEAR, Person, Variable

    def formula(person, period, parameters):
        raise AssertionError("a Medicaid state total was computed")

    class medicaid_slcsp_state_average_cost_index(Variable):
        value_type = float
        entity = Person
        label = "raises"
        unit = USD
        definition_period = YEAR

    class medicaid_slcsp_state_denominator(Variable):
        value_type = float
        entity = Person
        label = "raises"
        unit = USD
        definition_period = YEAR

    medicaid_slcsp_state_average_cost_index.formula = formula
    medicaid_slcsp_state_denominator.formula = formula

    class RaiseOnAggregates(Reform):
        def apply(self):
            self.replace_variable(medicaid_slcsp_state_average_cost_index)
            self.replace_variable(medicaid_slcsp_state_denominator)

    return RaiseOnAggregates


@pytest.mark.parametrize("year", YEARS)
def test_sums_never_compute_the_totals(system, small_dataset, year):
    """Gathering the sums' inputs never reaches either total, in any branch.

    simulation_sums's own check sees only the main simulation's holders; a
    branch made inside a formula keeps its own storage. Here the totals raise
    whenever they are computed.
    """
    from policyengine_us import Microsimulation

    from cliffs2017.simulation import reforms

    data = small_dataset
    if year < int(small_dataset.time_period):
        data, _ = deflate(small_dataset, system, year)
    base = reforms(True, year < 2018, None, year, year >= 2024) or ()
    sim = Microsimulation(
        dataset=data,
        reform=tuple(base) + (raise_on_aggregates(),),
        dataset_end_year=max(year, int(data.time_period)),
    )
    sums = simulation_sums(sim, year)
    assert len(sums) > 10
    with pytest.raises(AssertionError, match="state total was computed"):
        sim.calculate("medicaid_cost_if_enrolled", year)
