"""Render combined cliff results as Markdown tables (results/summary.md).

usage: python scripts/render_results.py results/final_*.json [--csfp results/csfp/final_*.json] > results/summary.md

With --csfp, a section compares the 2025 runs that count the Commodity
Supplemental Food Program as the model does (CSFP=keep scripts/run_final.sh),
using results/csfp/reach_2025.json from scripts/csfp_reach.py where it exists.
Where results/counted_once/once_<year>.json exist (scripts/counted_once.py), a
section repeats the Medicaid scaling with the premium tax credit counted once
and says where the credit is the largest loss.
"""

import json
import sys
from pathlib import Path

LABELS = {
    "people_on_cliff": "Adults facing a cliff",
    "households_with_person_on_cliff": "Their households",
    "people_in_those_households": "Household members",
    "workers_on_cliff": "Workers facing a cliff",
}
PROGRAMS = {
    "snap": "SNAP",
    "ssi": "SSI",
    "tanf": "TANF",
    "wic": "WIC",
    "free_school_meals": "Free school meals",
    "reduced_price_school_meals": "Reduced-price school meals",
    "household_state_benefits": "State benefits",
    "household_refundable_tax_credits": "Refundable tax credits",
    "household_tax_before_refundable_credits": "Taxes",
    "medicaid_cost": "Medicaid",
    "msp_cost": "Medicare Savings Programs",
    "chip": "CHIP",
    "assigned_aca_ptc": "ACA premium tax credit",
    "marketplace_net_premium": "Marketplace premium (net of credit)",
    "chip_premium": "CHIP premium",
    "housing_assistance": "Housing assistance",
    "head_start": "Head Start",
    "early_head_start": "Early Head Start",
    "social_security": "Social Security",
    "unemployment_compensation": "Unemployment compensation",
    "spm_unit_broadband_subsidy": "Broadband subsidy",
    "commodity_supplemental_food_program": "Commodity Supplemental Food Program",
}
# Labels for the program totals that PROGRAMS lacks or that need telling apart.
TOTALS = {
    "household_net_income": "Household net income",
    "household_benefits": "All household benefits",
    "aca_ptc": "ACA premium tax credit before take-up",
    "assigned_aca_ptc": "ACA premium tax credit after take-up",
    "eitc": "EITC",
    "refundable_ctc": "Refundable child tax credit",
    "household_head_start_benefits": "Head Start",
}
REACH = Path("results/csfp/reach_2025.json")
ONCE = Path("results/counted_once")
TAKE_UP = Path("results/take_up_bounds.json")
TAKE_UP_GROUPS = {
    "school_meals": "School meals",
    "state_benefits": "State benefits",
    "chip": "CHIP",
    "medicare_savings_programs": "Medicare Savings Programs",
    "state_health_programs": "State health programs",
    "all_of_these": "Any of these",
}


def name(result, credit=""):
    """A run's label; with credit ("once" or "twice"), a health run says how it counts the credit."""
    health = "counting health coverage" if result["health_benefits_in_net_income"] else "cash and near-cash only"
    label = f"{result['year']} rules, {health}"
    if credit and result["health_benefits_in_net_income"]:
        label += f", premium tax credit counted {credit}"
    return label


def csfp_label(result):
    # Runs made before --leave-out-csfp existed don't record it; they ran without it.
    return "leaving CSFP out" if result.get("leave_out_csfp", False) else "counting CSFP"


def millions(x, se=None):
    text = f"{x / 1e6:,.2f}M"
    if se is not None:
        text += f" (± {1.96 * se / 1e6:,.2f}M)"
    return text


def counts_table(rows):
    print("| Configuration | " + " | ".join(LABELS.values()) + " | Share of workers |")
    print("|" + "---|" * (len(LABELS) + 2))
    for label, r in rows:
        cells = [millions(r[k], r["standard_errors"].get(k)) for k in LABELS]
        cells.append(f"{100 * r['workers_on_cliff'] / r['workers']:.2f}%")
        print(f"| {label} | " + " | ".join(cells) + " |")


