"""A small model-backed fixture for the national job-entry scenario and resource measures.

It runs ``expanded_job_entry_national.run_rank`` on a few households of part 0 in
the frozen 2017 model and checks the result against oracles that don't come from
the job branch or the fresh-simulation route:

1. inputs: every work-related column the dataset's person table holds is either
   one the job sets, and it then holds the full-time job's value for each tested
   adult, or one reviewed as held fixed, and it is then unchanged. A new or
   overlooked work-status input fails the fixture by name, so an input omitted
   from both the branch and the fresh simulation can't pass unnoticed;
2. hand values: for every tested adult, earnings rise by the rate times 2,080
   and employee Social Security and Medicare tax by 7.65% of that (2017: 6.2%
   below the $127,200 wage base, 1.45%). For tested adults who file alone (a
   one-person tax unit, no dependents, not joint), take the standard deduction
   before and after, are not blind, have no preferentially taxed income and whose
   AGI rises by exactly the pay, the change in federal income tax before credits
   equals the 2017 single schedule (10% to $9,325 of taxable income, then 15%)
   applied to AGI less the $6,350 standard deduction and $4,050 exemption, after
   minus before; and the EITC is $0 before and after (no earnings before; a
   childless credit ends at $15,010, below every state's full-time pay);
3. resources: each row's measures equal the change in the model's top-level
   household variables: ``d_net`` the change in household net income,
   ``d_net_single_ptc`` that plus the change in marketplace net premiums, and
   ``d_net_without_health`` that less the change in health benefits plus the
   change in health costs.

The fixture loads the full part, so it runs in a Modal container
(``modal run scripts/modal_job_entry.py --model-fixture-only``). Its counts check
the code path; the selected households support no population inference.
"""

from __future__ import annotations

import re
import time

import numpy as np

YEAR = 2017
PART = 0
SAMPLE_SEED = 11
# 2017 single filer (Rev. Proc. 2016-55): standard deduction, personal exemption, brackets.
STANDARD_DEDUCTION = 6350
EXEMPTION = 4050
BRACKETS = ((9325, 0.10), (37950, 0.15), (91900, 0.25), (191650, 0.28), (416700, 0.33), (418400, 0.35),
            (float("inf"), 0.396))
AGI_CEILING = 100_000  # well below where the 2017 AMT could bind with the standard deduction
SOCIAL_SECURITY_RATE = 0.062
SOCIAL_SECURITY_WAGE_BASE = 127200
MEDICARE_RATE = 0.0145
CHILDLESS_EITC_ENDS = 15010
WORK_PATTERN = re.compile(r"(employ|hour|week|work|job|wage|labor|occupation|salar|earn|unemploy|retire|pension|"
                          r"lsr|business|farm|tip)")
# The inputs the job sets and the value each takes for a tested adult. "pay" is
# the rate times 2,080 and "rate" the state's hourly rate.
JOB_INPUTS = {
    "employment_income_before_lsr": "pay",
    "hourly_wage": "rate",
    "hours_worked_last_week": 40,
    "weekly_hours_worked_before_lsr": 40,
    "weeks_worked": 52,
    "weeks_unemployed": 0,
    "unemployment_compensation": 0,
    "is_paid_hourly": True,
    "is_self_employed": False,
    "has_never_worked": False,
}
# Work-related inputs the job holds fixed, with the reason.
SELF_EMPLOYMENT = "self-employment or business input; candidates have none and the job is wage work"
REVIEWED_UNCHANGED = {
    "business_is_sstb": SELF_EMPLOYMENT,
    "farm_income": SELF_EMPLOYMENT,
    "farm_operations_income": SELF_EMPLOYMENT,
    "farm_operations_income_would_be_qualified": SELF_EMPLOYMENT,
    "farm_rent_income": SELF_EMPLOYMENT,
    "farm_rent_income_would_be_qualified": SELF_EMPLOYMENT,
    "partnership_self_employment_net_earnings": SELF_EMPLOYMENT,
    "self_employed_pension_contributions_desired": SELF_EMPLOYMENT,
    "self_employment_income_before_lsr": SELF_EMPLOYMENT,
    "self_employment_income_last_year": SELF_EMPLOYMENT,
    "self_employment_income_would_be_qualified": SELF_EMPLOYMENT,
    "sstb_self_employment_income_before_lsr": SELF_EMPLOYMENT,
    "sstb_self_employment_income_would_be_qualified": SELF_EMPLOYMENT,
    "sstb_w2_wages_from_qualified_business": SELF_EMPLOYMENT,
    "w2_wages_from_qualified_business": SELF_EMPLOYMENT,
    "is_farmer_fisher": "occupation flag; the job is a general minimum-wage job with no assigned occupation",
    "detailed_occupation_recode": "occupation code; the job has no assigned occupation",
    "treasury_tipped_occupation_code": "tipped-occupation code; the job is non-tipped",
    "tip_income": "the job is a non-tipped job",
    "unreimbursed_business_employee_expenses": "the scenario adds no work expenses",
    "workers_compensation": "an existing benefit, held fixed with other household characteristics",
    "social_security_retirement": "an existing benefit, held fixed with other household characteristics",
    "tax_exempt_private_pension_income": "existing pension income, held fixed",
    "taxable_private_pension_income": "existing pension income, held fixed",
}
PAY_TOLERANCE = 0.02  # float32 earnings near $25,000
TAX_TOLERANCE = 0.05
MEASURE_TOLERANCE = 1.0


