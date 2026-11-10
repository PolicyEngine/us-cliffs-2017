"""Full-sample state totals for Medicaid's value per enrollee.

PolicyEngine-US values Medicaid at government cost: ``medicaid_cost_if_enrolled``
spreads each state's spending (``calibration.gov.hhs.medicaid.totals.spending``)
over the state's enrollees in proportion to a cost index. Two formulas behind
it sum over every person in the simulation, not over one household:

- ``medicaid_slcsp_state_average_cost_index``, the person-weighted mean of the
  positive cost indices in each state, which stands in for an index of 0;
- ``medicaid_slcsp_state_denominator``, the person-weighted sum of that filled
  index over each state's enrollees. Over a dataset with a reform, it reads
  the simulation's baseline branch, which runs the unreformed policy.

So one household's Medicaid value depends on which other households the run
holds. A run over one of four disjoint parts, at full weight, finds about a
quarter of each state's denominator and so about four times each enrollee's
value. A small subsample finds a noisy denominator: in a 2% subsample, where
each state's sum covers only the few enrollees the subsample holds, the model
valued some enrollees' Medicaid at billions of dollars. And under the pre-2018
premium tax credit reform
(cliffs2017.aca2017), the cost index comes from the reform while the
denominator comes from the unreformed policy.

This module computes both totals for the full sample, from per-state sums over
disjoint parts that add exactly, and builds a reform that replaces the two
formulas with lookups of those totals by state. Each household's Medicaid
value then depends only on its own records and its state, whatever part or
subsample holds it, and every branch of a simulation reads the same totals.

Usage, once per health configuration, before its health runs:
  python -m cliffs2017.medicaid sums --year 2017 --aca-before-2018 --parts 4 \\
      --part 0 --out results/medicaid/sums_2017_p4_0_s0.json      # each part
  python -m cliffs2017.medicaid combine --out results/medicaid/totals_2017_p4_s0.json \\
      results/medicaid/sums_2017_p4_*_s0.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd

AGGREGATES = (
    "medicaid_slcsp_state_average_cost_index",
    "medicaid_slcsp_state_denominator",
)
# Per-state sums over people; each adds across disjoint sets of households.
SUM_COLUMNS = [
    "positive_index_weight",  # sum of weight where the cost index is positive
    "positive_index_total",  # sum of weight * index where the index is positive
    "enrolled_positive_index_total",  # the same, over enrollees
    "enrolled_zero_index_weight",  # sum of weight over enrollees with index 0
    "enrolled_weight",  # sum of weight over enrollees
    "people",  # sample records
    "enrolled_people",  # sample records enrolled
]
# What the totals must agree on to combine, and with the run that uses them.
CONFIGURATION_KEYS = ("year", "aca_before_2018", "dataset", "versions")


def sums_from_arrays(state, weight, cost_index, enrolled) -> pd.DataFrame:
    """Per-state sums (one row per state) behind the two totals."""
    state = np.asarray(state).astype(str)
    weight = np.asarray(weight, dtype=np.float64)
    cost_index = np.asarray(cost_index, dtype=np.float64)
    enrolled = np.asarray(enrolled, dtype=bool)
    positive = cost_index > 0
    frame = pd.DataFrame(
        {
            "state": state,
            "positive_index_weight": weight * positive,
            "positive_index_total": weight * cost_index * positive,
            "enrolled_positive_index_total": weight * cost_index * (positive & enrolled),
            "enrolled_zero_index_weight": weight * (~positive & enrolled),
            "enrolled_weight": weight * enrolled,
            "people": np.ones(len(state), dtype=np.int64),
            "enrolled_people": enrolled.astype(np.int64),
        }
    )
    return frame.groupby("state").sum()[SUM_COLUMNS].sort_index()


def add_sums(frames) -> pd.DataFrame:
    """Sums over the union of disjoint parts."""
    return pd.concat(list(frames)).groupby(level=0).sum()[SUM_COLUMNS].sort_index()


def totals_from_sums(sums: pd.DataFrame) -> pd.DataFrame:
    """The two totals PolicyEngine-US's formulas compute, from the per-state sums.

    ``average_cost_index`` follows ``medicaid_slcsp_state_average_cost_index``
    (1 for a state with no positive index), and ``denominator`` follows
    ``medicaid_slcsp_state_denominator``: enrollees with a positive index count
    it, and enrollees with an index of 0 count the state average, as
    ``medicaid_slcsp_cost_index_filled`` does.
    """
    weight = sums["positive_index_weight"].to_numpy(dtype=np.float64)
    average = np.divide(
        sums["positive_index_total"].to_numpy(dtype=np.float64),
        weight,
        out=np.ones(len(sums)),
        where=weight > 0,
    )
    denominator = (
        sums["enrolled_positive_index_total"].to_numpy(dtype=np.float64)
        + average * sums["enrolled_zero_index_weight"].to_numpy(dtype=np.float64)
    )
    return sums.assign(average_cost_index=average, denominator=denominator)


def simulation_sums(sim, year: int) -> pd.DataFrame:
    """Per-state sums for one simulation, under its own policy.

    Fails if gathering the inputs computed either total: the sums must not
    depend on what they feed.
    """

    def arr(variable, map_to=None):
        return np.asarray(sim.calculate(variable, year, map_to=map_to).values)

    sums = sums_from_arrays(
        arr("state_code_str", map_to="person"),
        arr("person_weight"),
        arr("medicaid_slcsp_cost_index"),
        arr("medicaid_enrolled"),
    )
    for name in AGGREGATES:
        if sim.get_holder(name).get_known_periods():
            raise RuntimeError(f"{name} was computed while gathering its own inputs")
    return sums


def fixed_state_totals(totals: pd.DataFrame, year: int):
    """A reform whose two state totals are lookups in ``totals`` (indexed by state code).

    The lookups serve ``year`` only and fail for a state missing from
    ``totals``, so a run can't silently fall back to the model's own sums.
    """
    from policyengine_core.reforms import Reform
    from policyengine_us.model_api import USD, YEAR, Person, Variable

    def lookup(values: dict, name: str):
        def formula(person, period, parameters):
            if period.start.year != year:
                raise ValueError(f"{name}: the full-sample totals cover {year}, not {period}")
            state = pd.Series(np.asarray(person.household("state_code_str", period)).astype(str))
            out = state.map(values)
            if out.isna().any():
                missing = sorted(state[out.isna()].unique())
                raise KeyError(f"{name}: no full-sample total for {missing}")
            return out.to_numpy(dtype=np.float64)

        return formula

    average = {str(k): float(v) for k, v in totals["average_cost_index"].items()}
    denominator = {str(k): float(v) for k, v in totals["denominator"].items()}

    class medicaid_slcsp_state_average_cost_index(Variable):
        value_type = float
        entity = Person
        label = "Average Medicaid SLCSP cost index in each state (full-sample total)"
        unit = USD
        definition_period = YEAR
        formula = lookup(average, "medicaid_slcsp_state_average_cost_index")

    class medicaid_slcsp_state_denominator(Variable):
        value_type = float
        entity = Person
        label = "Medicaid SLCSP state allocation denominator (full-sample total)"
        unit = USD
        definition_period = YEAR
        formula = lookup(denominator, "medicaid_slcsp_state_denominator")

    class FixedMedicaidStateTotals(Reform):
        def apply(self):
            self.replace_variable(medicaid_slcsp_state_average_cost_index)
            self.replace_variable(medicaid_slcsp_state_denominator)

    return FixedMedicaidStateTotals


def state_spending(system, year: int, states) -> pd.Series:
    """Each state's Medicaid spending in ``year`` as the model reads it."""
    spending = system.parameters(f"{year}-01-01").calibration.gov.hhs.medicaid.totals.spending
    return pd.Series({state: float(spending[state]) for state in states}, dtype=np.float64)


