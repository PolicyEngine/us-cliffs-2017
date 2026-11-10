"""Show, for one household, how the premium tax credit moves net income twice.

With health coverage counted (gov.simulation.include_health_benefits_in_net_income),
PolicyEngine-US adds the premium tax credit to household benefits
(assigned_aca_ptc, in gov.household.household_health_benefits) and subtracts
the marketplace premium net of the credit used (marketplace_net_premium, in
gov.household.household_health_costs). So a $1 cut in the credit of an enrollee
who pays a premium lowers household net income by $2.

The household: one adult aged 40 in Texas, who earns $30,000 in 2025 (about
199% of the poverty line) and then $31,000. Texas didn't expand Medicaid, so
the adult gets marketplace coverage. The script computes each household at
both earnings, with and without health coverage counted, and writes the
changes to results/ptc_household.json.

usage: python scripts/ptc_household.py [--year 2025] [--state TX] [--earnings 30000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cliffs2017.simulation import reforms  # noqa: E402

HOUSEHOLD = [
    "household_net_income",
    "household_market_income",
    "household_benefits",
    "household_health_benefits",
    "household_refundable_tax_credits",
    "household_tax_before_refundable_credits",
    "household_health_costs",
]
TAX_UNIT = [
    "aca_ptc",
    "used_aca_ptc",
    "assigned_aca_ptc",
    "selected_marketplace_plan_premium_proxy",
    "marketplace_net_premium",
    "aca_magi_fraction",
]
PERSON = ["employment_income", "is_medicaid_eligible", "marginal_tax_rate", "cliff_gap"]


def situation(year: int, state: str, earnings: float) -> dict:
    members = ["adult"]
    return {
        "people": {"adult": {"age": {year: 40}, "employment_income": {year: earnings}}},
        "tax_units": {"tax_unit": {"members": members}},
        "families": {"family": {"members": members}},
        "spm_units": {"spm_unit": {"members": members}},
        "marital_units": {"marital_unit": {"members": members}},
        "households": {"household": {"members": members, "state_name": {year: state}}},
    }


def compute(year: int, state: str, earnings: float, health: bool) -> dict:
    from policyengine_us import Simulation

    sim = Simulation(
        situation=situation(year, state, earnings),
        reform=reforms(health=health, aca_before_2018=False),
    )
    out = {}
    for name in HOUSEHOLD + TAX_UNIT + PERSON:
        values = sim.calculate(name, year)
        if values.dtype == bool:
            out[name] = bool(values[0])
        else:
            out[name] = round(float(values[0]), 4 if name == "marginal_tax_rate" else 2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--state", default="TX")
    parser.add_argument("--earnings", type=float, default=30_000)
    parser.add_argument("--out", default="results/ptc_household.json")
    args = parser.parse_args()

    from importlib.metadata import version

    raise_ = 1_000
    result = dict(
        policyengine_us=version("policyengine-us"),
        policyengine_core=version("policyengine-core"),
        year=args.year,
        state=args.state,
        household="one adult aged 40",
        earnings=args.earnings,
        raised_earnings=args.earnings + raise_,
    )
    for health in (False, True):
        base = compute(args.year, args.state, args.earnings, health)
        raised = compute(args.year, args.state, args.earnings + raise_, health)
        change = {
            k: round(raised[k] - base[k], 2)
            for k in HOUSEHOLD + TAX_UNIT
            if isinstance(base[k], float) and isinstance(raised[k], float)
        }
        key = "counting_health_coverage" if health else "without_health_coverage"
        result[key] = dict(base=base, raised=raised, change=change)
        if health:
            # Counting the credit once: leave out the change in the net premium,
            # as cliffs2017/decompose.py does (d_net_single_ptc).
            result[key]["change_in_net_income_counting_credit_once"] = round(
                change["household_net_income"] + change["marketplace_net_premium"], 2
            )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
