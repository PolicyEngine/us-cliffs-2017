"""Worker shares behind the 17 April 2025 figures, as published and with draws held.

Reads attribute_{as_published,draws_held}.csv.gz (person_index = position in
the simulation's person arrays, the same order every run) and recomputes the
weighted share of workers whose household net income falls with $1,000 more
earnings, under several denominators, to identify the published 3.5%.
Writes workers_summary.json.
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


def main():
    from policyengine_us import Microsimulation

    sim = Microsimulation(dataset=DATASET)
    v = lambda name: np.asarray(sim.calculate(name, YEAR).values, dtype=np.float64)
    weight = v("person_weight")
    earnings = v("employment_income") + v("self_employment_income")
    employment = v("employment_income")
    age = v("age")
    adult = np.asarray(sim.calculate("is_adult", YEAR).values).astype(bool)
    rank = v("adult_earnings_index")
    worker = earnings > 0
    denominators = dict(
        people=weight.sum(),
        adults=weight[adult].sum(),
        measured_adults=weight[adult & (rank <= 2) & (rank >= 1)].sum(),
        workers=weight[worker].sum(),
        wage_earners=weight[employment > 0].sum(),
        workers_18_64=weight[worker & (age >= 18) & (age < 65)].sum(),
        measured_workers=weight[worker & adult & (rank <= 2) & (rank >= 1)].sum(),
    )
    out = dict(denominators=denominators, variants={})
    for label in ("as_published", "draws_held"):
        frame = pd.read_csv(HERE / f"attribute_{label}.csv.gz")
        on = frame.loc[frame["d_net"] < 0, "person_index"].to_numpy()
        numerators = dict(
            adults_on_cliff=weight[on].sum(),
            workers_on_cliff=weight[on][worker[on]].sum(),
            wage_earners_on_cliff=weight[on][employment[on] > 0].sum(),
        )
        shares = {
            f"{n}/{d}": numerators[n] / denominators[d]
            for n in numerators
            for d in denominators
        }
        out["variants"][label] = dict(numerators=numerators, shares=shares)
    (HERE / "workers_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
