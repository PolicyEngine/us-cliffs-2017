"""Why the 17 April 2025 cliff counts exceed today's: test the random redraws.

PolicyEngine-US 1.251.1 measured each adult's marginal tax rate in a branch
simulation (variables/household/marginal_tax_rate.py): it cloned the
simulation, deleted every array that was not a dataset input, raised the
adult's earnings by $1,000 and recomputed household net income. Three
variables in that model draw random numbers when a dataset is loaded:
meets_ssi_resource_test (pass rate 0.4), would_claim_wic and
is_wic_at_nutritional_risk. policyengine-core 3.16.6 seeds each draw with
entity_id * 100 + count_random_calls, and Simulation.clone copies
count_random_calls to the branch, so the branch draws again with different
seeds. A household can then lose (or gain) SSI or WIC in the branch for
reasons unrelated to the raise.

This script replicates the model's branch procedure line for line and runs
it three ways on the same base simulation:

1. as_published: draws recomputed in each branch, as in the April 2025 run;
2. null_raise: the same branch with a $0 raise, where any change in net
   income is spurious;
3. draws_held: the three drawn variables join the simulation's inputs, so
   each branch keeps the base draws (the current model reads such draws from
   the data instead).

For each it records the weighted count of adults whose household net income
falls, their households and everyone in them, plus the change in each
component of net income, and writes attribute_summary.json.
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
DRAWN = ["meets_ssi_resource_test", "would_claim_wic", "is_wic_at_nutritional_risk"]
TAX = "household_tax_before_refundable_credits"
NET = "household_net_income"


def components(sim):
    p = sim.tax_benefit_system.parameters(str(YEAR))
    parts = [("household_market_income", 1), ("household_refundable_tax_credits", 1), (TAX, -1)]
    parts += [(b, 1) for b in p.gov.household.household_benefits]
    return parts


def household_values(sim, variables):
    out = {}
    for v in variables:
        out[v] = np.asarray(
            sim.calculate(v, YEAR, map_to="household").values, dtype=np.float64
        )
    return out


def old_branch(sim, name, increase):
    """The branch of policyengine_us 1.251.1's marginal_tax_rate, line for line."""
    employment_income = sim.calculate("employment_income", YEAR).values
    self_employment_income = sim.calculate("self_employment_income", YEAR).values
    total = employment_income + self_employment_income
    ratio = np.divide(
        employment_income,
        total,
        out=np.ones_like(total, dtype=np.float32),
        where=total > 0,
    )
    alt = sim.get_branch(name)
    for variable in sim.tax_benefit_system.variables:
        if variable not in sim.input_variables or variable == "employment_income":
            alt.delete_arrays(variable)
    alt.set_input("employment_income", YEAR, employment_income + increase * ratio)
    alt.set_input("self_employment_income", YEAR, self_employment_income + increase * (1 - ratio))
    return alt


def measure(sim, base, parts, people, label, delta):
    """Branch for each of the two highest-earning adults; return per-adult changes."""
    names = [n for n, _ in parts] + [NET] + DRAWN_PERSON_SUMS
    rows = []
    for k in (1, 2):
        mask = people["rank"].to_numpy() == k
        name = f"{label}_{k}"
        alt = old_branch(sim, name, mask * delta)
        alt_values = household_values(alt, names)
        del sim.branches[name]
        idx = np.flatnonzero(mask)
        hh = people["household_index"].to_numpy()[idx]
        frame = pd.DataFrame({"person_index": idx, "rank": k})
        for n, sign in parts:
            frame[f"d_{n}"] = sign * (alt_values[n] - base[n])[hh]
        frame["d_net"] = (alt_values[NET] - base[NET])[hh]
        for n in DRAWN_PERSON_SUMS:
            frame[f"d_{n}"] = (alt_values[n] - base[n])[hh]
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


# Household counts of members passing each draw, to see the redraws directly.
DRAWN_PERSON_SUMS = DRAWN