def csfp_section(main_results, csfp_paths):
    kept = sorted((json.load(open(p)) for p in csfp_paths), key=lambda r: r["health_benefits_in_net_income"])
    if not kept:
        return
    for r in kept:
        if r.get("leave_out_csfp", False):
            sys.exit("a --csfp result records leave_out_csfp; it belongs with the main results")
    print("\n## Counting the Commodity Supplemental Food Program\n")
    print("From 2024, PolicyEngine-US counts the Commodity Supplemental Food Program (CSFP) in")
    print("household benefits and gives its food package to everyone the program's rules admit.")
    if REACH.exists():
        reach = json.loads(REACH.read_text())
        line = (
            f"Weighting up a {100 * reach['fraction']:.0f}% household sample, we find that the model gives "
            f"{reach['model_recipients'] / 1e6:.1f} million people a package in {reach['year']}, "
            f"at ${reach['model_spending'] / 1e9:.1f} billion"
        )
        if reach.get("cited"):
            line += (
                f". It values each package at ${reach['package_value']:,.0f}, the program's "
                f"{reach['year']} cost of ${reach['cited']['funding'] / 1e6:,.0f} million divided by its "
                f"{reach['cited']['participation']:,.0f} participants"
            )
        print(line + ".")
    print("A 2017 run reads the model's earlier list, which has no CSFP, so we leave CSFP out of")
    print("the main 2025 rows as well (cliffs2017/benefits.py). In these rows, we count it as the")
    print("model does.\n")
    by_health = {r["health_benefits_in_net_income"]: r for r in main_results if r["year"] == 2025}
    rows = []
    for r in kept:
        base = by_health.get(r["health_benefits_in_net_income"])
        if base:
            rows.append((f"{name(base, 'twice')}, {csfp_label(base)}", base))
        rows.append((f"{name(r, 'twice')}, {csfp_label(r)}", r))
        if r["health_benefits_in_net_income"] and "premium_tax_credit_counted_once" in r:
            if base and "premium_tax_credit_counted_once" in base:
                rows.append((f"{name(base, 'once')}, {csfp_label(base)}", once_row(base)))
            rows.append((f"{name(r, 'once')}, {csfp_label(r)}", once_row(r)))
    counts_table(rows)
    for r in kept:
        drivers = r.get("people_on_cliff_by_driver", {})
        csfp = drivers.get("commodity_supplemental_food_program")
        if csfp:
            print(f"\nCounting CSFP, losing it lowers net income most for {millions(csfp)} of the"
                  f" {millions(r['people_on_cliff'])} adults facing a cliff under {name(r)}.")


def counted_once_section(results, folder=ONCE):
    """Medicaid's scaling and the credit as largest loss, counting the credit once."""
    once = sorted((json.loads(p.read_text()) for p in folder.glob("once_*.json")), key=lambda r: r["year"])
    if not once:
        return
    print("\n## Medicaid valued differently, with the premium tax credit counted once\n")
    print("scripts/counted_once.py rebuilds each part of the runs counting health coverage,")
    print("reproduces their counted-once counts and the table above, and scales every")
    print("enrollee's Medicaid value by the factor shown.\n")
    cols = sorted(list(once[0]["medicaid_value_scaled_counted_once"]) + ["1"], key=float)
    print("| Configuration | " + " | ".join(f"x{c}" for c in cols) + " |")
    print("|" + "---|" * (len(cols) + 1))
    for r in once:
        row = {k: v["people_on_cliff"] for k, v in r["medicaid_value_scaled_counted_once"].items()}
        row["1"] = r["counted_once"]["people_on_cliff"]
        print(f"| {name(r, 'once')} | " + " | ".join(millions(row[c]) for c in cols) + " |")
    print("\n## The premium tax credit as the largest loss\n")
    for r in once:
        p = r["premium_tax_credit_largest_loss"]
        if not p["sample_people"]:
            print(f"Under {name(r)}, with the credit counted once, the credit is no adult's largest loss.\n")
            continue
        print(
            f"Under {name(r)}, with the credit counted once, losing the credit lowers net income most"
            f" for {millions(p['people'])} adults ({p['sample_people']} in the sample). For"
            f" {millions(p['lifted_past_400'])} ({p['sample_lifted_past_400']} in the sample), the raise lifts"
            f" their tax unit's income from below 400% of the poverty line to 400% or more;"
            f" {millions(p['lose_income_test'])} ({p['sample_lose_income_test']}) fail the credit's income test"
            f" after the raise, and {millions(p['lose_whole_credit'])} ({p['sample_lose_whole_credit']}) lose"
            f" their tax unit's whole credit.\n"
        )