def federal_income_tax_before_credits(agi: float) -> float:
    """2017 single schedule on ordinary AGI, after the standard deduction and one exemption."""
    taxable = max(0.0, agi - STANDARD_DEDUCTION - EXEMPTION)
    tax, lower = 0.0, 0.0
    for upper, rate in BRACKETS:
        tax += rate * max(0.0, min(taxable, upper) - lower)
        lower = upper
    return tax


def employee_payroll_tax(pay: float) -> float:
    return SOCIAL_SECURITY_RATE * min(pay, SOCIAL_SECURITY_WAGE_BASE) + MEDICARE_RATE * pay


def unreviewed_inputs(columns) -> list[str]:
    """Work-related dataset columns that are neither set by the job nor reviewed as fixed."""
    return sorted(c for c in columns if WORK_PATTERN.search(c) and c not in JOB_INPUTS and c not in REVIEWED_UNCHANGED)


def fixture_sample(dataset, seed: int = SAMPLE_SEED, alone: int = 40, others: int = 30, non_candidates: int = 10):
    """Households chosen from stored inputs: households of candidates alone in their tax
    unit, other candidate households, and households with no candidate."""
    from cliffs2017.deflate import _keep_households
    from scripts.expanded_job_entry import eligible_nonworkers

    p = dataset.person
    candidate = eligible_nonworkers(
        p.age, p.employment_income_before_lsr, p.self_employment_income_before_lsr,
        p.sstb_self_employment_income_before_lsr, p.is_full_time_college_student, p.is_disabled,
    )
    hh = dataset.household
    unit_size = p.person_tax_unit_id.map(p.groupby("person_tax_unit_id").size())
    has = hh.household_id.isin(set(p.loc[candidate, "person_household_id"]))
    files_alone = hh.household_id.isin(set(p.loc[candidate & unit_size.eq(1), "person_household_id"]))
    pools = [(files_alone, alone), (has & ~files_alone, others), (~has, non_candidates)]
    chosen = []
    for mask, n in pools:
        pool = hh[mask]
        chosen += pool.sample(n=min(n, len(pool)), random_state=seed).household_id.tolist()
    sample = _keep_households(dataset, hh.household_id.isin(chosen).to_numpy(), 1.0)
    return sample, {"households": len(sample.household), "people": len(sample.person)}


def _check(name: str, value, ok: bool, results: dict, **extra) -> None:
    results[name] = {"value": value, "pass": bool(ok), **extra}


