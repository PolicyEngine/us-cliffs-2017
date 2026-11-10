"""Add up disjoint household parts of one configuration into full-sample results.

Each part (cliffs2017.run --parts P --part i) holds different households at
full weight. In the model, households interact only through Medicaid's two
state totals, and runs with health coverage counted fix those at their
full-sample values (cliffs2017.medicaid), so every weighted total of the full
sample is the sum of the parts' totals. Ratios are recomputed from the summed
totals. The bootstrap resamples households within each part, so the parts'
estimates are independent and their variances add.

With health coverage counted, Medicaid's value over the full sample must add
up to the spending the totals spread: the combined ``medicaid_cost`` has to
match the totals file's ``spending_total`` within MEDICAID_TOLERANCE, or the
combine fails.

Usage:
  python -m cliffs2017.combine results/parts/run_2017_plain_p4_*.json --out results/final_2017_plain.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter

ADDITIVE = [
    "people_total",
    "households_total",
    "workers",
    "workers_evaluated",
    "people_on_cliff",
    "workers_on_cliff",
    "households_with_person_on_cliff",
    "people_in_those_households",
    "cliff_gap_total",
    "sample_people_on_cliff",
    "sample_households",
    "decomposition_flag_mismatches",
]
HEADLINE = [
    "people_on_cliff",
    "workers_on_cliff",
    "households_with_person_on_cliff",
    "people_in_those_households",
]
SAME = [
    "year",
    "health_benefits_in_net_income",
    "aca_before_2018",
    "leave_out_csfp",
    "parts",
    "seed",
    "versions",
    "dataset",
    "python",
    "deflation",
    "medicaid_totals",
]
# Runs made before an option existed don't record it; they ran without it.
DEFAULTS = {"leave_out_csfp": False}
MEDICAID_TOLERANCE = 1e-3


def add_dicts(dicts):
    out = Counter()
    for d in dicts:
        for key, value in d.items():
            if isinstance(value, (int, float)):
                out[key] += value
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def quadrature(dicts):
    keys = dicts[0].keys()
    return {k: math.sqrt(sum(d[k] ** 2 for d in dicts)) for k in keys}


def combine(results: list[dict]) -> dict:
    if not results:
        raise ValueError("no parts to combine")
    first = results[0]
    for key in SAME:
        values = [json.dumps(r.get(key, DEFAULTS.get(key)), sort_keys=True) for r in results]
        if len(set(values)) > 1:
            raise ValueError(f"parts disagree on {key}")
    parts = first["parts"]
    indices = sorted(r["part"] for r in results)
    if indices != list(range(parts)):
        raise ValueError(f"expected parts 0..{parts - 1} once each, got {indices}")

    out = {key: first.get(key, DEFAULTS.get(key)) for key in SAME if key in first or key in DEFAULTS}
    for key in ADDITIVE:
        if all(key in r for r in results):
            out[key] = sum(r[key] for r in results)
    out["share_of_workers_on_cliff"] = out["workers_on_cliff"] / out["workers"]
    out["mean_cliff_gap_on_cliff"] = (
        out["cliff_gap_total"] / out["people_on_cliff"] if out["people_on_cliff"] else 0.0
    )
    out["standard_errors"] = quadrature([r["standard_errors"] for r in results])
    if all("people_on_cliff_by_driver" in r for r in results):
        out["people_on_cliff_by_driver"] = add_dicts(
            [r["people_on_cliff_by_driver"] for r in results]
        )
    if all("premium_tax_credit_counted_once" in r for r in results):
        once = [r["premium_tax_credit_counted_once"] for r in results]
        out["premium_tax_credit_counted_once"] = dict(
            **{k: sum(o[k] for o in once) for k in HEADLINE + ["sample_people_on_cliff"]},
            standard_errors=quadrature([o["standard_errors"] for o in once]),
            people_on_cliff_by_driver=add_dicts([o["people_on_cliff_by_driver"] for o in once]),
        )
    if all("medicaid_value_scaled" in r for r in results):
        out["medicaid_value_scaled"] = {
            scale: {k: sum(r["medicaid_value_scaled"][scale][k] for r in results) for k in HEADLINE}
            for scale in first["medicaid_value_scaled"]
        }
    for key in ("program_totals", "people_in_recipient_units"):
        out[key] = add_dicts([r[key] for r in results])
    if parts > 1 and not first.get("medicaid_totals"):
        # Without the full-sample totals, each part values Medicaid from its
        # own state sums (cliffs2017.medicaid), so the parts' values don't add
        # up to a full-sample total. These runs leave health coverage out of
        # net income, so their cliff counts don't use Medicaid's value.
        if out["program_totals"].pop("medicaid_cost", None) is not None:
            out["program_totals_left_out"] = {
                "medicaid_cost": "parts value Medicaid from their own state sums"
            }
    if first.get("health_benefits_in_net_income"):
        if not first.get("medicaid_totals"):
            raise ValueError("health runs need full-sample Medicaid totals (cliffs2017.medicaid)")
        cost = out["program_totals"]["medicaid_cost"]
        spending = first["medicaid_totals"]["spending_total"]
        gap = abs(cost - spending) / spending
        out["medicaid_value_check"] = dict(
            medicaid_cost_total=cost, spending_total=spending, relative_gap=gap
        )
        if gap > MEDICAID_TOLERANCE:
            raise ValueError(
                f"Medicaid value ${cost:,.0f} misses the spending it spreads, ${spending:,.0f}"
            )
    out["seconds"] = sum(r["timing_seconds"]["total"] for r in results)
    out["part_files"] = sorted(r.get("_file", "") for r in results)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    results = []
    for path in args.files:
        with open(path) as f:
            result = json.load(f)
        result["_file"] = path
        results.append(result)
    combined = combine(results)
    with open(args.out, "w") as f:
        json.dump(combined, f, indent=1)
    print(json.dumps({k: combined[k] for k in HEADLINE + ["standard_errors"]}, indent=1))


if __name__ == "__main__":
    main()
