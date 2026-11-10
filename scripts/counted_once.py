"""Medicaid's value and the premium tax credit, with the credit counted once.

cliffs2017.run counts the adults facing a cliff with the premium tax credit
counted once (premium_tax_credit_counted_once), but it scales Medicaid's value
(medicaid_value_scaled) only for the model's own count, which counts a change
in the credit twice. For one household part of a final run counting health
coverage, this script rebuilds the part as scripts/run_final.sh runs it and,
with the credit counted once, reports:

1. the headline counts when every enrollee's Medicaid value scales by each
   factor in cliffs2017.run.MEDICAID_SCALES, as run.py does for the model's
   own count;
2. for the adults facing a cliff whose largest loss is the premium tax credit,
   how many the $1,000 raise lifts from below 400% of the poverty line to 400%
   or more, how many it costs the credit's income test
   (gov.aca.ptc_income_eligibility, which ends at 400% before 2021), and how
   many lose their tax unit's whole credit.

It stops unless it reproduces the committed part in results/parts/: the
counted-once counts, the counted-once counts by largest loss, and the model's
own Medicaid scaling. It also stops if cliffs2017/ or this script has
uncommitted changes, so the commit it records holds the code that ran.

usage:
  python scripts/counted_once.py --year 2017 --part 0 [--parts 4] [--seed 0]
  python scripts/counted_once.py --combine results/counted_once/parts/once_2017_p4_*_s0.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cliffs2017.run import (  # noqa: E402
    FILENAME,
    MEDICAID_SCALES,
    REPO,
    REVISION,
    code_version,
    headline,
)

OUT = ROOT / "results" / "counted_once"
PTC = "assigned_aca_ptc"
# 400% of the poverty line, in aca_magi_fraction's units.
LIMIT = 4.0
HEADLINE = (
    "people_on_cliff",
    "workers_on_cliff",
    "households_with_person_on_cliff",
    "people_in_those_households",
)
OUTCOMES = ("lifted_past_400", "lose_income_test", "lose_whole_credit")
# Settings every part of one run shares (the part index aside).
SHARED = (
    "year",
    "health_benefits_in_net_income",
    "aca_before_2018",
    "leave_out_csfp",
    "parts",
    "seed",
    "versions",
    "dataset",
    "code",
)


def settings(year: int, parts: int, part: int, seed: int) -> dict:
    """The settings scripts/run_final.sh gives a health run of this year."""
    return dict(
        year=year,
        health_benefits_in_net_income=True,
        aca_before_2018=year < 2018,
        leave_out_csfp=year >= 2024,
        parts=parts,
        part=part,
        seed=seed,
    )


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def mismatches(label: str, ours: dict, theirs: dict) -> list[str]:
    """One line for each key whose value differs, or that one side lacks."""
    return [
        f"{label}.{key}: {ours.get(key)} here, {theirs.get(key)} committed"
        for key in sorted(set(ours) | set(theirs))
        if key not in ours or key not in theirs or not close(ours[key], theirs[key])
    ]


def ptc_outcomes(base_fraction, alt_fraction, base_credit, alt_credit, income_eligible):
    """For each adult, whether the raise lifts their tax unit's income past 400%
    of the poverty line, costs it the credit's income test, and ends its credit."""
    base_fraction = np.asarray(base_fraction, dtype=float)
    alt_fraction = np.asarray(alt_fraction, dtype=float)
    lifted = (base_fraction < LIMIT) & (alt_fraction >= LIMIT)
    lose_test = income_eligible(base_fraction) & ~income_eligible(alt_fraction)
    lose_credit = (np.asarray(base_credit) > 0) & (np.asarray(alt_credit) <= 0)
    return dict(lifted_past_400=lifted, lose_income_test=lose_test, lose_whole_credit=lose_credit)


def summarize(weight, outcomes: dict) -> dict:
    """Weighted and sample counts of the adults and of each outcome."""
    weight = np.asarray(weight, dtype=float)
    out = dict(people=float(weight.sum()), sample_people=int(weight.size))
    for name in OUTCOMES:
        flags = np.asarray(outcomes[name], dtype=bool)
        out[name] = float(weight[flags].sum())
        out[f"sample_{name}"] = int(flags.sum())
    return out