def take_up_section(path=TAKE_UP):
    """Cliffs that disappear without the change in benefits the model gives to everyone eligible."""
    if not path.exists():
        return
    runs = json.loads(path.read_text())["runs"]
    print("## Cliffs that rest on benefits the model gives to everyone eligible\n")
    print("Microcosm supplies take-up for SNAP, SSI, TANF, WIC, housing assistance, Head Start,")
    print("Medicaid, Medicare, the ACA premium tax credit and the EITC.")
    print("We set WIC take-up from the draw Microcosm stores, as policyengine.py does")
    print("(cliffs2017/wic_take_up.py). PolicyEngine-US gives free and reduced-price school meals,")
    print("most state child care subsidies, CHIP, Medicare Savings Programs and several state")
    print("health programs to everyone eligible. It counts school meals for every K-12 child in an")
    print("eligible family on all 180 school days. In each cell, scripts/take_up_bounds.py counts")
    print("the adults facing a cliff whose cliff would disappear if that benefit didn't change")
    print("with the raise. If some families don't take up these benefits, only some of the cliffs")
    print("in each cell would disappear. The state benefits column also holds state supplements")
    print("to SSI. Some states pay these only to SSI recipients, so they follow Microcosm's SSI")
    print("take-up, and the column overstates the cliffs that rest on full take-up. When a raise")
    print("ends Medicaid for someone in a household, the model can start their CHIP or Medicare")
    print("Savings Program instead. A household that didn't take that coverage up would lose the")
    print("offset, so the model can also miss cliffs. The per-person files hold only cliff rows,")
    print("so we can't count those. In the rows counting health coverage, we count the premium")
    print("tax credit once.\n")
    groups = [g for g in TAKE_UP_GROUPS if any(g in e[k]["groups"] for e in runs.values() for k in e)]
    print("| Configuration | Adults facing a cliff | " + " | ".join(TAKE_UP_GROUPS[g] for g in groups) + " |")
    print("|" + "---|" * (len(groups) + 2))
    for run, entry in runs.items():
        year, kind = run.split("_")
        health = kind == "health"
        b = entry["credit_counted_once" if health else "as_modeled"]
        label = name({"year": year, "health_benefits_in_net_income": health}, "once")
        cells = []
        for g in groups:
            if g in b["groups"]:
                v = b["groups"][g]
                cells.append(f"{millions(v['cliffs_that_disappear'])} ({100 * v['share']:.0f}%)")
            else:
                cells.append("–")
        print(f"| {label} | {millions(b['people_on_cliff'])} | " + " | ".join(cells) + " |")
    print()


def once_row(r):
    o = r["premium_tax_credit_counted_once"]
    return dict(o, workers=r["workers"])