def summarize(frame, people, label):
    on = frame[frame["d_net"] < 0]
    w = people["weight"].to_numpy()
    hh_index = people["household_index"].to_numpy()
    hh_weight = people.groupby("household_index")["weight"].first()
    hh_members = people.groupby("household_index").size()
    on_households = np.unique(hh_index[on["person_index"]])
    parts = [c for c in frame.columns if c.startswith("d_") and c not in (
        "d_net", "d_household_market_income", *[f"d_{n}" for n in DRAWN_PERSON_SUMS])]
    worst = on[parts].idxmin(axis=1).str.removeprefix("d_")
    worst = worst.where(on[parts].min(axis=1) < 0, "none")
    any_redraw = np.zeros(len(on), dtype=bool)
    for n in DRAWN_PERSON_SUMS:
        any_redraw |= on[f"d_{n}"].to_numpy() != 0
    return dict(
        label=label,
        adults_on_cliff=float(w[on["person_index"]].sum()),
        households_with_adult_on_cliff=float(hh_weight.loc[on_households].sum()),
        people_in_those_households=float(
            (hh_weight.loc[on_households] * hh_members.loc[on_households]).sum()
        ),
        sample_adults_on_cliff=int(len(on)),
        adults_on_cliff_whose_household_redrew=float(w[on["person_index"]][any_redraw].sum()),
        adults_on_cliff_by_driver=(
            pd.Series(w[on["person_index"]], index=on.index).groupby(worst).sum()
            .sort_values(ascending=False).to_dict()
        ),
        measured_adults=float(w[frame["person_index"]].sum()),
        measured_adults_whose_household_net_income_changed=float(
            w[frame["person_index"]][frame["d_net"].to_numpy() != 0].sum()
        ),
        measured_adults_whose_household_redrew=float(
            w[frame["person_index"]][
                np.any([frame[f"d_{n}"].to_numpy() != 0 for n in DRAWN_PERSON_SUMS], axis=0)
            ].sum()
        ),
    )


def main():
    from policyengine_us import Microsimulation

    started = time.time()
    sim = Microsimulation(dataset=DATASET)
    parts = components(sim)
    person_household = sim.calculate("household_id", YEAR, map_to="person").values
    household_ids = sim.calculate("household_id", YEAR).values
    position = {h: i for i, h in enumerate(household_ids)}
    people = pd.DataFrame(
        dict(
            household_index=[position[h] for h in person_household],
            weight=sim.calculate("person_weight", YEAR).values,
            rank=sim.calculate("adult_earnings_index", YEAR).values,
        )
    )
    names = [n for n, _ in parts] + [NET] + DRAWN_PERSON_SUMS
    base = household_values(sim, names)
    log = {"random_calls_in_base": int(getattr(sim, "count_random_calls", -1))}

    results = {}
    frames = {}
    for label, delta in (("as_published", 1_000.0), ("null_raise", 0.0)):
        frames[label] = measure(sim, base, parts, people, label, delta)
        results[label] = summarize(frames[label], people, label)
        print(json.dumps(results[label], indent=1), flush=True)

    # Hold the draws: from here on the branches keep the base values.
    sim.input_variables = list(sim.input_variables) + DRAWN
    frames["draws_held"] = measure(sim, base, parts, people, "draws_held", 1_000.0)
    results["draws_held"] = summarize(frames["draws_held"], people, "draws_held")
    print(json.dumps(results["draws_held"], indent=1), flush=True)
    held = frames["draws_held"]
    redraws_left = int(
        np.any([held[f"d_{n}"].to_numpy() != 0 for n in DRAWN_PERSON_SUMS], axis=0).sum()
    )
    log["draws_held_rows_with_any_redraw"] = redraws_left

    summary = dict(
        model="policyengine-us 1.251.1 (c379969db9), policyengine-core 3.16.6",
        dataset=DATASET,
        year=YEAR,
        households=int(len(household_ids)),
        people=int(len(people)),
        **log,
        results=results,
        seconds=round(time.time() - started, 1),
    )
    (HERE / "attribute_summary.json").write_text(json.dumps(summary, indent=1))
    for label, frame in frames.items():
        frame.to_csv(HERE / f"attribute_{label}.csv.gz", index=False)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
