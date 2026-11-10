"""Invariants of the cliff breakdown (cliffs2017.decompose).

For every measured adult, in 2017 and 2025, with and without health benefits
counted:
1. the signed changes in the parts add up to the change in household net
   income (accounting identity);
2. that change equals delta * (1 - marginal_tax_rate) from PolicyEngine-US's
   own measurement (differential test against the model);
3. it also equals the change in a fresh simulation of the same households
   with the adult's earnings raised (differential test of the branch
   machinery against re-simulation from scratch);
4. without health benefits, no health part enters, so counting the premium
   tax credit once changes nothing.
"""

import numpy as np
import pytest

from cliffs2017.decompose import NET, components, decompose, household_values
from cliffs2017.deflate import deflate
from cliffs2017.simulation import build_simulation

CONFIGURATIONS = [(2017, False), (2017, True), (2025, False), (2025, True)]


def configured(dataset, system, year, health):
    data = dataset
    if year < int(dataset.time_period):
        data, _ = deflate(dataset, system, year)
    return data, dict(health=health, aca_before_2018=year < 2018)


@pytest.mark.parametrize("year, health", CONFIGURATIONS)
def test_parts_add_up_and_match_model(system, small_dataset, year, health):
    data, options = configured(small_dataset, system, year, health)
    sim = build_simulation(data, year, **options)
    mtr = np.asarray(sim.calculate("marginal_tax_rate", year))
    frame = decompose(sim, year)
    assert len(frame) > 100
    np.testing.assert_allclose(frame["d_parts"], frame["d_net"], atol=1.0)
    expected = frame["delta"] * (1 - mtr[frame["person_index"]])
    np.testing.assert_allclose(frame["d_net"], expected, atol=1.0)
    names = [name for name, _ in components(sim, year)]
    if health:
        assert "assigned_aca_ptc" in names and "marketplace_net_premium" in names
    else:
        assert "assigned_aca_ptc" not in names
        np.testing.assert_array_equal(frame["d_net_single_ptc"], frame["d_net"])


@pytest.mark.parametrize("year, health", CONFIGURATIONS)
def test_branch_matches_fresh_simulation(system, small_dataset, year, health):
    from policyengine_us.variables.gov.simulation.behavioral_response_measurements import (
        PRE_RESPONSE_INPUTS,
    )
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        earnings_increments,
        user_set_variables,
    )

    data, options = configured(small_dataset, system, year, health)
    base = build_simulation(data, year, **options)
    frame = decompose(base, year)
    base_net = household_values(base, [NET], year)[NET]
    person = base.populations["person"]
    household_index = np.asarray(base.populations["household"].members_entity_id)
    rank = np.asarray(base.calculate("adult_earnings_index", year))
    is_adult = np.asarray(base.calculate("is_adult", year)).astype(bool)
    delta = float(base.tax_benefit_system.parameters(year).simulation.marginal_tax_rate_delta)
    inputs = user_set_variables(base, year)
    for k in sorted(frame["rank"].unique()):
        mask = is_adult & (rank == k)
        raised = {}
        for variable, increment in earnings_increments(person, year, mask * delta).items():
            name = variable if variable in inputs else PRE_RESPONSE_INPUTS.get(variable, variable)
            raised[name] = np.asarray(base.calculate(name, year), dtype=np.float64) + increment
        fresh = build_simulation(data, year, **options)
        for name, value in raised.items():
            fresh.set_input(name, year, value)
        fresh_net = household_values(fresh, [NET], year)[NET]
        rows = frame[frame["rank"] == k]
        expected = (fresh_net - base_net)[household_index[rows["person_index"]]]
        np.testing.assert_allclose(rows["d_net"], expected, atol=1.0)
