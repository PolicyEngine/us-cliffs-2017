"""Intervals for the counts by largest loss, and how many survey households carry each count.

cliffs2017.run's bootstrap gives standard errors for the headline counts only. The
texts also quote counts by the benefit whose loss lowers net income most
(``people_on_cliff_by_driver``), and some of those rest on a handful of survey
households. For each final run, this script reads the cliff rows in
results/parts/per_person/ (all four parts), assigns each adult's largest loss as
cliffs2017.run does, and maps each adult's household to its source household
(the household table's ``household_source_id``, the unit cliffs2017.run
resamples). It then resamples all of Microcosm's source households 5,000 times,
as april2025/precision.py resamples the April data's survey households, and
uses the same resampled households for every count in a draw. cliffs2017.run
resamples within each part instead; the parts split the source households at
random, so the two schemes estimate the same thing.

Each count gets a standard error and a 95% percentile interval, and its share
of the run's total gets an interval from the same resamples. A count that few
households carry has a skewed distribution, which a percentile interval
follows and 1.96 standard errors either side of the estimate don't: it can
reach below zero. For each count, the script also reports the sample adults
and source households behind it, the fewest source households that supply
half of it, and Kish's effective number of source households (the square of
their total over the sum of their squared totals).

It stops unless the rows reproduce each final run's committed counts, in
total and by largest loss, for the model's own count and, in the runs counting
health coverage, the count with the premium tax credit counted once. The
per-person files are git-ignored record-level output of cliffs2017.run; the
output holds only weighted totals and counts of records. The output records
HEAD, so the script stops if it or cliffs2017/ has uncommitted changes.

usage: python scripts/driver_intervals.py   # writes results/driver_intervals.json
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
sys.path.insert(0, str(ROOT))

from cliffs2017.decompose import primary_driver  # noqa: E402
from cliffs2017.run import FILENAME, REPO, REVISION  # noqa: E402

PARTS = ROOT / "results" / "parts" / "per_person"
OUT = ROOT / "results" / "driver_intervals.json"
RUNS = ("2017_plain", "2017_health", "2025_plain", "2025_health")
DRAWS = 5_000
SEED = 0
# The model's own count, and the count with the premium tax credit counted once
# (cliffs2017.run, premium_tax_credit_counted_once), which only the runs counting
# health coverage change.
CHANGES = {"as_modeled": "d_net", "credit_counted_once": "d_net_single_ptc"}
# Relative gap allowed between these rows and a committed count, as in
# scripts/take_up_bounds.py: summing the same weights in another order moves a
# count by far less.
TOLERANCE = 1e-9


def largest_loss(rows: pd.DataFrame, change: str) -> pd.DataFrame:
    """The rows on a cliff by ``change``, each with its largest loss as cliffs2017.run assigns it.

    With the credit counted once, cliffs2017.run leaves out the change in the
    premium net of the credit, so the credit's own change can be the largest loss.
    """
    on = rows[rows[change].to_numpy() < 0].copy()
    parts = on.drop(columns=["d_marketplace_net_premium"], errors="ignore") if change == "d_net_single_ptc" else on
    on["driver"] = primary_driver(parts).to_numpy()
    return on


def source_index(household_id: np.ndarray, households: pd.DataFrame) -> tuple[np.ndarray, int]:
    """Each row's source household, as an index into the dataset's sorted source households.

    Returns the indices and the number of source households in the dataset.
    """
    source = pd.Series(
        households["household_source_id"].to_numpy(), index=households["household_id"].to_numpy()
    )
    if not source.index.is_unique:
        raise ValueError("the household table repeats a household_id")
    mapped = source.reindex(household_id)
    if mapped.isna().any():
        raise ValueError(f"{int(mapped.isna().sum())} rows' households aren't in the household table")
    sources = np.unique(households["household_source_id"].to_numpy())
    return np.searchsorted(sources, mapped.to_numpy()), len(sources)


def support(totals: np.ndarray, sample_people: int) -> dict:
    """How many source households carry a count, from each one's total of it."""
    held = np.sort(totals[totals > 0])[::-1]
    total = float(held.sum())
    if total == 0:
        return dict(
            sample_people_on_cliff=int(sample_people),
            source_households=0,
            source_households_for_half=0,
            kish_effective_source_households=0.0,
        )
    half = int(np.searchsorted(np.cumsum(held), total / 2, side="left")) + 1
    return dict(
        sample_people_on_cliff=int(sample_people),
        source_households=int(len(held)),
        source_households_for_half=min(half, int(len(held))),
        kish_effective_source_households=float(total**2 / np.square(held).sum()),
    )


def resample(stats: np.ndarray, draws: int, seed: int) -> np.ndarray:
    """Each statistic's total in each of ``draws`` resamples of the source households.

    ``stats`` has one row per source household in the dataset and one column per
    statistic. Each resample draws as many source households as the dataset
    holds, with replacement, as april2025/precision.py does.
    """
    n = len(stats)
    held = np.flatnonzero(np.any(stats != 0, axis=1))
    rng = np.random.default_rng(seed)
    out = np.empty((draws, stats.shape[1]))
    for b in range(draws):
        counts = rng.multinomial(n, np.full(n, 1 / n))
        out[b] = counts[held] @ stats[held]
    return out