def run(rank: int = 1, scope: str = "resolved") -> dict:
    import scripts.expanded_job_entry_national as national
    from cliffs2017.decompose import HEALTH_BENEFITS, HEALTH_COSTS, MARKETPLACE_PREMIUM, NET, household_values
    from scripts.expanded_job_entry import make_job_branch
    from scripts.job_entry_wages import HOURS_PER_YEAR, national_wage_table

    started = time.time()
    table = national_wage_table()
    rates = table["rates"]
    dataset, sample = fixture_sample(national.load_part(PART))
    sim = national.build(dataset)
    rows, record = national.run_rank(sim, dataset, rank, rates, scope, fresh=True)
    checks: dict = {}
    _check("run_rank_identities", sorted(record["identities"]),
           all(c["pass"] for c in record["identities"].values()), checks)

    # 1. Inputs.
    columns = list(dataset.person.columns)
    unreviewed = unreviewed_inputs(columns)
    _check("every_work_input_reviewed", unreviewed, not unreviewed, checks)
    c = national.candidates(sim, rates, scope, YEAR)
    selected = c["eligible"] & c["in_scope"] & (c["rank"] == rank)
    sel = np.asarray(selected, dtype=bool)
    name, branch, _ = make_job_branch(sim, selected, c["hourly"], rank, YEAR)
    state = np.asarray(c["state"]).astype(str)
    rate = np.array([rates[s] for s in state[sel]])
    pay = rate * HOURS_PER_YEAR
    wrong = {}
    for variable in columns:
        if not WORK_PATTERN.search(variable) or variable not in sim.tax_benefit_system.variables:
            continue
        after = np.asarray(branch.calc(variable, period=YEAR))[sel]
        before = np.asarray(sim.calc(variable, period=YEAR))[sel]
        if variable in JOB_INPUTS:
            target = JOB_INPUTS[variable]
            want = pay if target == "pay" else rate if target == "rate" else np.full(sel.sum(), target)
            if after.dtype == bool or isinstance(target, bool):
                bad = int((after != want).sum())
            else:
                bad = int((np.abs(after.astype(float) - want.astype(float)) > PAY_TOLERANCE).sum())
        else:
            bad = int((after != before).sum())
        if bad:
            wrong[variable] = bad
    _check("job_inputs_at_target_and_reviewed_inputs_unchanged", wrong, not wrong, checks,
           job_inputs=sorted(JOB_INPUTS), reviewed_unchanged=len(REVIEWED_UNCHANGED))

    # 2. Hand values.
    def person(sim_, variable):
        return np.asarray(sim_.calc(variable, period=YEAR), dtype=np.float64)

    def tax_unit_to_person(sim_, variable):
        return np.asarray(sim_.calc(variable, period=YEAR, map_to="person"), dtype=np.float64)

    d_earn = person(branch, "employment_income") - person(sim, "employment_income")
    _check("earnings_rise_by_pay", float(np.abs(d_earn[sel] - pay).max()),
           float(np.abs(d_earn[sel] - pay).max()) <= PAY_TOLERANCE, checks)
    payroll = ("employee_social_security_tax", "employee_medicare_tax")
    d_payroll = sum(person(branch, v) - person(sim, v) for v in payroll)
    hand_payroll = np.array([employee_payroll_tax(x) for x in pay])
    _check("payroll_tax_7_65_percent_of_pay", float(np.abs(d_payroll[sel] - hand_payroll).max()),
           float(np.abs(d_payroll[sel] - hand_payroll).max()) <= TAX_TOLERANCE, checks)
    # Single filers alone in their tax unit, with no dependents, the standard deduction
    # before and after, not blind, no preferentially taxed income, and AGI rising by
    # exactly the pay (so no unemployment compensation or Social Security interplay).
    unit_size = tax_unit_to_person(sim, "tax_unit_size")
    joint = tax_unit_to_person(sim, "tax_unit_is_joint").astype(bool)
    dependents = tax_unit_to_person(sim, "tax_unit_dependents")
    itemizes = tax_unit_to_person(sim, "tax_unit_itemizes").astype(bool) \
        | tax_unit_to_person(branch, "tax_unit_itemizes").astype(bool)
    blind = person(sim, "is_blind").astype(bool)
    preferential = sum(np.abs(person(sim, v)) for v in ("long_term_capital_gains", "qualified_dividend_income"))
    agi_base = tax_unit_to_person(sim, "adjusted_gross_income")
    d_agi = tax_unit_to_person(branch, "adjusted_gross_income") - agi_base
    all_pay = np.asarray(c["hourly"], dtype=np.float64) * HOURS_PER_YEAR
    steps = {"tested": sel}
    steps["alone_in_tax_unit"] = steps["tested"] & (unit_size == 1) & ~joint & (dependents == 0)
    steps["standard_deduction_not_blind"] = steps["alone_in_tax_unit"] & ~itemizes & ~blind
    steps["no_preferential_income"] = steps["standard_deduction_not_blind"] & (preferential == 0)
    steps["agi_rises_by_pay"] = steps["no_preferential_income"] & (np.abs(d_agi - all_pay) <= PAY_TOLERANCE) \
        & (agi_base + all_pay <= AGI_CEILING)
    simple = steps["agi_rises_by_pay"]
    simple_pay = all_pay[simple]
    if simple_pay.size and simple_pay.min() <= CHILDLESS_EITC_ENDS:
        raise ValueError("the EITC oracle assumes pay above the childless phase-out end")
    deduction = STANDARD_DEDUCTION + EXEMPTION
    hand_tax = np.array([federal_income_tax_before_credits(a + g) - federal_income_tax_before_credits(a)
                         for a, g in zip(agi_base[simple], simple_pay)])
    d_tax = tax_unit_to_person(branch, "income_tax_before_credits") - tax_unit_to_person(sim, "income_tax_before_credits")
    eitc = np.abs(tax_unit_to_person(branch, "eitc")[simple]) + np.abs(tax_unit_to_person(sim, "eitc")[simple])
    _check("single_filers_checked", int(simple.sum()), simple.sum() >= 3, checks,
           filter_counts={k: int(v.sum()) for k, v in steps.items()},
           states=sorted(set(state[simple].tolist())),
           agi_before_job=[round(float(a), 2) for a in agi_base[simple]])
    tax_error = float(np.abs(d_tax[simple] - hand_tax).max()) if simple.any() else None
    _check("single_filer_federal_tax_before_credits_by_hand", tax_error,
           tax_error is not None and tax_error <= TAX_TOLERANCE, checks,
           hand=[round(float(x), 2) for x in hand_tax], pay=[round(float(x), 2) for x in simple_pay],
           rule=f"2017 single schedule on AGI less ${deduction:,}, after minus before")
    _check("single_filer_eitc_zero", float(eitc.max()) if eitc.size else None, eitc.size > 0 and eitc.max() == 0,
           checks)

    # 3. Resources from top-level household variables, row by row.
    tracked = [NET, HEALTH_BENEFITS, HEALTH_COSTS, MARKETPLACE_PREMIUM]
    base = household_values(sim, tracked, YEAR)
    alt = household_values(branch, tracked, YEAR)
    d = {v: alt[v] - base[v] for v in tracked}
    household_index = np.asarray(sim.populations["household"].members_entity_id)
    position = household_index[rows["person_index"].to_numpy()]
    direct = {
        "d_net": d[NET][position],
        "d_net_single_ptc": (d[NET] + d[MARKETPLACE_PREMIUM])[position],
        "d_net_without_health": (d[NET] - d[HEALTH_BENEFITS] + d[HEALTH_COSTS])[position],
    }
    for measure, tolerance in (("d_net", 1e-6), ("d_net_single_ptc", MEASURE_TOLERANCE),
                               ("d_net_without_health", MEASURE_TOLERANCE)):
        error = float(np.abs(rows[measure].to_numpy() - direct[measure]).max())
        _check(f"{measure}_equals_top_level_change", error, error <= tolerance, checks, tolerance=tolerance)
    health_moves = int((np.abs(d[HEALTH_BENEFITS][position] - d[HEALTH_COSTS][position]) > 0).sum())
    del sim.branches[name], branch
    return {
        "pass": all(v["pass"] for v in checks.values()),
        "checks": checks,
        "sample": sample,
        "part": PART,
        "rank": rank,
        "scope": scope,
        "sample_seed": SAMPLE_SEED,
        "tested_adults": int(sel.sum()),
        "tested_by_state": record["counts"]["sample_candidates_tested_by_state"],
        "rows_with_a_health_change": health_moves,
        "rows_keeping_less_than_half_with_health": int((rows["d_net_single_ptc"] < 0.5 * rows["gross_pay"]).sum()),
        "wages_json_sha256": table["wages_json_sha256"],
        "seconds": round(time.time() - started, 1),
        "peak_memory_gib": national.peak_memory_gib(),
    }