def main(argv):
    paths, csfp_paths = argv, []
    if "--csfp" in argv:
        i = argv.index("--csfp")
        paths, csfp_paths = argv[:i], argv[i + 1 :]
    results = [json.load(open(p)) for p in paths]
    results.sort(key=lambda r: (r["year"], r["health_benefits_in_net_income"]))
    print("# Cliff counts\n")
    print("Each count is a weighted national total. The ± figure in parentheses is half the")
    print("width of its 95% interval, 1.96 standard errors from a bootstrap that resamples")
    print("source households (sampling error only).")
    print("PolicyEngine-US tests the two adults with the highest market income in each")
    print("household, so we count only adults as facing a cliff. For the share of workers, we")
    print("divide the adults facing a cliff who have earnings (wages plus self-employment")
    print("income above zero) by everyone with earnings, including people the model")
    print("doesn't test. We leave the Commodity Supplemental Food Program out of the 2025 rows")
    print("(see the last section). In the rows counting health coverage, we count the premium")
    print("tax credit twice, as the model does when it computes net income. In the table after")
    print("this one, we count it once, as we do in our headline counts; we give the reason in")
    print("METHODOLOGY.md.\n")
    header = "| Configuration | " + " | ".join(LABELS.values()) + " | Share of workers | Mean cliff gap |"
    print(header)
    print("|" + "---|" * (len(LABELS) + 3))
    for r in results:
        cells = [millions(r[k], r["standard_errors"].get(k)) for k in LABELS]
        cells.append(f"{100 * r['share_of_workers_on_cliff']:.2f}%")
        cells.append(f"${r['mean_cliff_gap_on_cliff']:,.0f}")
        print(f"| {name(r, 'twice')} | " + " | ".join(cells) + " |")
    once = [r for r in results if "premium_tax_credit_counted_once" in r and r["health_benefits_in_net_income"]]
    if once:
        print("\n## Premium tax credit counted once\n")
        print("PolicyEngine-US's health-inclusive net income adds the premium tax credit and")
        print("subtracts the premium net of that credit, so a change in the credit counts twice.")
        print("In these rows, we count it once.\n")
        counts_table([(name(r, "once"), once_row(r)) for r in once])
    scaled = [r for r in results if "medicaid_value_scaled" in r]
    if scaled:
        scales = list(scaled[0]["medicaid_value_scaled"])
        print("\n## Adults facing a cliff with Medicaid valued differently\n")
        print("PolicyEngine-US holds state Medicaid spending for 2020 through 2023 only, so the")
        print("2017 runs spread 2020 spending and the 2025 runs 2023 spending. In each column, we")
        print("scale every enrollee's Medicaid value by the factor shown. In these rows, we count")
        print("the premium tax credit twice, as the model does.\n")
        cols = sorted(scales + ["1"], key=float)
        print("| Configuration | " + " | ".join(f"x{c}" for c in cols) + " |")
        print("|" + "---|" * (len(cols) + 1))
        for r in scaled:
            row = {**{k: v["people_on_cliff"] for k, v in r["medicaid_value_scaled"].items()}, "1": r["people_on_cliff"]}
            print(f"| {name(r, 'twice')} | " + " | ".join(millions(row[c]) for c in cols) + " |")
    counted_once_section(results)
    checked = [r for r in results if "medicaid_value_check" in r]
    if checked:
        print("\n## Medicaid's value against the spending it spreads ($ billions)\n")
        print("| Configuration | Medicaid value, full sample | State spending | Gap |")
        print("|---|---|---|---|")
        for r in checked:
            c = r["medicaid_value_check"]
            print(f"| {name(r)} | {c['medicaid_cost_total'] / 1e9:,.1f} | {c['spending_total'] / 1e9:,.1f} | {100 * c['relative_gap']:.3f}% |")
    print("\n## What lowers net income most, for adults facing a cliff\n")
    for r in results:
        variants = [("twice", r.get("people_on_cliff_by_driver"))]
        if r["health_benefits_in_net_income"] and "premium_tax_credit_counted_once" in r:
            variants.append(("once", r["premium_tax_credit_counted_once"].get("people_on_cliff_by_driver")))
        for credit, drivers in variants:
            if not drivers:
                continue
            total = sum(drivers.values())
            print(f"**{name(r, credit)}**\n")
            print("| Largest loss | Adults | Share |")
            print("|---|---|---|")
            for key, value in sorted(drivers.items(), key=lambda kv: -kv[1]):
                print(f"| {PROGRAMS.get(key, key)} | {millions(value)} | {100 * value / total:.0f}% |")
            print()
    take_up_section()
    print("## Program totals in each run ($ billions)\n")
    keys = []
    for r in results:
        for k, v in r["program_totals"].items():
            if isinstance(v, (int, float)) and k not in keys:
                keys.append(k)
    print("| Program | " + " | ".join(name(r) for r in results) + " |")
    print("|---|" + "---|" * len(results))
    for k in keys:
        cells = [f"{r['program_totals'][k] / 1e9:,.1f}" if k in r["program_totals"] else "–" for r in results]
        print(f"| {TOTALS.get(k, PROGRAMS.get(k, k))} ({k}) | " + " | ".join(cells) + " |")
    if {"aca_ptc", "assigned_aca_ptc"} <= set(keys):
        print("\nassigned_aca_ptc multiplies aca_ptc by takes_up_aca_if_eligible. Net income counting")
        print("health coverage adds assigned_aca_ptc, the credit the tables above call the ACA")
        print("premium tax credit.")
    if any("medicaid_cost" in r.get("program_totals_left_out", {}) for r in results):
        print("\nThe runs without health coverage leave out Medicaid's value: they don't hold")
        print("Medicaid's full-sample state totals, and their net income leaves Medicaid out.")
    other = {
        (name(r), key, why)
        for r in results
        for key, why in r.get("program_totals_left_out", {}).items()
        if key != "medicaid_cost"
    }
    if other:
        print("\nTotals a part couldn't compute, left out:\n")
        for config, key, why in sorted(other):
            print(f"- {config}: {key} ({why})")
    csfp_section(results, csfp_paths)


if __name__ == "__main__":
    main(sys.argv[1:])