def compute(sim, year: int, people: pd.DataFrame) -> dict:
    """The counted-once counts, Medicaid scaling and premium tax credit outcomes."""
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
        earnings_increments,
    )

    from cliffs2017.decompose import decompose, primary_driver

    weight = people["weight"].to_numpy()
    frame = decompose(sim, year)
    index = frame["person_index"].to_numpy()

    def on_cliff(change) -> np.ndarray:
        flags = np.zeros(len(people), dtype=bool)
        flags[index] = np.asarray(change) < 0
        return flags

    once = frame["d_net_single_ptc"]
    medicaid = frame["d_medicaid_cost"]
    result = dict(
        counted_once=headline(people, on_cliff(once)),
        medicaid_value_scaled_counted_once={
            f"{s:g}": headline(people, on_cliff(once + (s - 1) * medicaid)) for s in MEDICAID_SCALES
        },
        medicaid_value_scaled_model={
            f"{s:g}": headline(people, on_cliff(frame["d_net"] + (s - 1) * medicaid))
            for s in MEDICAID_SCALES
        },
    )
    # As cliffs2017.run ranks the parts for the counted-once count.
    rows = frame[once < 0].copy()
    rows["weight"] = weight[rows["person_index"]]
    rows["driver"] = primary_driver(rows.drop(columns=["d_marketplace_net_premium"], errors="ignore"))
    result["counted_once_by_driver"] = {
        key: float(value) for key, value in rows.groupby("driver")["weight"].sum().items()
    }

    ptc_rows = rows[rows["driver"] == PTC]
    p = sim.tax_benefit_system.parameters(year)
    delta = float(p.simulation.marginal_tax_rate_delta)
    eligibility = p.gov.aca.ptc_income_eligibility

    def income_eligible(fraction):
        return np.asarray(eligibility.calc(np.asarray(fraction, dtype=float))).astype(bool)

    person = sim.populations["person"]
    rank = np.asarray(sim.calculate("adult_earnings_index", year))
    is_adult = np.asarray(sim.calculate("is_adult", year)).astype(bool)
    base_fraction = np.asarray(sim.calculate("aca_magi_fraction", year, map_to="person"), dtype=float)
    base_credit = np.asarray(sim.calculate(PTC, year, map_to="person"), dtype=float)
    weights, outcomes = [], {name: [] for name in OUTCOMES}
    for k in sorted(ptc_rows["rank"].unique()):
        # The branch decompose built for these adults: the same raise.
        mask = is_adult & (rank == k)
        name = f"counted_once_ptc_adult_{k}"
        branch = create_perturbed_branch(sim, year, name, earnings_increments(person, year, mask * delta))
        alt_fraction = np.asarray(branch.calculate("aca_magi_fraction", year, map_to="person"), dtype=float)
        alt_credit = np.asarray(branch.calculate(PTC, year, map_to="person"), dtype=float)
        del sim.branches[name]
        who = ptc_rows[ptc_rows["rank"] == k]
        i = who["person_index"].to_numpy()
        found = ptc_outcomes(
            base_fraction[i], alt_fraction[i], base_credit[i], alt_credit[i], income_eligible
        )
        weights.append(who["weight"].to_numpy())
        for key in OUTCOMES:
            outcomes[key].append(found[key])
    result["premium_tax_credit_largest_loss"] = summarize(
        np.concatenate(weights) if weights else np.zeros(0),
        {key: np.concatenate(v) if v else np.zeros(0, dtype=bool) for key, v in outcomes.items()},
    )
    return result


def check_part(result: dict, committed: dict) -> list[str]:
    """Where this rebuild differs from the committed part's counts."""
    once = committed["premium_tax_credit_counted_once"]
    problems = mismatches("counted_once", result["counted_once"], {k: once[k] for k in HEADLINE})
    problems += mismatches("counted_once_by_driver", result["counted_once_by_driver"], once["people_on_cliff_by_driver"])
    for scale, counts in result["medicaid_value_scaled_model"].items():
        problems += mismatches(f"medicaid_value_scaled[{scale}]", counts, committed["medicaid_value_scaled"][scale])
    return problems


