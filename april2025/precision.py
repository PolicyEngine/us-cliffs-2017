"""Sampling precision of the April 2025 counts, as published and with draws held.

Reads attribute_{as_published,draws_held}.csv.gz (person_index = position in
the simulation's person arrays) and resamples the enhanced CPS's households
200 times, as cliffs2017.run.bootstrap does for the current model. Both
variants use the same resampled households in each draw, so the ratio of the
two counts gets an interval too. Also reports how many sample adults and
households carry each count, and the two largest households' share of it.
Writes precision_summary.json.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATASET = (
    "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5"
    "@da98b4faccf44492e91d80c0112a34ef6c3da0bd"
)
YEAR = 2025
DRAWS = 200
LABELS = ("as_published", "draws_held")
NAMES = ["adults_on_cliff", "households_with_adult_on_cliff", "people_in_those_households"]


def household_stats(people: pd.DataFrame, on: np.ndarray) -> tuple[np.ndarray, dict]:
    """Per-household contributions to the three counts, and sample sizes."""
    frame = people.assign(on=on)
    by_household = frame.groupby("household_id", sort=True).agg(
        weight=("weight", "first"), members=("weight", "size"), adults_on=("on", "sum")
    )
    any_on = (by_household["adults_on"] > 0).to_numpy()
    w = by_household["weight"].to_numpy()
    stats = np.column_stack(
        [
            w * by_household["adults_on"].to_numpy(),
            w * any_on,
            w * by_household["members"].to_numpy() * any_on,
        ]
    )
    contribution = np.sort(stats[:, 0])[::-1]
    sizes = dict(
        sample_adults_on_cliff=int(on.sum()),
        sample_households_on_cliff=int(any_on.sum()),
        largest_two_households_share_of_adults=float(contribution[:2].sum() / contribution.sum()),
        kish_effective_households=float(stats[:, 0].sum() ** 2 / (stats[:, 0] ** 2).sum()),
    )
    return stats, sizes


def main():
    from policyengine_us import Microsimulation

    sim = Microsimulation(dataset=DATASET)
    people = pd.DataFrame(
        dict(
            household_id=np.asarray(sim.calculate("household_id", YEAR, map_to="person").values),
            weight=np.asarray(sim.calculate("person_weight", YEAR).values, dtype=np.float64),
        )
    )
    stats, out = {}, {}
    for label in LABELS:
        frame = pd.read_csv(HERE / f"attribute_{label}.csv.gz")
        on = np.zeros(len(people), dtype=bool)
        on[frame.loc[frame["d_net"] < 0, "person_index"].to_numpy()] = True
        stats[label], sizes = household_stats(people, on)
        out[label] = dict(
            estimate={k: float(v) for k, v in zip(NAMES, stats[label].sum(axis=0))}, **sizes
        )
    n = len(stats[LABELS[0]])
    rng = np.random.default_rng(0)
    totals = {label: np.empty((DRAWS, len(NAMES))) for label in LABELS}
    for b in range(DRAWS):
        counts = rng.multinomial(n, np.full(n, 1 / n))
        for label in LABELS:
            totals[label][b] = counts @ stats[label]
    for label in LABELS:
        t = totals[label]
        out[label]["standard_error"] = {k: float(v) for k, v in zip(NAMES, t.std(axis=0, ddof=1))}
        out[label]["interval_95"] = {
            k: [float(lo), float(hi)]
            for k, lo, hi in zip(NAMES, np.percentile(t, 2.5, axis=0), np.percentile(t, 97.5, axis=0))
        }
    ratio = totals["as_published"] / totals["draws_held"]
    out["published_over_held"] = {
        k: dict(
            estimate=float(out["as_published"]["estimate"][k] / out["draws_held"]["estimate"][k]),
            interval_95=[float(np.percentile(ratio[:, i], 2.5)), float(np.percentile(ratio[:, i], 97.5))],
        )
        for i, k in enumerate(NAMES)
    }
    (HERE / "precision_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
