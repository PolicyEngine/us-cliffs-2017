"""Check that attribute.py's parts add up to each change in net income.

attribute.py breaks each measured adult's change in household net income into
the parts PolicyEngine-US 1.251.1 adds up: market income, refundable credits,
taxes before refundable credits and each benefit. The model stores those
values in float32, which keeps 24 significant bits, so a household's dollar
amounts sit on a grid of 1/16 of a dollar near $1 million and $8 near $100
million. The parts and net income each round to that grid, so their changes
can disagree by a few grid steps in high-income households.

This script reads attribute.py's per-person files and each household's market
income and net income from the same base simulation, and reports for each
variant:
- how many rows miss by more than a cent and by more than a dollar, and the
  largest miss;
- each miss in grid steps at the household's scale (np.spacing of the
  float32 value of the larger of market income and net income, plus the
  size of every change, so the scale covers the amounts both before and
  after the raise), and how many rows exceed 2 x (number of parts + 1)
  steps, more than rounding the parts and net income can produce;
- for adults on a cliff, how many miss by more than a dollar, and how many
  could change which part lowers net income most (the largest loss leads the
  second-largest by no more than the miss).

The cliff flag reads the model's own change in net income, so a miss never
changes a count. Writes identity_summary.json.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import attribute

HERE = Path(__file__).parent
LABELS = ("as_published", "null_raise", "draws_held")


def main():
    from policyengine_us import Microsimulation

    year = attribute.YEAR
    sim = Microsimulation(dataset=attribute.DATASET)
    person_household = np.asarray(sim.calculate("household_id", year, map_to="person").values)
    household_ids = np.asarray(sim.calculate("household_id", year).values)
    position = pd.Series(np.arange(len(household_ids)), index=household_ids)
    household_index = position.loc[person_household].to_numpy()
    weight = np.asarray(sim.calculate("person_weight", year).values, dtype=np.float64)
    scale = np.maximum.reduce(
        [
            np.abs(np.asarray(sim.calculate(v, year).values, dtype=np.float64))
            for v in ("household_market_income", attribute.NET)
        ]
    )
    out = dict(
        model="policyengine-us 1.251.1 (c379969db9), policyengine-core 3.16.6",
        dataset=attribute.DATASET,
        year=year,
    )
    for label in LABELS:
        frame = pd.read_csv(HERE / f"attribute_{label}.csv.gz")
        parts = [
            c
            for c in frame.columns
            if c.startswith("d_") and c != "d_net" and c[2:] not in attribute.DRAWN
        ]
        person = frame["person_index"].to_numpy()
        miss = (frame["d_net"] - frame[parts].sum(axis=1)).abs().to_numpy()
        size = scale[household_index[person]] + frame[parts + ["d_net"]].abs().sum(axis=1).to_numpy()
        steps = miss / np.spacing(np.maximum(size, 1.0).astype(np.float32)).astype(np.float64)
        # The parts attribute.summarize ranks to name the largest loss.
        losses = frame[[c for c in parts if c != "d_household_market_income"]].to_numpy()
        ranked = np.sort(losses, axis=1)
        largest_loss = -ranked[:, 0]
        lead = ranked[:, 1] - ranked[:, 0]
        on = frame["d_net"].to_numpy() < 0
        big = on & (miss > 1)
        could_change = on & (largest_loss > 0) & (miss > 0.01) & (lead <= miss)
        out[label] = dict(
            rows=int(len(frame)),
            parts=len(parts),
            rows_missing_by_over_1_cent=int((miss > 0.01).sum()),
            rows_missing_by_over_1_dollar=int((miss > 1).sum()),
            largest_miss=float(miss.max()),
            largest_miss_in_float32_steps=float(steps.max()),
            rows_over_rounding_bound=int((steps > 2 * (len(parts) + 1)).sum()),
            cliff_rows=int(on.sum()),
            cliff_rows_missing_by_over_1_dollar=int(big.sum()),
            smallest_loss_in_those_rows=(
                float(-frame["d_net"].to_numpy()[big].max()) if big.any() else None
            ),
            cliff_rows_where_miss_could_change_largest_loss=int(could_change.sum()),
            adults_on_cliff_where_miss_could_change_largest_loss=float(
                weight[person[could_change]].sum()
            ),
        )
    (HERE / "identity_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
