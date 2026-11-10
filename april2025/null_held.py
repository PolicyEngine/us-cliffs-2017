"""The zero test: with the three draws held, a $0 raise should move no one's net income.

Uses attribute.py's line-for-line replica of the April 2025 cliff test, holds
meets_ssi_resource_test, would_claim_wic and is_wic_at_nutritional_risk at
their base values as attribute.py's draws_held run does, and raises earnings
by $0. Any adult whose household net income still changes would point to a
source of spurious change other than the three draws. Writes
null_held_summary.json.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import attribute

HERE = Path(__file__).parent


def main():
    from policyengine_us import Microsimulation

    sim = Microsimulation(dataset=attribute.DATASET)
    year = attribute.YEAR
    parts = attribute.components(sim)
    person_household = sim.calculate("household_id", year, map_to="person").values
    household_ids = sim.calculate("household_id", year).values
    position = {h: i for i, h in enumerate(household_ids)}
    people = pd.DataFrame(
        dict(
            household_index=[position[h] for h in person_household],
            weight=sim.calculate("person_weight", year).values,
            rank=sim.calculate("adult_earnings_index", year).values,
        )
    )
    names = [n for n, _ in parts] + [attribute.NET] + attribute.DRAWN_PERSON_SUMS
    base = attribute.household_values(sim, names)
    sim.input_variables = list(sim.input_variables) + attribute.DRAWN
    frame = attribute.measure(sim, base, parts, people, "null_held", 0.0)
    result = attribute.summarize(frame, people, "null_held")
    change = frame["d_net"].to_numpy()
    result.update(
        rows=int(len(frame)),
        rows_with_any_net_income_change=int((change != 0).sum()),
        largest_absolute_net_income_change=float(np.abs(change).max()),
    )
    (HERE / "null_held_summary.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
