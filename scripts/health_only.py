"""How the count with health coverage relates to the count without it.

Each year has two headline counts of adults facing a cliff: one from net income
without health coverage (the ``plain`` runs) and one that also counts health
coverage, with the premium tax credit counted once (``d_net_single_ptc`` in the
``health`` runs). Both test the same adults, and the health runs' rows carry
every part of net income the plain runs' rows do, plus the health parts.

For each year this script reads the cliff rows of both final runs (all four
parts, results/parts/per_person/) and reports:

- the adults in both counts, the adults only in the count with health coverage
  and the adults only in the count without it;
- for the adults only in the count with health coverage, the change in the rest
  of their household's net income (every part the plain run has) and the change
  in its health parts (with the credit counted once): the smallest and largest
  values and the weighted medians.

An adult only in the count with health coverage isn't on a cliff before health
coverage counts, so the rest of their household's net income doesn't fall with
the raise. An adult only in the count without it is one whose health coverage
gains more than the rest of net income loses.

It stops unless each run's rows reproduce the committed count. The per-person
files are git-ignored record-level output of cliffs2017.run; the output holds
only weighted totals, counts of records and summary statistics. The output
records HEAD, so the script stops if it has uncommitted changes.

usage: python scripts/health_only.py   # writes results/health_only.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "results" / "parts" / "per_person"
OUT = ROOT / "results" / "health_only.json"
YEARS = ("2017", "2025")
# Columns of a per-person file that aren't parts of the change in net income.
NOT_PARTS = ("d_net", "d_parts", "d_net_single_ptc")
# With the premium tax credit counted once, cliffs2017.run leaves out the change in the
# premium net of the credit (cliffs2017.run, premium_tax_credit_counted_once).
PREMIUM_NET_OF_CREDIT = "d_marketplace_net_premium"
# Relative gap allowed between these rows and a committed count, as in scripts/take_up_bounds.py.
TOLERANCE = 1e-9


def parts(rows: pd.DataFrame) -> list[str]:
    return [c for c in rows.columns if c.startswith("d_") and c not in NOT_PARTS]


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """The smallest value at which the weights up to it reach half their total."""
    order = np.argsort(values, kind="stable")
    running = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(running, running[-1] / 2, side="left")])


def compare(plain: pd.DataFrame, health: pd.DataFrame) -> dict:
    """The two counts' overlap, and what moves for the adults only in the count with health coverage.

    ``plain`` and ``health`` hold one row per tested adult on a cliff in either sense; the
    count without health coverage takes ``d_net`` < 0 in ``plain`` and the count with it
    ``d_net_single_ptc`` < 0 in ``health``.
    """
    rest = parts(plain)
    missing = [c for c in rest if c not in health.columns]
    if missing:
        raise ValueError(f"the health rows lack parts the plain rows have: {missing}")
    health_parts = [c for c in parts(health) if c not in rest and c != PREMIUM_NET_OF_CREDIT]
    without = plain[plain["d_net"].to_numpy() < 0]
    with_ = health[health["d_net_single_ptc"].to_numpy() < 0]
    in_both = with_["person_id"].isin(without["person_id"]).to_numpy()
    only_with = with_[~in_both]
    only_without = without[~without["person_id"].isin(with_["person_id"]).to_numpy()]
    out = dict(
        people_on_cliff_with_health_coverage=float(with_["weight"].sum()),
        people_on_cliff_without_health_coverage=float(without["weight"].sum()),
        in_both=dict(people=float(with_["weight"].to_numpy()[in_both].sum()), sample_people=int(in_both.sum())),
        only_with_health_coverage=dict(people=float(only_with["weight"].sum()), sample_people=int(len(only_with))),
        only_without_health_coverage=dict(people=float(only_without["weight"].sum()), sample_people=int(len(only_without))),
    )
    total = out["people_on_cliff_with_health_coverage"]
    out["only_with_health_coverage"]["share_of_count_with_health_coverage"] = (
        out["only_with_health_coverage"]["people"] / total if total else 0.0
    )
    if len(only_with):
        weight = only_with["weight"].to_numpy()
        for name, columns in (("change_in_rest_of_net_income", rest), ("change_in_health_parts", health_parts)):
            change = only_with[columns].sum(axis=1).to_numpy()
            out["only_with_health_coverage"][name] = dict(
                smallest=float(change.min()),
                largest=float(change.max()),
                weighted_median=weighted_median(change, weight),
                sample_people_where_it_falls=int((change < 0).sum()),
                sample_people_where_it_rises=int((change > 0).sum()),
            )
    return out


def check(label: str, ours: float, committed: float) -> None:
    if abs(ours - committed) > TOLERANCE * max(abs(committed), 1.0):
        raise ValueError(f"{label}: rows give {ours:,.6f}, committed run {committed:,.6f}")


def load(run: str) -> pd.DataFrame:
    files = sorted(PARTS.glob(f"run_{run}_p4_*_s0_cliff_parts.csv.gz"))
    if len(files) != 4:
        raise FileNotFoundError(f"{run}: expected 4 part files in {PARTS}, found {len(files)}")
    rows = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    if rows["person_id"].duplicated().any():
        raise ValueError(f"{run}: a person appears in more than one row")
    return rows


def main() -> int:
    # The output records HEAD as its commit, so the script that runs must be the one HEAD holds.
    script = Path(__file__).resolve().relative_to(ROOT)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(script)], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"commit {script} first: the output records HEAD, which doesn't hold this version")
    out = {
        "note": (
            "Adults facing a cliff with and without health coverage counted (the premium "
            "tax credit counted once): how the two counts overlap, and, for the adults "
            "only in the count with health coverage, the change in the rest of their "
            "household's net income and in its health parts after the $1,000 raise."
        ),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "years": {},
    }
    renames, datasets = set(), set()
    for year in YEARS:
        finals = {kind: json.loads((ROOT / "results" / f"final_{year}_{kind}.json").read_text()) for kind in ("plain", "health")}
        for final in finals.values():
            # The finals record the stored inputs they renamed (the WIC take-up draw) and the
            # dataset they read; the output carries both, and the script stops if they differ.
            renames.add(json.dumps(final.get("stored_input_renames"), sort_keys=True))
            datasets.add(final.get("dataset"))
        entry = compare(load(f"{year}_plain"), load(f"{year}_health"))
        check(f"{year} without health coverage", entry["people_on_cliff_without_health_coverage"], finals["plain"]["people_on_cliff"])
        check(
            f"{year} with health coverage",
            entry["people_on_cliff_with_health_coverage"],
            finals["health"]["premium_tax_credit_counted_once"]["people_on_cliff"],
        )
        out["years"][year] = entry
    if len(renames) != 1 or len(datasets) != 1:
        raise ValueError(f"the final runs differ in their stored-input renames or dataset: {sorted(renames)}, {sorted(map(str, datasets))}")
    out["stored_input_renames"] = json.loads(renames.pop())
    out["dataset"] = datasets.pop()
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for year, e in out["years"].items():
        only = e["only_with_health_coverage"]
        print(
            f"{year}: {e['people_on_cliff_with_health_coverage']:,.0f} with health coverage, "
            f"{only['people']:,.0f} only with it ({only['share_of_count_with_health_coverage']:.1%}); "
            f"{e['only_without_health_coverage']['people']:,.0f} only without it"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
