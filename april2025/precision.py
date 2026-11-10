"""Sampling precision of the April 2025 counts, as published and with draws held.

Reads attribute_{as_published,draws_held}.csv.gz (person_index = position in
the simulation's person arrays) and resamples the survey households 5,000
times. The enhanced CPS holds each CPS household twice: the record as
surveyed and a copy whose household_id adds a fixed offset. survey_households
finds the offset and stops unless every copy has the same members, by age, as
its original. A resample draws the two records together, as one survey
household, as cliffs2017.run.bootstrap does with Microcosm's source
households. Both variants use the same resampled households in each draw, so
the ratio of the two counts gets an interval too (a paired ratio: the
published count over the held count in the same resample). With 200 draws
the intervals' ends depended on the random seed, so the script takes 5,000.
Also reports how many sample adults, household records and survey households
carry each count, and the two largest households' share of it.
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
DRAWS = 5_000
LABELS = ("as_published", "draws_held")
NAMES = ["adults_on_cliff", "households_with_adult_on_cliff", "people_in_those_households"]


def survey_households(household_id: np.ndarray, age: np.ndarray) -> tuple[np.ndarray, int]:
    """Map each person's household record to its survey household.

    Returns the survey household of each person (the original record's id)
    and the offset that separates the copies' ids from the originals'.
    """
    ids = np.unique(household_id)
    originals, copies = np.array_split(ids, 2)
    offset = int(copies[0] - originals[0])
    if len(originals) != len(copies) or not np.array_equal(copies - offset, originals):
        raise ValueError("household records do not split into originals and copies")
    people = pd.DataFrame(dict(household_id=household_id, age=age))
    people["survey_household"] = np.where(household_id > originals[-1], household_id - offset, household_id)
    people["is_copy"] = household_id > originals[-1]
    members = people.groupby(["survey_household", "is_copy"])["age"].apply(lambda a: tuple(sorted(a)))
    members = members.unstack("is_copy")
    if not (members[False] == members[True]).all():
        raise ValueError("a copy's members differ from its original's")
    return people["survey_household"].to_numpy(), offset


def household_stats(people: pd.DataFrame, on: np.ndarray) -> tuple[np.ndarray, dict]:
    """Per-survey-household contributions to the three counts, and sample sizes."""
    frame = people.assign(on=on)
    by_household = frame.groupby("household_id", sort=True).agg(
        weight=("weight", "first"),
        members=("weight", "size"),
        adults_on=("on", "sum"),
        survey_household=("survey_household", "first"),
    )
    any_on = (by_household["adults_on"] > 0).to_numpy()
    w = by_household["weight"].to_numpy()
    per_record = np.column_stack(
        [
            w * by_household["adults_on"].to_numpy(),
            w * any_on,
            w * by_household["members"].to_numpy() * any_on,
        ]
    )
    _, survey = np.unique(by_household["survey_household"].to_numpy(), return_inverse=True)
    stats = np.zeros((survey.max() + 1, per_record.shape[1]))
    np.add.at(stats, survey, per_record)
    contribution = np.sort(per_record[:, 0])[::-1]
    sizes = dict(
        sample_adults_on_cliff=int(on.sum()),
        sample_households_on_cliff=int(any_on.sum()),
        sample_survey_households_on_cliff=int(len(np.unique(survey[any_on]))),
        largest_two_households_share_of_adults=float(contribution[:2].sum() / contribution.sum()),
        kish_effective_survey_households=float(stats[:, 0].sum() ** 2 / (stats[:, 0] ** 2).sum()),
    )
    return stats, sizes


def main():
    from policyengine_us import Microsimulation

    sim = Microsimulation(dataset=DATASET)
    household_id = np.asarray(sim.calculate("household_id", YEAR, map_to="person").values)
    survey, offset = survey_households(household_id, np.asarray(sim.calculate("age", YEAR).values))
    people = pd.DataFrame(
        dict(
            household_id=household_id,
            survey_household=survey,
            weight=np.asarray(sim.calculate("person_weight", YEAR).values, dtype=np.float64),
        )
    )
    stats, out = {}, {}
    out["survey_households"] = dict(
        records=int(len(np.unique(household_id))),
        survey_households=int(len(np.unique(survey))),
        copy_id_offset=offset,
    )
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