def interval(draws: np.ndarray) -> list[float]:
    return [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def check(label: str, ours: float, committed: float) -> None:
    gap = abs(ours - committed)
    if gap > TOLERANCE * max(abs(committed), 1.0):
        raise ValueError(f"{label}: rows give {ours:,.6f}, committed run {committed:,.6f}")


def load(run: str) -> pd.DataFrame:
    files = sorted(PARTS.glob(f"run_{run}_p4_*_s0_cliff_parts.csv.gz"))
    if len(files) != 4:
        raise FileNotFoundError(f"{run}: expected 4 part files in {PARTS}, found {len(files)}")
    rows = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    if rows["person_id"].duplicated().any():
        raise ValueError(f"{run}: a person appears in more than one row")
    return rows


def counts(run: str, rows: pd.DataFrame, final: dict) -> dict[str, pd.DataFrame]:
    """The cliff rows of each count a run reports, checked against the committed run."""
    out = {}
    for key, change in CHANGES.items():
        if key == "credit_counted_once" and not final["health_benefits_in_net_income"]:
            continue
        block = final if key == "as_modeled" else final["premium_tax_credit_counted_once"]
        on = largest_loss(rows, change)
        check(f"{run} {key}", float(on["weight"].sum()), block["people_on_cliff"])
        ours = on.groupby("driver")["weight"].sum()
        committed = block["people_on_cliff_by_driver"]
        if set(ours.index) != set(committed):
            raise ValueError(f"{run} {key}: largest losses {sorted(ours.index)}, committed {sorted(committed)}")
        for driver, value in committed.items():
            check(f"{run} {key} {driver}", float(ours[driver]), value)
        out[key] = on
    return out


def main() -> int:
    # The output records HEAD as its commit, so the code that runs must be the code HEAD holds.
    script = Path(__file__).resolve().relative_to(ROOT)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", str(script), "cliffs2017"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"commit {script} and cliffs2017/ first: the output records HEAD, which doesn't hold this version")
    from huggingface_hub import hf_hub_download

    dataset = f"{REPO}/{FILENAME}@{REVISION}"
    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    households = pd.read_hdf(path, "household", columns=["household_id", "household_source_id"])

    finals, renames, columns, labels, samples = {}, set(), [], [], []
    for run in RUNS:
        final = json.loads((ROOT / "results" / f"final_{run}.json").read_text())
        if final.get("dataset") != dataset:
            raise ValueError(f"{run}: the final run read {final.get('dataset')}, not {dataset}")
        # The finals record the stored inputs they renamed (the WIC take-up draw); the
        # intervals carry that record, and stop if the runs they read differ in it.
        renames.add(json.dumps(final.get("stored_input_renames"), sort_keys=True))
        finals[run] = final
        for key, on in counts(run, load(run), final).items():
            index, n = source_index(on["household_id"].to_numpy(), households)
            weight = on["weight"].to_numpy()
            columns.append(np.bincount(index, weights=weight, minlength=n))
            labels.append((run, key, None))
            samples.append(len(on))
            for driver in sorted(set(on["driver"])):
                mine = on["driver"].to_numpy() == driver
                columns.append(np.bincount(index[mine], weights=weight[mine], minlength=n))
                labels.append((run, key, driver))
                samples.append(int(mine.sum()))
    if len(renames) != 1:
        raise ValueError(f"the final runs differ in the stored inputs they renamed: {sorted(renames)}")
    stats = np.column_stack(columns)
    draws = resample(stats, DRAWS, SEED)

    out = {
        "note": (
            "Counts of adults facing a cliff, in total and by the benefit whose loss "
            "lowers net income most, with 95% percentile intervals from resampling "
            "Microcosm's source households, and the source households that carry "
            "each count. Sampling error only."
        ),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset": dataset,
        "stored_input_renames": json.loads(renames.pop()),
        "draws": DRAWS,
        "seed": SEED,
        "source_households_in_dataset": int(len(stats)),
        "runs": {},
    }
    total_column = {}
    for j, (run, key, driver) in enumerate(labels):
        estimate = float(stats[:, j].sum())
        entry = dict(
            people_on_cliff=estimate,
            standard_error=float(draws[:, j].std(ddof=1)),
            interval_95=interval(draws[:, j]),
            **support(stats[:, j], samples[j]),
        )
        if driver is None:
            total_column[(run, key)] = j
            committed = finals[run] if key == "as_modeled" else finals[run]["premium_tax_credit_counted_once"]
            entry["committed_standard_error"] = committed["standard_errors"]["people_on_cliff"]
            entry["by_largest_loss"] = {}
            out["runs"].setdefault(run, {})[key] = entry
            continue
        t = total_column[(run, key)]
        entry["share"] = estimate / float(stats[:, t].sum())
        entry["share_interval_95"] = interval(draws[:, j] / draws[:, t])
        out["runs"][run][key]["by_largest_loss"][driver] = entry
    for block in (b for r in out["runs"].values() for b in r.values()):
        block["by_largest_loss"] = dict(
            sorted(block["by_largest_loss"].items(), key=lambda kv: -kv[1]["people_on_cliff"])
        )
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for run, entry in out["runs"].items():
        for key, b in entry.items():
            lo, hi = b["interval_95"]
            print(f"{run} {key}: {b['people_on_cliff']:,.0f} ({lo:,.0f} to {hi:,.0f}); "
                  f"{b['source_households']} source households, {b['source_households_for_half']} supply half, "
                  f"Kish {b['kish_effective_source_households']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
