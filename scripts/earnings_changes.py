"""Cliff counts for other changes in earnings, for one household part of a final run.

The final runs test each adult with PolicyEngine-US's own change, a $1,000
raise. This script rebuilds one household part of a final run that counts
health coverage, exactly as scripts/run_final.sh builds it, and repeats the
test for each change in ``--changes`` (cliffs2017.changes): raises and cuts, in
dollars or in proportion to the adult's earnings. Under a raise it counts the
adults whose household's net income falls; under a cut, the adults whose
household's net income rises.

From one simulation it counts both ways the texts do:

- before health coverage: the change in every part of net income except the
  health ones (cliffs2017.changes.without_health);
- counting health coverage, with the premium tax credit counted once
  (``d_net_single_ptc``).

For every adult a change reaches, it also records their tax unit's income as a
fraction of the poverty line (``aca_magi_fraction``) and its premium tax credit
(``assigned_aca_ptc``) before and after, so scripts/earnings_changes_summary.py
can count who crosses 400% of the poverty line.

Each change is written as soon as it is done: its weighted totals to
results/earnings_changes/parts/changes_<year>_p<parts>_<part>_s<seed>/<key>.json
and its per-person rows to results/parts/per_person/ (git-ignored record-level
output). A rerun skips the changes already written, so a run that stops loses
at most the change it was on. Each change builds two branches, and memory grows
with the branches one process builds, so scripts/run_earnings_changes.sh runs
two changes per process.

The $1,000 raise must reproduce the committed part: the count before health
coverage must equal the part of the final run without health coverage, and the
count with it the part's count with the credit counted once, in adults,
workers, households and members, to 1e-9. That checks both this code and the
premise that one simulation gives both counts. The change's file records
``reproduces_committed_part``; if it is false, the script writes the change and
then stops with an error, and scripts/earnings_changes_summary.py refuses the
part. The script also stops if cliffs2017/ or this script has uncommitted
changes, so the commit it records holds the code that ran.

usage:
  python scripts/earnings_changes.py --year 2017 --part 0 [--parts 4] [--seed 0]
      [--changes +1000,-1000] [--todo]
"""

from __future__ import annotations

import argparse
import gc
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

from cliffs2017.changes import (  # noqa: E402
    decompose_change,
    health_parts,
    moves_against,
    parse,
    without_health,
)
from cliffs2017.run import FILENAME, REPO, REVISION, code_version, headline  # noqa: E402

OUT = ROOT / "results" / "earnings_changes" / "parts"
PER_PERSON = ROOT / "results" / "parts" / "per_person"
CHANGES = "+1000,-1000,+2000,-2000,+5000,-5000,+1%,-1%,+10%,-10%"
PERSON_VARIABLES = ("aca_magi_fraction", "assigned_aca_ptc")
HEADLINE = (
    "people_on_cliff",
    "workers_on_cliff",
    "households_with_person_on_cliff",
    "people_in_those_households",
)
BASE = "raise_1000"
TOLERANCE = 1e-9


def stem(year: int, parts: int, part: int, seed: int) -> str:
    return f"changes_{year}_p{parts}_{part}_s{seed}"


def change_files(year: int, parts: int, part: int, seed: int, key: str) -> tuple[Path, Path]:
    """Where one change's totals and per-person rows go."""
    name = stem(year, parts, part, seed)
    return OUT / name / f"{key}.json", PER_PERSON / f"{name}_{key}.csv.gz"


def uncommitted() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "cliffs2017", "scripts/earnings_changes.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def mismatches(label: str, ours: dict, theirs: dict) -> list[str]:
    return [
        f"{label}.{key}: {ours[key]} here, {theirs[key]} committed"
        for key in HEADLINE
        if not math.isclose(ours[key], theirs[key], rel_tol=TOLERANCE, abs_tol=1e-6)
    ]