def _versions() -> dict:
    return {p: metadata.version(p) for p in ("policyengine-us", "policyengine-core")}


def _frame_to_json(frame: pd.DataFrame) -> dict:
    return {
        state: {k: (int(v) if isinstance(v, (int, np.integer)) else float(v)) for k, v in row.items()}
        for state, row in frame.iterrows()
    }


def _frame_from_json(states: dict) -> pd.DataFrame:
    frame = pd.DataFrame.from_dict(states, orient="index").sort_index()
    frame.index.name = "state"
    return frame


def load_totals(path) -> tuple[pd.DataFrame, dict]:
    """(totals by state, the file's metadata) from a ``combine`` output."""
    data = json.loads(Path(path).read_text())
    if data.get("kind") != "medicaid_state_totals":
        raise ValueError(f"{path} is not a Medicaid state totals file")
    meta = {k: v for k, v in data.items() if k != "states"}
    meta["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return _frame_from_json(data["states"]), meta


def check_totals_match(meta: dict, year: int, aca_before_2018: bool, dataset: str) -> None:
    """Fail unless a totals file describes this run's configuration."""
    expected = dict(year=year, aca_before_2018=aca_before_2018, dataset=dataset, versions=_versions())
    wrong = {k: (meta.get(k), v) for k, v in expected.items() if meta.get(k) != v}
    if wrong:
        raise ValueError(f"Medicaid totals don't match this run: {wrong}")


def main_sums(args) -> None:
    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.run import FILENAME, REPO, REVISION, load_dataset
    from cliffs2017.simulation import build_simulation

    started = time.time()
    system = CountryTaxBenefitSystem()
    dataset, _ = load_dataset(args.year, args.fraction, args.seed, system, args.parts, args.part)
    sim = build_simulation(dataset, args.year, health=True, aca_before_2018=args.aca_before_2018)
    sums = simulation_sums(sim, args.year)
    out = dict(
        kind="medicaid_state_sums",
        year=args.year,
        aca_before_2018=args.aca_before_2018,
        parts=args.parts,
        part=args.part,
        fraction=args.fraction,
        seed=args.seed,
        dataset=f"{REPO}/{FILENAME}@{REVISION}",
        versions=_versions(),
        seconds=round(time.time() - started, 1),
        states=_frame_to_json(sums),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{args.out}: {len(sums)} states, {int(sums['people'].sum())} people")


def main_combine(args) -> None:
    from policyengine_us import CountryTaxBenefitSystem

    parts = [json.loads(Path(p).read_text()) for p in args.sums]
    first = parts[0]
    for part in parts:
        if part.get("kind") != "medicaid_state_sums":
            raise ValueError("combine takes the outputs of `sums`")
        for key in CONFIGURATION_KEYS + ("parts", "seed", "fraction"):
            if part[key] != first[key]:
                raise ValueError(f"parts disagree on {key}: {part[key]} vs {first[key]}")
    if first["fraction"] != 1.0:
        raise ValueError("full-sample totals need the full sample's parts, not a subsample")
    indices = sorted(part["part"] for part in parts)
    if indices != list(range(first["parts"])):
        raise ValueError(f"need parts 0..{first['parts'] - 1} once each, got {indices}")
    totals = totals_from_sums(add_sums(_frame_from_json(p["states"]) for p in parts))
    spending = state_spending(CountryTaxBenefitSystem(), first["year"], totals.index)
    totals = totals.assign(
        spending=spending,
        spending_per_enrollee=np.divide(
            spending.to_numpy(),
            totals["enrolled_weight"].to_numpy(),
            out=np.zeros(len(totals)),
            where=totals["enrolled_weight"].to_numpy() > 0,
        ),
    )
    funded = totals["denominator"] > 0
    out = dict(
        kind="medicaid_state_totals",
        **{k: first[k] for k in CONFIGURATION_KEYS},
        parts=first["parts"],
        seed=first["seed"],
        sums_files=[str(p) for p in args.sums],
        states_with_enrollees=int(funded.sum()),
        # medicaid_cost over the full sample adds to this exactly: each state's
        # spending, for every state with enrollees.
        spending_total=float(totals.loc[funded, "spending"].sum()),
        enrolled_weight_total=float(totals["enrolled_weight"].sum()),
        states=_frame_to_json(totals),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(
        f"{args.out}: {len(totals)} states; spending ${out['spending_total'] / 1e9:,.1f}B over "
        f"{out['enrolled_weight_total'] / 1e6:,.1f}M enrollees"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    sums = commands.add_parser("sums", help="per-state sums for one part")
    sums.add_argument("--year", type=int, required=True)
    sums.add_argument("--aca-before-2018", action="store_true")
    sums.add_argument("--fraction", type=float, default=1.0)
    sums.add_argument("--parts", type=int, default=1)
    sums.add_argument("--part", type=int, default=0)
    sums.add_argument("--seed", type=int, default=0)
    sums.add_argument("--out", required=True)
    combine = commands.add_parser("combine", help="full-sample totals from every part's sums")
    combine.add_argument("--out", required=True)
    combine.add_argument("sums", nargs="+")
    args = parser.parse_args()
    if args.command == "sums":
        if args.parts > 1 and args.fraction < 1:
            parser.error("use --fraction or --parts, not both")
        main_sums(args)
    else:
        main_combine(args)


if __name__ == "__main__":
    main()
