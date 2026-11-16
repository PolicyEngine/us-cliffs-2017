"""A bounded job-entry feasibility pilot for the frozen 2017 experiment.

This command deliberately refuses a national run. It selects a small household
sample in states with independently verified historical wages. Its output is a
validation record, never a population estimate. All weighted aggregations use
MicroSeries and entity mapping; no weight columns are read by this module.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from pathlib import Path

from microdf import MicroSeries

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.expanded_historical import (
    build_historical_simulation,
    historical_provenance,
    load_historical_dataset,
)

THRESHOLDS = (0.6, 0.5, 0.2, 0.0)
EARNINGS = (
    "employment_income",
    "self_employment_income",
    "sstb_self_employment_income",
)
PILOT_FIPS = {"CO": 8, "NC": 37, "WA": 53}
# DOL's 2017 basic-rate column, verified against state history for Washington.
# This is an annualized wage scenario at the published historical rate, not a
# month-by-month reconstruction, local wage, tipped wage, or employer-size model.
PILOT_WAGES = {"CO": 9.30, "NC": 7.25, "WA": 11.00}
WAGE_SOURCES = {
    "DOL": "https://www.dol.gov/agencies/whd/state/minimum-wage/history",
    "DOL_beta": (
        "https://beta.dol.gov/policy-regulations/pay-benefits/wages-hours/"
        "state-laws/minimum-wage/history"
    ),
    "WA": (
        "https://www.lni.wa.gov/workers-rights/wages/minimum-wage/"
        "history-of-washington-states-minimum-wage"
    ),
    "CO": "https://leg.colorado.gov/sites/default/files/documents/2019A/bills/fn/2019a_hb1210_00.pdf",
    "NC": "https://www.labor.nc.gov/communications/labor-ledger/2021-november-december-edition/open",
}


def eligible_nonworkers(age, wages, self_employment, sstb, student, disabled):
    """An explicit observable restriction, not a prediction of work availability.

    The main pilot excludes full-time students and reported disability. The
    dataset has no direct observation that a person is available for a specific
    full-time job; age 18-64 also excludes conventionally retired adults. The
    job test holds other household characteristics fixed.
    """
    return (
        (age >= 18)
        & (age <= 64)
        & (wages == 0)
        & (self_employment == 0)
        & (sstb == 0)
        & ~student
        & ~disabled
    )


def register_analysis_variables(system):
    """Analysis-only inputs and mappings, with no new policy rules."""
    from policyengine_us.model_api import YEAR, Household, Person, Variable, add

    class expanded_job_eligible(Variable):
        label = "Observable working-age job-entry test population"
        value_type = bool
        entity = Person
        definition_period = YEAR

        def formula(person, period, parameters):
            return eligible_nonworkers(
                person("age", period),
                person("employment_income", period),
                person("self_employment_income", period),
                person("sstb_self_employment_income", period),
                person("is_full_time_student", period),
                person("is_disabled", period),
            )

    class expanded_job_rank(Variable):
        label = "Rank among job-entry candidates in a household"
        value_type = int
        entity = Person
        definition_period = YEAR

        def formula(person, period, parameters):
            return (
                person.get_rank(
                    person.household,
                    person("person_id", period),
                    condition=person("expanded_job_eligible", period),
                )
                + 1
            )

    class expanded_job_resources(Variable):
        label = "Historical household resources with the ACA credit counted once"
        value_type = float
        entity = Household
        definition_period = YEAR

        def formula(household, period, parameters):
            # Health-inclusive net income already adds assigned ACA PTC.
            # Cancel its marketplace-net-premium subtraction, as the original
            # d_net_single_ptc comparison does, to count the credit once.
            return household("household_net_income", period) + add(
                household, period, ["marketplace_net_premium"]
            )

    class expanded_job_flag(Variable):
        label = "Person meets an analysis scenario condition"
        value_type = bool
        entity = Person
        definition_period = YEAR

    class expanded_job_household_flag(Variable):
        label = "At least one household member meets an analysis condition"
        value_type = bool
        entity = Household
        definition_period = YEAR

        def formula(household, period, parameters):
            return household.any(household.members("expanded_job_flag", period))

    for variable in (
        expanded_job_eligible,
        expanded_job_rank,
        expanded_job_resources,
        expanded_job_flag,
        expanded_job_household_flag,
    ):
        if variable.__name__ not in system.variables:
            system.add_variable(variable)


def stratified_pilot(dataset, states, per_state=5, seed=0):
    """Select up to five candidate-containing households in each pilot state.

    Selection uses stored inputs only. It preserves all household members and
    their units and keeps the existing household weights unchanged. These
    deliberately selected strata do not support population inference.
    """
    if not 1 <= per_state <= 10:
        raise ValueError("pilot requires 1..10 households per state")
    if not set(states) <= set(PILOT_WAGES):
        raise ValueError("historical wages verified only for pilot states CO, NC, WA")
    from cliffs2017.deflate import _keep_households

    p = dataset.person
    candidate = eligible_nonworkers(
        p.age,
        p.employment_income_before_lsr,
        p.self_employment_income_before_lsr,
        p.sstb_self_employment_income_before_lsr,
        p.is_full_time_college_student,
        p.is_disabled,
    )
    candidate_households = set(p.loc[candidate, "person_household_id"])
    households = dataset.household
    chosen = []
    counts = {}
    for state in states:
        possible = households.loc[
            (households.state_fips == PILOT_FIPS[state])
            & households.household_id.isin(candidate_households)
        ]
        if len(possible) == 0:
            raise ValueError(f"no candidate-containing household in {state}")
        sample = possible.sample(n=min(per_state, len(possible)), random_state=seed)
        chosen.extend(sample.household_id.tolist())
        counts[state] = len(sample)
    out = _keep_households(dataset, households.household_id.isin(chosen), 1.0)
    return out, counts


def resources(sim, year=2017, map_to="person"):
    result = sim.calc("expanded_job_resources", period=year, map_to=map_to)
    if not isinstance(result, MicroSeries):
        raise TypeError("resource mapping must preserve MicroSeries weights")
    return result


def hourly_wages(state, rates):
    """Map state rates with MicroSeries arithmetic, which retains its metadata.

    Comparisons and arithmetic preserve the calibrated household-weight
    context in the frozen historical environment.
    """
    hourly = (state == "__no_state__") * 0.0
    covered = state == "__no_state__"
    for code, wage in rates.items():
        match = state == code
        covered = covered | match
        hourly = hourly + match * wage
    if not covered.all():
        raise ValueError("missing verified 2017 state minimum wage")
    if not isinstance(hourly, MicroSeries):
        raise TypeError("wage mapping must retain MicroSeries metadata")
    return hourly


def job_increments(sim, selected, hourly_wage, year=2017):
    """Full-time wage work, with hours and unemployment inputs made consistent."""
    gross = selected * hourly_wage * 40 * 52
    increments = {"employment_income": gross}
    targets = {
        "hours_worked_last_week": 40,
        "weekly_hours_worked_before_lsr": 40,
        "weeks_worked": 52,
        "weeks_unemployed": 0,
        "unemployment_compensation": 0,
        "hourly_wage": hourly_wage,
    }
    for variable, target in targets.items():
        base = sim.calc(variable, period=year)
        increments[variable] = selected * (target - base)
    return increments, gross


def make_job_branch(sim, selected, hourly_wage, rank, year=2017):
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
    )

    increments, gross = job_increments(sim, selected, hourly_wage, year)
    name = f"expanded_job_rank_{rank}"
    branch = create_perturbed_branch(sim, year, name, increments)
    for variable, target in (
        ("is_paid_hourly", True),
        ("is_self_employed", False),
        ("has_never_worked", False),
    ):
        base = sim.calc(variable, period=year)
        changed = base | selected if target else base & ~selected
        branch.set_input(variable, year, changed)
    return name, branch, gross


def map_flag(sim, flag, year=2017):
    """Count household unions through model entity mapping, never weight math."""
    sim.set_input("expanded_job_flag", year, flag)
    # set_input replaces its own input array, but this core version keeps a
    # previously calculated dependent array. Every new threshold/selection
    # must therefore recalculate the household projection.
    sim.delete_arrays("expanded_job_household_flag", year)
    household = sim.calc("expanded_job_household_flag", period=year)
    members = sim.calc("expanded_job_household_flag", period=year, map_to="person")
    return household, members


def fresh_job_simulation(dataset, sim, selected, hourly_wage, year=2017):
    """Independently change stored inputs and construct a fresh simulation.

    Lists/dicts here carry identifiers and new input wages, never weighted
    outcomes. No survey weights are read, stripped or aggregated.
    """
    changed = dataset.copy(deep=True)
    ids = sim.calc("person_id", period=year)
    wage_by_id = dict(zip(ids[selected].tolist(), hourly_wage[selected].tolist()))
    person = changed.person
    enters = person.person_id.isin(wage_by_id)
    new_wage = person.loc[enters, "person_id"].map(wage_by_id)
    person.loc[enters, "employment_income_before_lsr"] = new_wage * 40 * 52
    for variable, value in {
        "hours_worked_last_week": 40,
        "weekly_hours_worked_before_lsr": 40,
        "weeks_worked": 52,
        "weeks_unemployed": 0,
        "unemployment_compensation": 0,
        "is_paid_hourly": True,
        "is_self_employed": False,
        "has_never_worked": False,
    }.items():
        person.loc[enters, variable] = value
    person.loc[enters, "hourly_wage"] = new_wage
    fresh = build_historical_simulation(changed, year, health=True)
    register_analysis_variables(fresh.tax_benefit_system)
    return fresh


def run_pilot(dataset, year=2017, rates=None):
    if year != 2017:
        raise ValueError("this pilot verifies the 2017 historical experiment only")
    if len(dataset.household) > 30:
        raise ValueError("pilot refuses more than 30 households; no national run here")
    rates = rates or PILOT_WAGES
    sim = build_historical_simulation(dataset, year, health=True)
    register_analysis_variables(sim.tax_benefit_system)
    eligible = sim.calc("expanded_job_eligible", period=year)
    if not eligible.any():
        raise ValueError("pilot sample has no candidates under the model selection")
    rank = sim.calc("expanded_job_rank", period=year)
    state = sim.calc("state_code_str", period=year, map_to="person")
    hourly = hourly_wages(state, rates)
    base = resources(sim, year)
    flags = {cutoff: eligible & False for cutoff in THRESHOLDS}
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
    )

    zero = create_perturbed_branch(
        sim, year, "expanded_job_zero_change", {"employment_income": eligible * 0}
    )
    zero_difference = resources(zero, year) - base
    zero_max = zero_difference.abs().max()
    del sim.branches["expanded_job_zero_change"]
    del zero
    gc.collect()
    if zero_max > 0:
        raise RuntimeError(f"zero-change branch moved resources by {zero_max}")

    audit = []
    for k in range(1, int(rank[eligible].max()) + 1):
        selected = eligible & (rank == k)
        name, branch, gross = make_job_branch(sim, selected, hourly, k, year)
        changed = resources(branch, year)
        delta = changed - base
        for cutoff in THRESHOLDS:
            flags[cutoff] = flags[cutoff] | (selected & (delta < cutoff * gross))
        # The entire household changes for each selected adult. No other
        # household may change, since every branch changes one adult per unit.
        _, touched = map_flag(sim, selected, year)
        outside_max = delta[~touched].abs().max() if (~touched).any() else 0.0
        if outside_max > 0:
            raise RuntimeError(
                f"job entry changed an untouched household: {outside_max}"
            )
        selected_hours = branch.calc("weekly_hours_worked", period=year)[selected]
        selected_weeks = branch.calc("weeks_worked", period=year)[selected]
        earnings_alt = sum(branch.calc(v, period=year) for v in EARNINGS)
        earnings_error = (earnings_alt[selected] - gross[selected]).abs().max()
        if earnings_error > 0.02:
            raise RuntimeError(
                f"job earnings don't equal wage x 2080: {earnings_error}"
            )
        if not (selected_hours == 40).all() or not (selected_weeks == 52).all():
            raise RuntimeError("job branch failed full-time hours/weeks identity")
        draw_changed = (
            branch.calc("takes_up_wic_if_eligible", period=f"{year}-01")
            != sim.calc("takes_up_wic_if_eligible", period=f"{year}-01")
        ).any()
        if draw_changed:
            raise RuntimeError("job counterfactual changed the stored WIC take-up draw")
        fresh_error = None
        if k == 1:
            fresh = fresh_job_simulation(dataset, sim, selected, hourly, year)
            fresh_error = (resources(fresh, year) - changed).abs().max()
            if fresh_error > 1:
                raise RuntimeError(
                    f"branch disagrees with fresh input simulation: {fresh_error}"
                )
            del fresh
            gc.collect()
        audit.append(
            {
                "rank": k,
                "sample_adults_tested": len(selected[selected]),
                "max_earnings_identity_error": earnings_error,
                "max_untouched_household_resource_change": outside_max,
                "wic_draw_changed": bool(draw_changed),
                "fresh_simulation_max_difference": fresh_error,
                "sample_min_resource_change": delta[selected].min(),
                "sample_max_resource_change": delta[selected].max(),
            }
        )
        del sim.branches[name]
        del branch
        gc.collect()

    counts = {}
    if sum(row["sample_adults_tested"] for row in audit) != len(eligible[eligible]):
        raise RuntimeError("job-entry ranks failed to test every candidate once")
    for lo, hi in zip(reversed(THRESHOLDS), reversed(THRESHOLDS[:-1])):
        if (flags[lo] & ~flags[hi]).any():
            raise RuntimeError("retention thresholds are not nested")
    for cutoff, flag in flags.items():
        household, members = map_flag(sim, flag, year)
        if len(household[household]) > len(flag[flag]):
            raise RuntimeError("household union exceeds its flagged adults")
        if (flag & ~members).any():
            raise RuntimeError(
                "a flagged adult is absent from its household projection"
            )
        counts[f"keeps_less_than_{cutoff:g}"] = {
            "sample_adults": len(flag[flag]),
            "sample_households": len(household[household]),
            "sample_members": len(members[members]),
            # These sums check the weighted aggregation route only. They are
            # intentionally omitted: selected-stratum weights are not a
            # nationally representative estimate.
            "microseries_mapping_verified": all(
                isinstance(x, MicroSeries) for x in (flag, household, members)
            ),
        }
    return {
        "status": "pilot_only_not_a_population_estimate",
        "year": year,
        "sample_households": len(dataset.household),
        "sample_people": len(dataset.person),
        "sample_candidates": len(eligible[eligible]),
        "zero_change_max_resource_difference": zero_max,
        "selection": "age 18-64; all three earnings zero; no full-time student or reported disability",
        "candidate_limitations": "No direct full-time-job availability flag; early retirement is not observed. Reported disability exclusion is an explicit sensitivity choice.",
        "job": "40 hours/week, 52 weeks; verified 2017 state basic wage; no new employer insurance",
        "other_changes": "set unemployment compensation and weeks unemployed to zero; preserve other incomes and childcare costs",
        "health": "same government-cost coverage valuation as historical experiment; ACA premium tax credit once",
        "hourly_wages": rates,
        "wage_sources": WAGE_SOURCES,
        "counterfactuals": audit,
        "retention_checks": counts,
        "provenance": historical_provenance(),
    }


def json_scalar(value):
    """Serialize NumPy validation scalars without stripping any MicroSeries."""
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", default="CO,NC,WA")
    parser.add_argument("--households-per-state", type=int, default=5)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    start = time.time()
    code_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    dataset = load_historical_dataset()
    sample, strata = stratified_pilot(
        dataset,
        args.states.split(","),
        args.households_per_state,
        args.seed,
    )
    del dataset
    gc.collect()
    result = run_pilot(sample)
    result.update(
        strata=strata,
        seconds=round(time.time() - start, 2),
        script_sha256=code_sha256,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, indent=2, default=json_scalar)
    args.out.write_text(serialized + "\n")
    print(serialized)


if __name__ == "__main__":
    main()