def uncommitted() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "cliffs2017", "scripts/counted_once.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def run_part(year: int, parts: int, part: int, seed: int) -> Path:
    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.medicaid import check_totals_match, load_totals
    from cliffs2017.run import load_dataset
    from cliffs2017.simulation import build_simulation

    started = time.time()
    dirty = uncommitted()
    if dirty:
        sys.exit(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    code = dict(code_version(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    wanted = settings(year, parts, part, seed)
    committed_path = ROOT / "results" / "parts" / f"run_{year}_health_p{parts}_{part}_s{seed}.json"
    committed = json.loads(committed_path.read_text())
    for key, value in wanted.items():
        if committed.get(key) != value:
            sys.exit(f"{committed_path}: {key} is {committed.get(key)!r}, not {value!r}")
    versions = {package: metadata.version(package) for package in ("policyengine-us", "policyengine-core")}
    dataset_name = f"{REPO}/{FILENAME}@{REVISION}"
    if committed.get("versions") != versions or committed.get("dataset") != dataset_name:
        sys.exit(f"{committed_path} ran {committed.get('versions')} on {committed.get('dataset')}, "
                 f"not {versions} on {dataset_name}")
    totals_file = committed["medicaid_totals"]["file"]
    totals, meta = load_totals(ROOT / totals_file)
    if meta["sha256"] != committed["medicaid_totals"]["sha256"]:
        sys.exit(f"{totals_file} changed since {committed_path} ran")
    check_totals_match(meta, year, wanted["aca_before_2018"], dataset_name)

    system = CountryTaxBenefitSystem()
    dataset, _ = load_dataset(year, 1.0, seed, system, parts, part)
    sim = build_simulation(dataset, year, True, wanted["aca_before_2018"], totals, wanted["leave_out_csfp"])

    def arr(variable, map_to=None):
        return np.asarray(sim.calculate(variable, year, map_to=map_to).values)

    earnings = arr("employment_income") + arr("self_employment_income") + arr("sstb_self_employment_income")
    people = pd.DataFrame(
        dict(
            household_id=arr("household_id", map_to="person"),
            weight=arr("person_weight").astype(np.float64),
            worker=earnings > 0,
        )
    )
    result = compute(sim, year, people)
    problems = check_part(result, committed)
    if problems:
        sys.exit(f"doesn't reproduce {committed_path}:\n" + "\n".join(problems))
    out = dict(
        wanted,
        **result,
        reproduces=str(committed_path.relative_to(ROOT)),
        versions=versions,
        dataset=dataset_name,
        code=code,
        seconds=round(time.time() - started, 1),
    )
    path = OUT / "parts" / f"once_{year}_p{parts}_{part}_s{seed}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    return path


def add(dicts: list[dict]) -> dict:
    return {key: sum(d[key] for d in dicts) for key in dicts[0]}


def combine(parts: list[dict], final: dict) -> dict:
    """Add disjoint household parts up, and check the sums against the final run."""
    first = parts[0]
    for r in parts[1:]:
        for key in SHARED:
            if r[key] != first[key]:
                raise ValueError(f"the parts differ in {key}: {r[key]!r} and {first[key]!r}")
    indices = sorted(r["part"] for r in parts)
    if indices != list(range(first["parts"])):
        raise ValueError(f"parts {indices} don't cover 0 to {first['parts'] - 1} once each")
    for key in ("year", "health_benefits_in_net_income", "aca_before_2018", "leave_out_csfp", "parts", "seed", "versions", "dataset"):
        if final.get(key) != first[key]:
            raise ValueError(f"the final run's {key} is {final.get(key)!r}, not {first[key]!r}")
    out = {key: first[key] for key in SHARED}
    out["counted_once"] = add([r["counted_once"] for r in parts])
    for key in ("medicaid_value_scaled_counted_once", "medicaid_value_scaled_model"):
        out[key] = {s: add([r[key][s] for r in parts]) for s in first[key]}
    out["premium_tax_credit_largest_loss"] = add([r["premium_tax_credit_largest_loss"] for r in parts])
    once = final["premium_tax_credit_counted_once"]
    problems = mismatches("counted_once", out["counted_once"], {k: once[k] for k in HEADLINE})
    for scale, counts in out["medicaid_value_scaled_model"].items():
        problems += mismatches(f"medicaid_value_scaled[{scale}]", counts, final["medicaid_value_scaled"][scale])
    if PTC in once["people_on_cliff_by_driver"] or out["premium_tax_credit_largest_loss"]["people"]:
        problems += mismatches(
            "premium tax credit as largest loss",
            {"people": out["premium_tax_credit_largest_loss"]["people"]},
            {"people": once["people_on_cliff_by_driver"].get(PTC, 0.0)},
        )
    if problems:
        raise ValueError("the parts don't add up to the final run:\n" + "\n".join(problems))
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int)
    parser.add_argument("--parts", type=int, default=4)
    parser.add_argument("--part", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--combine", nargs="+", metavar="PART_FILE")
    args = parser.parse_args(argv)
    if args.combine:
        parts = [json.loads(Path(p).read_text()) for p in args.combine]
        year = parts[0]["year"]
        final_path = ROOT / "results" / f"final_{year}_health.json"
        try:
            out = combine(parts, json.loads(final_path.read_text()))
        except ValueError as error:
            sys.exit(str(error))
        out["adds_up_to"] = str(final_path.relative_to(ROOT))
        path = OUT / f"once_{year}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1) + "\n")
        print(path)
        return
    if args.year is None or args.part is None:
        parser.error("give --year and --part, or --combine")
    print(run_part(args.year, args.parts, args.part, args.seed))


if __name__ == "__main__":
    main()
