"""Add up disjoint household parts of one configuration into full-sample results.

Each part (cliffs2017.run --parts P --part i) holds different households at
full weight. In the model, households interact only through Medicaid's two
state totals, and runs with health coverage counted fix those at their
full-sample values (cliffs2017.medicaid), so every weighted total of the full
sample is the sum of the parts' totals. Ratios are recomputed from the summed
totals. The bootstrap resamples source households within each part, and a
source household's records always share a part (cliffs2017.deflate), so the
parts' estimates are independent and their variances add.

Every part must agree on the configuration (SAME), including the hash of the
code that computed it, and on any ``--expect KEY=VALUE`` the caller passes,
such as ``--expect leave_out_csfp=true``. A program total that a part could
not compute is left out of the sum and listed in ``program_totals_left_out``.

With health coverage counted, Medicaid's value over the full sample must add
up to the spending the totals spread: the combined ``medicaid_cost`` has to
match the totals file's ``spending_total`` within MEDICAID_TOLERANCE, or the
combine fails.

Usage:
  python -m cliffs2017.combine results/parts/run_2017_plain_p4_*.json \
      --expect leave_out_csfp=false --out results/final_2017_plain.json
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
    "sample_clusters",
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
    "decompose",
    "bootstrap_clusters",
    "parts",
    "seed",
    "code",
    "versions",
    "dataset",
    "python",
    "deflation",
    "medicaid_totals",
]
# Runs made before an option existed don't record it; they ran without it.
DEFAULTS = {"leave_out_csfp": False}
MEDICAID_TOLERANCE = 1e-3


def comparable(key, value):
    """The part of a recorded setting that must match across parts."""
    if key == "code" and value:
        # The hash of cliffs2017/, not the commit: committing docs mid-run is fine.
        return value.get("cliffs2017_sha256")
    if key == "medicaid_totals" and value:
        # The same file under another path spelling is the same totals.
        return {k: v for k, v in value.items() if k != "file"}
    return value


def setting(result, key):
    return comparable(key, result.get(key, DEFAULTS.get(key)))


def add_totals(results, key):
    """Sum each total over the parts, leaving out any total a part lacks a number for."""
    names = sorted(set().union(*(r[key] for r in results)))
    out, left_out = {}, {}
    for name in names:
        values = [(r["part"], r[key].get(name)) for r in results]
        bad = [(part, v) for part, v in values if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            left_out[name] = "; ".join(f"part {part}: {v!r}"[:200] for part, v in bad)
        else:
            out[name] = sum(v for _, v in values)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])), left_out


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


def combine(results: list[dict], expect: dict | None = None) -> dict:
    if not results:
        raise ValueError("no parts to combine")
    first = results[0]
    for key in SAME:
        values = [json.dumps(setting(r, key), sort_keys=True) for r in results]
        if len(set(values)) > 1:
            raise ValueError(f"parts disagree on {key}")
    for key, value in (expect or {}).items():
        for r in results:
            if setting(r, key) != value:
                raise ValueError(
                    f"{r.get('_file', 'a part')} records {key}={setting(r, key)!r}, expected {value!r}"
                )
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
    left_out = {}
    for key in ("program_totals", "people_in_recipient_units"):
        out[key], missing = add_totals(results, key)
        prefix = "" if key == "program_totals" else f"{key}."
        left_out.update({f"{prefix}{name}": why for name, why in missing.items()})
    if parts > 1 and not first.get("medicaid_totals"):
        # Without the full-sample totals, each part values Medicaid from its
        # own state sums (cliffs2017.medicaid), so the parts' values don't add
        # up to a full-sample total. These runs leave health coverage out of
        # net income, so their cliff counts don't use Medicaid's value.
        if out["program_totals"].pop("medicaid_cost", None) is not None:
            left_out["medicaid_cost"] = (
                "parts value Medicaid from their own state sums"
            )
    if left_out:
        out["program_totals_left_out"] = left_out
    if first.get("health_benefits_in_net_income"):
        if not first.get("medicaid_totals"):
            raise ValueError("health runs need full-sample Medicaid totals (cliffs2017.medicaid)")
        if "medicaid_cost" not in out["program_totals"]:
            raise ValueError("a health run's parts must all compute medicaid_cost")
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
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a setting (VALUE in JSON) every part must record, e.g. leave_out_csfp=true",
    )
    args = parser.parse_args()
    expect = {}
    for item in args.expect:
        key, _, value = item.partition("=")
        expect[key] = json.loads(value)
    results = []
    for path in args.files:
        with open(path) as f:
            result = json.load(f)
        result["_file"] = path
        results.append(result)
    combined = combine(results, expect)
    with open(args.out, "w") as f:
        json.dump(combined, f, indent=1)
    print(json.dumps({k: combined[k] for k in HEADLINE + ["standard_errors"]}, indent=1))


if __name__ == "__main__":
    main()
