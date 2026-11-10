"""Invariants of leaving CSFP out of household benefits (cliffs2017.benefits).

1. The model's 2017 list of household benefits has no CSFP, so the reform
   changes nothing in a 2017 run.
2. At every date, the reformed list equals the model's list less CSFP, in the
   model's order, and the baseline system keeps its own list.
3. A CSFP recipient's household benefits and net income fall by exactly the
   package's value, and the package itself still computes.
4. Every person's Medicaid value stays the same (differential test on a
   Microcosm subsample), so the full-sample Medicaid totals still apply.
"""

import numpy as np
import pytest

from cliffs2017.benefits import CSFP, LeaveOutCSFP, without_csfp

DATES = ["2017-01-01", "2021-12-31", "2022-01-01", "2023-06-01", "2024-01-01", "2025-07-01", "2026-01-01"]


def benefits(system, date):
    return list(system.parameters(date).gov.household.household_benefits)


@pytest.fixture(scope="module")
def reformed(system):
    return LeaveOutCSFP(system)


def test_2017_list_has_no_csfp(system):
    assert CSFP not in benefits(system, "2017-01-01")
    assert CSFP in benefits(system, "2025-01-01")


@pytest.mark.parametrize("date", DATES)
def test_reform_drops_only_csfp(system, reformed, date):
    assert benefits(reformed, date) == without_csfp(benefits(system, date))
    assert CSFP not in benefits(reformed, date)


def test_baseline_keeps_its_list(system, reformed):
    assert CSFP in benefits(system, "2025-01-01")


def senior(year=2025):
    """A 65-year-old in North Carolina, where CSFP has no county limit, at about 64% of the poverty line."""
    return {
        "people": {"senior": {"age": {year: 65}, "employment_income": {year: 10_000}}},
        "tax_units": {"tu": {"members": ["senior"]}},
        "spm_units": {"spm": {"members": ["senior"]}},
        "households": {"h": {"members": ["senior"], "state_code": {year: "NC"}}},
    }


def test_recipient_loses_exactly_the_package(system):
    from policyengine_us import Simulation

    year = 2025
    base = Simulation(situation=senior(year))
    left_out = Simulation(situation=senior(year), reform=LeaveOutCSFP)
    package = float(base.calculate(CSFP, year)[0])
    amount = float(system.parameters(f"{year}-01-01").gov.usda.csfp.amount)
    assert package == pytest.approx(amount) and package > 0
    assert float(left_out.calculate(CSFP, year)[0]) == pytest.approx(package)
    for variable in ("household_benefits", "household_net_income"):
        drop = float(base.calculate(variable, year)[0]) - float(left_out.calculate(variable, year)[0])
        assert drop == pytest.approx(package, abs=0.01), variable


def test_medicaid_value_unchanged(small_dataset):
    from cliffs2017.simulation import build_simulation

    year = 2025
    values = []
    for leave_out in (False, True):
        sim = build_simulation(small_dataset, year, health=True, leave_out_csfp=leave_out)
        values.append(np.asarray(sim.calculate("medicaid_cost", year).values, dtype=float))
    assert values[0].sum() > 0
    np.testing.assert_array_equal(values[0], values[1])
