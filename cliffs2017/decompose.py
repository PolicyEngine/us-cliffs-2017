"""Break each measured adult's change in household net income into its parts.

PolicyEngine-US measures a person's cliff by raising that adult's earnings by
``simulation.marginal_tax_rate_delta`` ($1,000) in a branch simulation and
comparing household net income (``marginal_earnings_change``). This module
builds the same branches, with PolicyEngine-US's own ``create_perturbed_branch``
and ``earnings_increments``, and records the change in every component of
household net income:

- household_market_income;
- each source in gov.household.household_benefits (with the health sources in
  gov.household.household_health_benefits listed one by one when health
  benefits count as income);
- household_refundable_tax_credits;
- household_tax_before_refundable_credits (subtracted);
- each cost in gov.household.household_health_costs (subtracted, when health
  benefits count as income).

The parts add up to the change in household net income, which equals
``delta * (1 - marginal_tax_rate)`` for every measured adult.

It also reports the change with the marketplace premium removed from the
health costs. With health benefits counted, household net income adds the
premium tax credit (assigned_aca_ptc) and subtracts the marketplace premium
net of the credit used (marketplace_net_premium = premium - used_aca_ptc), so
a change in the credit of a premium-paying enrollee moves net income twice.
Leaving out the premium counts the credit once, as the model counts Medicaid
and CHIP: at government cost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TAX = "household_tax_before_refundable_credits"
CREDITS = "household_refundable_tax_credits"
MARKET = "household_market_income"
NET = "household_net_income"
HEALTH_BENEFITS = "household_health_benefits"
HEALTH_COSTS = "household_health_costs"
MARKETPLACE_PREMIUM = "marketplace_net_premium"


def components(simulation, period) -> list[tuple[str, int]]:
    """(variable, sign) pairs whose signed sum is household net income."""
    p = simulation.tax_benefit_system.parameters(period)
    health = bool(p.gov.simulation.include_health_benefits_in_net_income)
    parts = [(MARKET, 1), (CREDITS, 1), (TAX, -1)]
    for benefit in p.gov.household.household_benefits:
        if benefit == HEALTH_BENEFITS:
            if health:
                parts += [(b, 1) for b in p.gov.household.household_health_benefits]
            continue
        if benefit == "housing_assistance" and p.gov.hud.abolition:
            continue
        parts.append((benefit, 1))
    if health:
        parts += [(c, -1) for c in p.gov.household.household_health_costs]
    return parts


def household_values(simulation, variables, period) -> dict[str, np.ndarray]:
    from policyengine_us.model_api import add

    household = simulation.populations["household"]
    return {v: np.asarray(add(household, period, [v]), dtype=np.float64) for v in variables}


def decompose(simulation, period) -> pd.DataFrame:
    """One row per measured adult: rank, base values and the change in each part."""
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
        earnings_increments,
    )

    p = simulation.tax_benefit_system.parameters(period)
    delta = float(p.simulation.marginal_tax_rate_delta)
    adults = int(p.simulation.marginal_tax_rate_adults)
    parts = components(simulation, period)
    names = [name for name, _ in parts]
    person = simulation.populations["person"]
    household_index = np.asarray(simulation.populations["household"].members_entity_id)
    rank = np.asarray(simulation.calculate("adult_earnings_index", period))
    is_adult = np.asarray(simulation.calculate("is_adult", period)).astype(bool)
    base = household_values(simulation, names + [NET], period)
    rows = []
    for k in range(1, adults + 1):
        mask = is_adult & (rank == k)
        name = f"cliffs2017_decompose_adult_{k}"
        branch = create_perturbed_branch(
            simulation, period, name, earnings_increments(person, period, mask * delta)
        )
        alt = household_values(branch, names + [NET], period)
        del simulation.branches[name]
        people = np.flatnonzero(mask)
        households = household_index[people]
        frame = pd.DataFrame({"person_index": people, "rank": k})
        for variable, sign in parts:
            frame[f"d_{variable}"] = sign * (alt[variable] - base[variable])[households]
        frame["d_net"] = (alt[NET] - base[NET])[households]
        frame["d_parts"] = frame[[f"d_{v}" for v in names]].sum(axis=1)
        rows.append(frame)
    out = pd.concat(rows, ignore_index=True)
    premium = f"d_{MARKETPLACE_PREMIUM}"
    out["d_net_single_ptc"] = out["d_net"] - (out[premium] if premium in out else 0)
    out["delta"] = delta
    return out


def primary_driver(frame: pd.DataFrame) -> pd.Series:
    """The part whose change lowers net income most, for each adult on a cliff."""
    cols = [c for c in frame.columns if c.startswith("d_") and c not in (
        "d_net", "d_parts", "d_net_single_ptc", f"d_{MARKET}")]
    worst = frame[cols].idxmin(axis=1).str.removeprefix("d_")
    return worst.where(frame[cols].min(axis=1) < 0, "none")
