"""Recompute the 17 April 2025 national cliff counts with that day's model and data.

Model: PolicyEngine-US 1.251.1 (main at c379969db9, 2025-04-16 23:31 UTC), on
policyengine-core 3.16.6. Data: enhanced_cps_2024.h5 at Hugging Face revision
da98b4fa (uploaded 2025-04-01, the last upload before 17 April 2025).
Method as in the April 2025 analysis: weighted sums of is_on_cliff for 2025,
households with anyone on a cliff, and household_size of those households.

Writes repro_summary.json and repro_on_cliff_people.csv beside this file.
"""

import json
import sys
import time
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

    started = time.time()
    sim = Microsimulation(dataset=DATASET)

    def arr(variable, map_to=None):
        return np.asarray(sim.calculate(variable, YEAR, map_to=map_to).values)

    weight = arr("person_weight")
    on_cliff = arr("is_on_cliff").astype(bool)
    household_id = arr("household_id", map_to="person")
    earnings = arr("employment_income") + arr("self_employment_income")
    mtr = arr("marginal_tax_rate")
    gap = arr("cliff_gap")
    people = pd.DataFrame(
        dict(
            household_id=household_id,
            person_id=arr("person_id"),
            weight=weight,
            on_cliff=on_cliff,
            earnings=earnings,
            mtr=mtr,
            gap=gap,
            age=arr("age"),
            is_adult=arr("is_adult").astype(bool),
        )
    )
    by_household = people.groupby("household_id").agg(
        weight=("weight", "first"),
        members=("weight", "size"),
        any_on_cliff=("on_cliff", "any"),
    )
    on_hh = by_household[by_household.any_on_cliff]
    summary = dict(
        model="policyengine-us 1.251.1 (c379969db9)",
        dataset=DATASET,
        year=YEAR,
        people_on_cliff=float(weight[on_cliff].sum()),
        workers_on_cliff=float(weight[on_cliff & (earnings > 0)].sum()),
        households_with_person_on_cliff=float(on_hh["weight"].sum()),
        people_in_those_households=float((on_hh["weight"] * on_hh["members"]).sum()),
        sample_people_on_cliff=int(on_cliff.sum()),
        sample_households_on_cliff=int(len(on_hh)),
        people_total=float(weight.sum()),
        mtr_above_one_share=float(weight[mtr > 1].sum() / weight.sum()),
        seconds=round(time.time() - started, 1),
    )
    for variable in ["snap", "tanf", "eitc", "aca_ptc", "medicaid", "household_net_income"]:
        try:
            summary[f"total_{variable}"] = float(sim.calculate(variable, YEAR).sum())
        except Exception as error:
            summary[f"total_{variable}"] = f"error: {error}"[:160]
    people[people.on_cliff].to_csv(HERE / "repro_on_cliff_people.csv", index=False)
    (HERE / "repro_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    sys.exit(main())