def committed_part(year: int, kind: str, parts: int, part: int, seed: int) -> tuple[Path, dict]:
    path = ROOT / "results" / "parts" / f"run_{year}_{kind}_p{parts}_{part}_s{seed}.json"
    return path, json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--parts", type=int, default=4)
    parser.add_argument("--part", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--changes", default=CHANGES)
    parser.add_argument("--todo", action="store_true", help="print how many of the changes aren't written yet, and stop")
    args = parser.parse_args()
    changes = [parse(text) for text in args.changes.split(",")]
    if len({c.key for c in changes}) != len(changes):
        parser.error("a change appears twice")
    todo = [c for c in changes if not change_files(args.year, args.parts, args.part, args.seed, c.key)[0].exists()]
    if args.todo:
        print(len(todo))
        return 0
    if not todo:
        print(f"{args.year} part {args.part}: every change in {args.changes} is done")
        return 0

    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.medicaid import check_totals_match, load_totals
    from cliffs2017.run import load_dataset, source_clusters
    from cliffs2017.simulation import build_simulation

    started = time.time()
    dirty = uncommitted()
    if dirty:
        sys.exit(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    code = dict(code_version(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    health_path, health = committed_part(args.year, "health", args.parts, args.part, args.seed)
    plain_path, plain = committed_part(args.year, "plain", args.parts, args.part, args.seed)
    wanted = dict(
        year=args.year,
        aca_before_2018=args.year < 2018,
        leave_out_csfp=args.year >= 2024,
        parts=args.parts,
        part=args.part,
        seed=args.seed,
    )
    for path, committed in ((health_path, health), (plain_path, plain)):
        for key, value in wanted.items():
            if committed.get(key) != value:
                sys.exit(f"{path}: {key} is {committed.get(key)!r}, not {value!r}")
    versions = {package: metadata.version(package) for package in ("policyengine-us", "policyengine-core")}
    dataset_name = f"{REPO}/{FILENAME}@{REVISION}"
    for path, committed in ((health_path, health), (plain_path, plain)):
        if committed.get("versions") != versions or committed.get("dataset") != dataset_name:
            sys.exit(f"{path} ran {committed.get('versions')} on {committed.get('dataset')}, "
                     f"not {versions} on {dataset_name}")
    totals_file = health["medicaid_totals"]["file"]
    totals, meta = load_totals(ROOT / totals_file)
    if meta["sha256"] != health["medicaid_totals"]["sha256"]:
        sys.exit(f"{totals_file} changed since {health_path} ran")
    check_totals_match(meta, args.year, wanted["aca_before_2018"], dataset_name)

    system = CountryTaxBenefitSystem()
    dataset, _ = load_dataset(args.year, 1.0, args.seed, system, args.parts, args.part)
    sim = build_simulation(
        dataset, args.year, True, wanted["aca_before_2018"], totals, wanted["leave_out_csfp"]
    )
    for path, committed in ((health_path, health), (plain_path, plain)):
        if committed.get("stored_input_renames", {}) != sim.stored_input_renames:
            sys.exit(f"{path} mapped stored inputs {committed.get('stored_input_renames', {})!r}, "
                     f"this run maps {sim.stored_input_renames!r}")
    year = args.year

    def arr(variable, map_to=None):
        return np.asarray(sim.calculate(variable, year, map_to=map_to).values)

    earnings = arr("employment_income") + arr("self_employment_income") + arr("sstb_self_employment_income")
    household_id = arr("household_id", map_to="person")
    person_id = arr("person_id")
    weight = arr("person_weight").astype(np.float64)
    cluster, _ = source_clusters(dataset, household_id)
    people = pd.DataFrame(dict(household_id=household_id, cluster=cluster, weight=weight, worker=earnings > 0))
    health_columns = health_parts(sim, year)
    shared = dict(
        wanted,
        health_benefits_in_net_income=True,
        health_parts=health_columns,
        person_variables=list(PERSON_VARIABLES),
        workers=float(weight[people["worker"].to_numpy()].sum()),
        people_total=float(weight.sum()),
        versions=versions,
        dataset=dataset_name,
        code=code,
        stored_input_renames=sim.stored_input_renames,
    )

    failed = []
    for change in todo:
        t = time.time()
        frame = decompose_change(sim, year, change, PERSON_VARIABLES)
        frame["d_net_without_health"] = without_health(frame, health_columns)
        index = frame["person_index"].to_numpy()
        reached = np.zeros(len(people), dtype=bool)
        reached[index] = True
        entry = dict(
            label=change.label,
            amount=change.amount,
            share=change.share,
            adults_reached=float(weight[reached].sum()),
            workers_reached=float(weight[reached & people["worker"].to_numpy()].sum()),
            sample_adults_reached=int(reached.sum()),
        )
        for name, column in (("without_health", "d_net_without_health"), ("with_health", "d_net_single_ptc")):
            flags = np.zeros(len(people), dtype=bool)
            flags[index] = moves_against(frame["change"], frame[column])
            entry[name] = dict(**headline(people, flags), sample_people_on_cliff=int(flags.sum()))
        reproduces, problems = None, []
        if change.key == BASE:
            problems = mismatches("without_health vs " + plain_path.name, entry["without_health"], plain)
            problems += mismatches(
                "with_health vs " + health_path.name, entry["with_health"], health["premium_tax_credit_counted_once"]
            )
            reproduces = not problems
        json_path, rows_path = change_files(year, args.parts, args.part, args.seed, change.key)
        frame.insert(0, "change_key", change.key)
        frame.insert(1, "person_id", person_id[index])
        frame.insert(2, "household_id", household_id[index])
        frame["weight"] = weight[index]
        frame["worker"] = people["worker"].to_numpy()[index]
        rows_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(rows_path, index=False)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(
            shared,
            key=change.key,
            change=entry,
            reproduces_committed_part=reproduces,
            reproduces=[str(plain_path.relative_to(ROOT)), str(health_path.relative_to(ROOT))] if change.key == BASE else None,
            problems=problems,
            per_person_file=str(rows_path.relative_to(ROOT)),
            seconds=round(time.time() - t, 1),
        )
        # Write to a temporary name and rename, so a stopped run never leaves half a file
        # that a rerun would take as done.
        tmp = json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=1) + "\n")
        tmp.replace(json_path)
        print(f"{change.label}: reached {entry['adults_reached']:,.0f}; "
              f"without health {entry['without_health']['people_on_cliff']:,.0f}, "
              f"with health {entry['with_health']['people_on_cliff']:,.0f} ({record['seconds']} s)", flush=True)
        if problems:
            failed += problems
        del frame
        gc.collect()
    if failed:
        sys.exit("doesn't reproduce the committed parts:\n" + "\n".join(failed))
    print(f"done in {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
