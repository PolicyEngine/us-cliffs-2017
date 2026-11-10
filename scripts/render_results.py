"""Render combined cliff results as Markdown tables (results/summary.md).

usage: python scripts/render_results.py results/final_*.json [--csfp results/csfp/final_*.json] > results/summary.md

With --csfp, a section compares the 2025 runs that count the Commodity
Supplemental Food Program as the model does (CSFP=keep scripts/run_final.sh),
using results/csfp/reach_2025.json from scripts/csfp_reach.py where it exists.
"""

import json
import sys
from pathlib import Path

LABELS = {
    "people_on_cliff": "Adults facing a cliff",
    "households_with_person_on_cliff": "Their households",
    "people_in_those_households": "People in those households",
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
REACH = Path("results/csfp/reach_2025.json")


def name(result):
    health = "counting health coverage" if result["health_benefits_in_net_income"] else "cash and near-cash only"
    return f"{result['year']} rules, {health}"


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
    print("\n## Counting the Commodity Supplemental Food Program\n")
    print("From 2024, PolicyEngine-US counts the Commodity Supplemental Food Program (CSFP) in")
    print("household benefits and gives its food package to everyone the program's rules admit.")
    if REACH.exists():
        reach = json.loads(REACH.read_text())
        line = (
            f"On a {100 * reach['fraction']:.0f}% household sample, the model gives "
            f"{reach['model_recipients'] / 1e6:.1f} million people a package in {reach['year']}, "
            f"at ${reach['model_spending'] / 1e9:.1f} billion"
        )
        if reach.get("cited"):
            line += (
                f"; the model's parameters cite the program's {reach['year']} funding and participation "
                f"as ${reach['cited']['funding'] / 1e6:,.0f} million and {reach['cited']['participation']:,.0f} people"
            )
        print(line + ".")
    print("A 2017 run reads the model's earlier list, which has no CSFP, so the main rows leave CSFP")
    print("out of 2025 as well (cliffs2017/benefits.py). These rows count it as the model does.\n")
    by_health = {r["health_benefits_in_net_income"]: r for r in main_results if r["year"] == 2025}
    rows = []
    for r in kept:
        base = by_health.get(r["health_benefits_in_net_income"])
        if base:
            rows.append((f"{name(base)}, leaving CSFP out", base))
        rows.append((f"{name(r)}, counting CSFP", r))
        if r["health_benefits_in_net_income"] and "premium_tax_credit_counted_once" in r:
            if base and "premium_tax_credit_counted_once" in base:
                rows.append((f"{name(base)}, leaving CSFP out, premium tax credit counted once", once_row(base)))
            rows.append((f"{name(r)}, counting CSFP, premium tax credit counted once", once_row(r)))
    counts_table(rows)
    for r in kept:
        drivers = r.get("people_on_cliff_by_driver", {})
        csfp = drivers.get("commodity_supplemental_food_program")
        if csfp:
            print(f"\nCounting CSFP, it is the largest loss for {millions(csfp)} of the {millions(r['people_on_cliff'])}"
                  f" adults facing a cliff under {name(r)}.")


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
    print("Each count is a weighted national total. Parentheses give 95% intervals")
    print("from a household bootstrap (sampling error only). PolicyEngine-US tests the")
    print("two adults with the highest market income in each household, so everyone")
    print("counted as facing a cliff is an adult.\n")
    header = "| Configuration | " + " | ".join(LABELS.values()) + " | Share of workers | Mean cliff gap |"
    print(header)
    print("|" + "---|" * (len(LABELS) + 3))
    for r in results:
        cells = [millions(r[k], r["standard_errors"].get(k)) for k in LABELS]
        cells.append(f"{100 * r['share_of_workers_on_cliff']:.2f}%")
        cells.append(f"${r['mean_cliff_gap_on_cliff']:,.0f}")
        print(f"| {name(r)} | " + " | ".join(cells) + " |")
    once = [r for r in results if "premium_tax_credit_counted_once" in r and r["health_benefits_in_net_income"]]
    if once:
        print("\n## Premium tax credit counted once\n")
        print("PolicyEngine-US's health-inclusive net income adds the premium tax credit and")
        print("subtracts the premium net of that credit, so a change in the credit counts twice.")
        print("These rows count it once.\n")
        print("| Configuration | " + " | ".join(LABELS.values()) + " |")
        print("|" + "---|" * (len(LABELS) + 1))
        for r in once:
            o = r["premium_tax_credit_counted_once"]
            cells = [millions(o[k], o["standard_errors"].get(k)) for k in LABELS]
            print(f"| {name(r)} | " + " | ".join(cells) + " |")
    scaled = [r for r in results if "medicaid_value_scaled" in r]
    if scaled:
        scales = list(scaled[0]["medicaid_value_scaled"])
        print("\n## Adults facing a cliff with Medicaid valued differently\n")
        print("PolicyEngine-US holds state Medicaid spending for 2020 through 2023 only, so the")
        print("2017 runs spread 2020 spending and the 2025 runs 2023 spending. Each column")
        print("scales every enrollee's Medicaid value by the factor shown.\n")
        cols = sorted(scales + ["1"], key=float)
        print("| Configuration | " + " | ".join(f"x{c}" for c in cols) + " |")
        print("|" + "---|" * (len(cols) + 1))
        for r in scaled:
            row = {**{k: v["people_on_cliff"] for k, v in r["medicaid_value_scaled"].items()}, "1": r["people_on_cliff"]}
            print(f"| {name(r)} | " + " | ".join(millions(row[c]) for c in cols) + " |")
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
        variants = [("", r.get("people_on_cliff_by_driver"))]
        if r["health_benefits_in_net_income"] and "premium_tax_credit_counted_once" in r:
            variants.append(
                (", premium tax credit counted once", r["premium_tax_credit_counted_once"].get("people_on_cliff_by_driver"))
            )
        for suffix, drivers in variants:
            if not drivers:
                continue
            total = sum(drivers.values())
            print(f"**{name(r)}{suffix}**\n")
            print("| Largest loss | Adults | Share |")
            print("|---|---|---|")
            for key, value in sorted(drivers.items(), key=lambda kv: -kv[1]):
                print(f"| {PROGRAMS.get(key, key)} | {millions(value)} | {100 * value / total:.0f}% |")
            print()
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
        print(f"| {k} | " + " | ".join(cells) + " |")
    if any("medicaid_cost" in r.get("program_totals_left_out", {}) for r in results):
        print("\nThe runs without health coverage leave out Medicaid's value: they don't hold")
        print("Medicaid's full-sample state totals, and their net income leaves Medicaid out.")
    csfp_section(results, csfp_paths)


if __name__ == "__main__":
    main(sys.argv[1:])
