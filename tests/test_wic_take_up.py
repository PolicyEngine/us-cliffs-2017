"""WIC take-up from Microcosm's stored draw (cliffs2017.wic_take_up).

Invariants:
1. Every simulation build_simulation makes sets ``takes_up_wic_if_eligible``
   to the stored ``would_claim_wic`` for every month it covers, and records
   the rename.
2. WIC under the mapping equals WIC under full take-up times the draw, for
   every person and month, in 2017 and 2025 (``wic`` is defined only for
   people who take it up).
3. The branches PolicyEngine-US makes to raise each adult's earnings start
   from the draw.
4. The mapping does nothing when the engine reads the old name or the data
   store the new one, and refuses a person table out of the simulation's
   order or holding values that aren't boolean.
5. Medicaid's state totals don't change: no Medicaid formula reads WIC, so the
   totals files computed before the mapping still hold.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cliffs2017.deflate import deflate
from cliffs2017.simulation import build_simulation
from cliffs2017.wic_take_up import (
    LEGACY,
    LIVE,
    RENAMES,
    map_stored_wic_take_up,
    pending,
    simulation_and_branches,
    stored_draw,
)

YEARS = [2017, 2025]


# Stand-ins for the parts of a policyengine-core simulation the mapping uses.
class FakePopulation:
    def __init__(self, ids):
        self.ids = np.asarray(ids)


class FakeSimulation:
    def __init__(self, variables, ids, branches=None):
        self.tax_benefit_system = type("System", (), {"variables": variables})()
        self.populations = {"person": FakePopulation(ids)}
        self.branches = dict(branches or {})
        self.inputs = {}
        self.input_variables = ["person_id"]

    def set_input(self, name, period, values):
        self.inputs[(name, period)] = np.asarray(values).copy()


class FakeDataset:
    def __init__(self, person):
        self.person = person


ENGINE = {LIVE: object(), "wic": object()}


def person_table(draw, ids=None):
    ids = np.arange(len(draw)) + 1 if ids is None else ids
    return pd.DataFrame({"person_id": ids, LEGACY: draw})


def test_pending_needs_the_new_name_without_the_old():
    assert pending({LIVE: 1})
    assert not pending({LIVE: 1, LEGACY: 1})
    assert not pending({LEGACY: 1})
    assert not pending({})


@pytest.mark.parametrize(
    "column, expected",
    [
        ([True, False, True], [True, False, True]),
        ([1, 0, 1], [True, False, True]),
        ([1.0, 0.0, 0.0], [True, False, False]),
        (pd.Series([True, False, 1], dtype=object), [True, False, True]),
    ],
)
def test_stored_draw_reads_booleans_and_zero_one(column, expected):
    table = pd.DataFrame({"person_id": [1, 2, 3], LEGACY: column})
    np.testing.assert_array_equal(stored_draw(table), expected)


@pytest.mark.parametrize(
    "column",
    [
        [True, None, False],
        [1, 2, 0],
        pd.Series(["True", "False", "True"], dtype=object),
        [0.5, 1.0, 0.0],
    ],
)
def test_stored_draw_refuses_missing_or_non_boolean_values(column):
    table = pd.DataFrame({"person_id": [1, 2, 3], LEGACY: column})
    with pytest.raises(ValueError):
        stored_draw(table)


def test_stored_draw_gives_none_without_the_old_name_or_with_the_new_one():
    assert stored_draw(pd.DataFrame({"person_id": [1, 2]})) is None
    both = pd.DataFrame({"person_id": [1, 2], LEGACY: [True, False], LIVE: [True, True]})
    assert stored_draw(both) is None


@given(
    draw=st.lists(st.booleans(), min_size=1, max_size=40),
    years=st.lists(st.integers(2010, 2030), min_size=1, max_size=3, unique=True),
)
def test_mapping_sets_exactly_the_draw_for_every_month(draw, years):
    sim = FakeSimulation(ENGINE, np.arange(len(draw)) + 1)
    applied = map_stored_wic_take_up(sim, FakeDataset(person_table(draw)), years)
    assert applied == RENAMES
    periods = {f"{year}-{month:02d}" for year in years for month in range(1, 13)}
    assert set(sim.inputs) == {(LIVE, period) for period in periods}
    for values in sim.inputs.values():
        np.testing.assert_array_equal(values, np.asarray(draw, dtype=bool))
    assert LIVE in sim.input_variables


def test_mapping_reaches_every_branch():
    ids = [10, 11, 12]
    grandchild = FakeSimulation(ENGINE, ids)
    child = FakeSimulation(ENGINE, ids, branches={"g": grandchild})
    sim = FakeSimulation(ENGINE, ids, branches={"c": child, "again": child})
    map_stored_wic_take_up(sim, FakeDataset(person_table([True, False, True], ids)), [2025])
    assert len(list(simulation_and_branches(sim))) == 3
    for current in (sim, child, grandchild):
        np.testing.assert_array_equal(current.inputs[(LIVE, "2025-07")], [True, False, True])


def test_mapping_does_nothing_when_the_engine_reads_the_old_name():
    sim = FakeSimulation({LIVE: 1, LEGACY: 1}, [1, 2])
    assert map_stored_wic_take_up(sim, FakeDataset(person_table([True, False])), [2025]) == {}
    assert sim.inputs == {}


def test_mapping_does_nothing_when_the_data_store_the_new_name():
    table = person_table([True, False]).assign(**{LIVE: [False, False]})
    sim = FakeSimulation(ENGINE, [1, 2])
    assert map_stored_wic_take_up(sim, FakeDataset(table), [2025]) == {}
    assert sim.inputs == {}


def test_mapping_refuses_a_table_out_of_the_simulations_order():
    sim = FakeSimulation(ENGINE, [1, 2, 3])
    table = person_table([True, False, False], ids=[2, 1, 3])
    with pytest.raises(ValueError, match="order"):
        map_stored_wic_take_up(sim, FakeDataset(table), [2025])
    assert sim.inputs == {}


def test_mapping_refuses_a_branch_out_of_order_before_setting_anything():
    branch = FakeSimulation(ENGINE, [3, 2, 1])
    sim = FakeSimulation(ENGINE, [1, 2, 3], branches={"b": branch})
    with pytest.raises(ValueError, match="order"):
        map_stored_wic_take_up(sim, FakeDataset(person_table([True, False, True])), [2025])
    assert sim.inputs == {} and branch.inputs == {}


def test_mapping_needs_person_ids_and_years():
    sim = FakeSimulation(ENGINE, [1, 2])
    with pytest.raises(ValueError, match="person_id"):
        map_stored_wic_take_up(sim, FakeDataset(pd.DataFrame({LEGACY: [True, False]})), [2025])
    with pytest.raises(ValueError, match="no years"):
        map_stored_wic_take_up(sim, FakeDataset(person_table([True, False])), [])


# The real model, on about 300 Microcosm households.


def configured(dataset, system, year):
    if year < int(dataset.time_period):
        dataset, _ = deflate(dataset, system, year)
    return dataset


def full_take_up(dataset, year):
    """The same simulation without the mapping: everyone eligible takes WIC up."""
    from policyengine_us import Microsimulation

    return Microsimulation(dataset=dataset, dataset_end_year=max(year, int(dataset.time_period)))


@pytest.mark.parametrize("year", YEARS)
def test_simulations_take_wic_up_as_drawn(small_dataset, system, year):
    data = configured(small_dataset, system, year)
    sim = build_simulation(data, year)
    assert sim.stored_input_renames == RENAMES
    draw = data.person[LEGACY].to_numpy(dtype=bool)
    assert draw.any() and not draw.all()
    for month in range(1, 13):
        np.testing.assert_array_equal(sim.calculate(LIVE, f"{year}-{month:02d}").values, draw)


@pytest.mark.parametrize("year", YEARS)
def test_wic_is_full_take_up_wic_times_the_draw(small_dataset, system, year):
    data = configured(small_dataset, system, year)
    mapped = build_simulation(data, year)
    full = full_take_up(data, year)
    draw = data.person[LEGACY].to_numpy(dtype=bool)
    for month in range(1, 13):
        period = f"{year}-{month:02d}"
        np.testing.assert_allclose(
            mapped.calculate("wic", period).values,
            np.where(draw, full.calculate("wic", period).values, 0.0),
        )
    # Some eligible people in the sample don't take WIC up.
    assert mapped.calculate("wic", year).sum() < full.calculate("wic", year).sum()


def test_the_cliff_tests_branches_start_from_the_draw(small_dataset):
    year = 2025
    sim = build_simulation(small_dataset, year)
    sim.calculate("is_on_cliff", year)
    branches = list(simulation_and_branches(sim))[1:]
    assert branches, "the cliff test made no branches"
    draw = small_dataset.person[LEGACY].to_numpy(dtype=bool)
    for branch in branches:
        for month in (1, 12):
            np.testing.assert_array_equal(branch.calculate(LIVE, f"{year}-{month:02d}").values, draw)


@pytest.mark.parametrize("year", YEARS)
def test_raised_earnings_copies_keep_the_draw(small_dataset, system, year):
    """The copy the cliff test makes to raise an adult's earnings keeps the mapped draw.

    marginal_earnings_change deletes each copy once it has measured it, so this
    builds one with PolicyEngine-US's own create_perturbed_branch, which keeps a
    simulation's inputs and deletes every other array.
    """
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
    )

    data = configured(small_dataset, system, year)
    sim = build_simulation(data, year)
    draw = data.person[LEGACY].to_numpy(dtype=bool)
    base_wic = sim.calculate("wic", year).values
    branch = create_perturbed_branch(
        sim, year, "wic_check", {"employment_income": np.full(len(draw), 1_000.0)}
    )
    try:
        for month in range(1, 13):
            np.testing.assert_array_equal(
                branch.calculate(LIVE, f"{year}-{month:02d}").values, draw
            )
        raised_wic = branch.calculate("wic", year).values
        # Nobody the draw leaves out gets WIC in either simulation.
        assert (base_wic[~draw] == 0).all() and (raised_wic[~draw] == 0).all()
        assert base_wic[draw].sum() > 0
    finally:
        del sim.branches["wic_check"]


@pytest.mark.parametrize("year", YEARS)
def test_medicaid_sums_ignore_wic_take_up(small_dataset, system, year):
    from cliffs2017.medicaid import simulation_sums

    data = configured(small_dataset, system, year)
    options = dict(health=True, aca_before_2018=year < 2018)
    mapped = simulation_sums(build_simulation(data, year, **options), year)
    from policyengine_us import Microsimulation

    from cliffs2017.simulation import reforms

    full = simulation_sums(
        Microsimulation(
            dataset=data,
            reform=reforms(True, year < 2018),
            dataset_end_year=max(year, int(data.time_period)),
        ),
        year,
    )
    pd.testing.assert_frame_equal(mapped, full)
