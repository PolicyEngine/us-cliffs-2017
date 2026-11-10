"""National tax-benefit cliff counts for one year, with or without health coverage.

A person "faces a cliff" when PolicyEngine-US's ``is_on_cliff`` is true: their
household's net income would fall if their earnings rose by
``simulation.marginal_tax_rate_delta`` ($1,000). The model evaluates this for
up to ``simulation.marginal_tax_rate_adults`` (two) adults per household, the
highest earners.

With ``--health``, the run turns on
``gov.simulation.include_health_benefits_in_net_income``, so household net
income also counts Medicaid, CHIP, ACA premium tax credits and the state
health programs listed in ``gov.household.household_health_benefits`` (valued
at government cost) and subtracts the health costs in
``gov.household.household_health_costs``.

With ``--decompose``, the run also breaks each measured adult's change in net
income into its parts (cliffs2017.decompose), counts people on a cliff by the
part that lowers their net income most, and repeats the headline counts with
the premium tax credit counted once.

Standard errors come from a bootstrap that resamples source households:
Microcosm holds some survey households twice (cliffs2017.run.source_clusters),
and the two records of one household are drawn together.

The full sample does not fit in the memory ceiling of one run, so final runs
split households into disjoint parts (``--parts 4 --part i``, at full weight)
and cliffs2017.combine adds the parts up. One part's households interact with
the others in the model only through Medicaid's two state totals
(cliffs2017.medicaid), so a run with health coverage counted takes those
totals for the full sample from ``--medicaid-totals``; with them, the sum of
the parts equals a single full-sample run.

Usage:
  python -m cliffs2017.run --year 2017 [--health] [--aca-before-2018]
      [--leave-out-csfp] [--decompose] [--fraction 0.05 | --parts 4 --part 0]
      [--medicaid-totals results/medicaid/totals_2017_p4_s0.json] --out results/x.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

from cliffs2017.deflate import deflate, partition, subsample

ROOT = Path(__file__).resolve().parents[1]

REPO = "policyengine/populace-us"
FILENAME = "populace_us_2024.h5"
REVISION = "populace-us-2024-spm-20260909"
BOOTSTRAP_DRAWS = 200
# Medicaid's value scales with the state spending it spreads, which the model
# holds for 2020-2023 only; these factors show how far that moves the counts.
MEDICAID_SCALES = (0.8, 0.9, 1.1, 1.2)

# Program totals reported beside the cliff counts, to compare a year's run
# with that year's administrative totals.
PROGRAM_TOTALS = [
    "snap",
    "ssi",
    "tanf",
    "wic",
    "free_school_meals",
    "reduced_price_school_meals",
    "eitc",
    "refundable_ctc",
    "aca_ptc",
    "assigned_aca_ptc",
    "medicaid_cost",
    "chip",
    "housing_assistance",
    "household_head_start_benefits",
    "household_state_benefits",
    "household_benefits",
    "household_net_income",
]
PROGRAM_PEOPLE = {
    "snap": "spm_unit",
    "ssi": "person",
    "tanf": "spm_unit",
    "medicaid_enrolled": "person",
    "chip_enrolled": "person",
    "aca_ptc": "tax_unit",
    "assigned_aca_ptc": "tax_unit",
}


def load_dataset(year: int, fraction: float, seed: int, system, parts: int = 1, part: int = 0):
    from policyengine_us.data.dataset_schema import USSingleYearDataset

    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    dataset = USSingleYearDataset(path)
    if parts > 1:
        dataset = partition(dataset, parts, part, seed)
    elif fraction < 1:
        dataset = subsample(dataset, fraction, seed)
    factors = None
    if year < int(dataset.time_period):
        dataset, factors = deflate(dataset, system, year)
    return dataset, factors


def source_clusters(dataset, household_id_by_person: np.ndarray) -> tuple[np.ndarray, str]:
    """Each person's source household, the unit the bootstrap resamples.

    Microcosm holds some survey households twice: the record as surveyed
    (``household_support_channel`` "asec") and a clone labelled
    "puf_tax_detail", with the same people under the same
    ``household_source_id`` and its own weight. The two records aren't
    independent draws, so they share a cluster. Datasets without the column
    cluster by household.
    """
    table = dataset.household
    if "household_source_id" not in table:
        return household_id_by_person, "household_id"
    source = pd.Series(
        table["household_source_id"].to_numpy(), index=table["household_id"].to_numpy()
    )
    clusters = source.reindex(household_id_by_person).to_numpy()
    if pd.isna(clusters).any():
        raise ValueError("some people's households have no household_source_id")
    return clusters, "household_source_id"


def code_version() -> dict:
    """The commit and a hash of the code that computes the results (cliffs2017/)."""
    digest = hashlib.sha256()
    for path in sorted((ROOT / "cliffs2017").rglob("*")):
        if path.is_file() and path.suffix in (".py", ".csv"):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    try:
        commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return dict(commit=commit, cliffs2017_sha256=digest.hexdigest())


def headline(people: pd.DataFrame, on_cliff: np.ndarray) -> dict[str, float]:
    """People on a cliff, their households, and everyone in those households."""
    frame = people.assign(on_cliff=on_cliff)
    by_household = frame.groupby("household_id").agg(
        weight=("weight", "first"),
        members=("weight", "size"),
        any_on_cliff=("on_cliff", "any"),
    )
    on_hh = by_household[by_household.any_on_cliff]
    return dict(
        people_on_cliff=float(frame.weight[frame.on_cliff].sum()),
        workers_on_cliff=float(frame.weight[frame.on_cliff & frame.worker].sum()),
        households_with_person_on_cliff=float(on_hh["weight"].sum()),
        people_in_those_households=float((on_hh["weight"] * on_hh["members"]).sum()),
    )


def bootstrap(people: pd.DataFrame, on_cliff: np.ndarray, draws: int, seed: int = 0):
    """Standard errors of the headline counts from resampling source households.

    A ``cluster`` column in ``people`` (source_clusters) groups households
    that are drawn together; without it, each household is its own cluster.
    """
    if "cluster" not in people:
        people = people.assign(cluster=people["household_id"].to_numpy())
    frame = people.assign(on_cliff=on_cliff, worker_on=on_cliff & people["worker"].to_numpy())
    by_household = frame.groupby("household_id").agg(
        cluster=("cluster", "first"),
        weight=("weight", "first"),
        members=("weight", "size"),
        people_on=("on_cliff", "sum"),
        workers_on=("worker_on", "sum"),
        any_on=("on_cliff", "any"),
    )
    w = by_household["weight"].to_numpy()
    household_stats = np.column_stack(
        [
            w * by_household["people_on"].to_numpy(),
            w * by_household["workers_on"].to_numpy(),
            w * by_household["any_on"].to_numpy(),
            w * by_household["members"].to_numpy() * by_household["any_on"].to_numpy(),
        ]
    )
    # Each statistic summed within a cluster.
    _, cluster_index = np.unique(by_household["cluster"].to_numpy(), return_inverse=True)
    stats = np.zeros((cluster_index.max() + 1 if len(cluster_index) else 0, 4))
    np.add.at(stats, cluster_index, household_stats)
    names = [
        "people_on_cliff",
        "workers_on_cliff",
        "households_with_person_on_cliff",
        "people_in_those_households",
    ]
    n = len(stats)
    if n == 0:
        return {name: 0.0 for name in names}
    rng = np.random.default_rng(seed)
    totals = np.empty((draws, stats.shape[1]))
    for b in range(draws):
        counts = rng.multinomial(n, np.full(n, 1 / n))
        totals[b] = counts @ stats
    return {name: float(se) for name, se in zip(names, totals.std(axis=0, ddof=1))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--health", action="store_true")
    parser.add_argument(
        "--aca-before-2018",
        action="store_true",
        help="Apply cliffs2017.aca2017.ACABefore2018 (premium tax credit before 2018).",
    )
    parser.add_argument(
        "--leave-out-csfp",
        action="store_true",
        help="Leave the Commodity Supplemental Food Program out of household benefits (cliffs2017.benefits).",
    )
    parser.add_argument("--decompose", action="store_true")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--parts", type=int, default=1)
    parser.add_argument("--part", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--medicaid-totals",
        help="Full-sample Medicaid state totals from cliffs2017.medicaid (required with --health).",
    )
    args = parser.parse_args()
    if args.parts > 1 and args.fraction < 1:
        parser.error("use --fraction or --parts, not both")
    if args.health and not args.medicaid_totals:
        parser.error("--health needs --medicaid-totals; see cliffs2017/medicaid.py")

    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.simulation import build_simulation

    started = time.time()
    system = CountryTaxBenefitSystem()
    dataset, factors = load_dataset(
        args.year, args.fraction, args.seed, system, args.parts, args.part
    )
    medicaid_totals = medicaid_meta = None
    if args.health:
        from cliffs2017.medicaid import check_totals_match, load_totals

        medicaid_totals, medicaid_meta = load_totals(args.medicaid_totals)
        check_totals_match(
            medicaid_meta, args.year, args.aca_before_2018, f"{REPO}/{FILENAME}@{REVISION}"
        )
    sim = build_simulation(
        dataset, args.year, args.health, args.aca_before_2018, medicaid_totals, args.leave_out_csfp
    )
    year = args.year
    loaded = time.time()

    def arr(variable, map_to=None):
        return np.asarray(sim.calculate(variable, year, map_to=map_to).values)

    weight = arr("person_weight").astype(np.float64)
    household_id = arr("household_id", map_to="person")
    person_id = arr("person_id")
    on_cliff = arr("is_on_cliff").astype(bool)
    evaluated = arr("cliff_evaluated").astype(bool)
    gap = arr("cliff_gap")
    # The model's earnings: wages and both kinds of self-employment income
    # (emp_self_emp_ratio, earnings_increments).
    earnings = (
        arr("employment_income")
        + arr("self_employment_income")
        + arr("sstb_self_employment_income")
    )
    worker = earnings > 0
    cluster, cluster_unit = source_clusters(dataset, household_id)
    cliffs_done = time.time()

    people = pd.DataFrame(
        dict(
            household_id=household_id,
            cluster=cluster,
            weight=weight,
            worker=worker,
            evaluated=evaluated,
        )
    )
    result = dict(
        year=year,
        health_benefits_in_net_income=args.health,
        aca_before_2018=args.aca_before_2018,
        leave_out_csfp=args.leave_out_csfp,
        decompose=args.decompose,
        bootstrap_clusters=cluster_unit,
        fraction=args.fraction,
        parts=args.parts,
        part=args.part,
        seed=args.seed,
        people_total=float(weight.sum()),
        households_total=float(people.groupby("household_id").weight.first().sum()),
        workers=float(weight[worker].sum()),
        workers_evaluated=float(weight[worker & evaluated].sum()),
        **headline(people, on_cliff),
        mean_cliff_gap_on_cliff=float(
            np.average(gap[on_cliff], weights=weight[on_cliff]) if on_cliff.any() else 0
        ),
        cliff_gap_total=float((gap * weight)[on_cliff].sum()),
        sample_people_on_cliff=int(on_cliff.sum()),
        sample_households=int(people.household_id.nunique()),
        sample_clusters=int(pd.unique(cluster).size),
    )
    result["share_of_workers_on_cliff"] = result["workers_on_cliff"] / result["workers"]
    result["standard_errors"] = bootstrap(people, on_cliff, BOOTSTRAP_DRAWS)

    if args.decompose:
        from cliffs2017.decompose import decompose, primary_driver

        parts = decompose(sim, year)
        index = parts["person_index"].to_numpy()
        # The breakdown must reproduce the model's own cliff flags.
        flagged = np.zeros_like(on_cliff)
        flagged[index] = parts["d_net"].to_numpy() < 0
        result["decomposition_flag_mismatches"] = int((flagged != on_cliff).sum())
        single = np.zeros_like(on_cliff)
        single[index] = parts["d_net_single_ptc"].to_numpy() < 0
        result["premium_tax_credit_counted_once"] = dict(
            **headline(people, single),
            standard_errors=bootstrap(people, single, BOOTSTRAP_DRAWS),
            sample_people_on_cliff=int(single.sum()),
        )
        cliff_rows = parts[parts["d_net"] < 0].copy()
        cliff_rows["weight"] = weight[cliff_rows["person_index"]]
        cliff_rows["driver"] = primary_driver(cliff_rows)
        result["people_on_cliff_by_driver"] = (
            cliff_rows.groupby("driver")["weight"].sum().sort_values(ascending=False).to_dict()
        )
        single_rows = parts[parts["d_net_single_ptc"] < 0].copy()
        single_rows["weight"] = weight[single_rows["person_index"]]
        single_rows["driver"] = primary_driver(single_rows.drop(columns=["d_marketplace_net_premium"], errors="ignore"))
        result["premium_tax_credit_counted_once"]["people_on_cliff_by_driver"] = (
            single_rows.groupby("driver")["weight"].sum().sort_values(ascending=False).to_dict()
        )
        if "d_medicaid_cost" in parts:
            # Every Medicaid value moves with its state's spending, so scaling
            # spending by f adds (f - 1) times the Medicaid change to d_net.
            result["medicaid_value_scaled"] = {}
            for scale in MEDICAID_SCALES:
                moved = np.zeros_like(on_cliff)
                moved[index] = (
                    parts["d_net"] + (scale - 1) * parts["d_medicaid_cost"]
                ).to_numpy() < 0
                result["medicaid_value_scaled"][f"{scale:g}"] = headline(people, moved)
        # Record-level model output stays out of git (results/per_person/).
        detail = Path(args.out).parent / "per_person" / (
            Path(args.out).stem + "_cliff_parts.csv.gz"
        )
        detail.parent.mkdir(parents=True, exist_ok=True)
        keep = parts[(parts["d_net"] < 0) | (parts["d_net_single_ptc"] < 0)].copy()
        keep.insert(0, "person_id", person_id[keep["person_index"]])
        keep.insert(1, "household_id", household_id[keep["person_index"]])
        keep["weight"] = weight[keep["person_index"]]
        keep.to_csv(detail, index=False)
        result["cliff_parts_file"] = str(detail)

    from policyengine_core.errors import VariableNotFoundError

    totals = {}
    for variable in PROGRAM_TOTALS:
        try:
            totals[variable] = float(sim.calculate(variable, year).sum())
        except VariableNotFoundError as error:  # missing from this model version
            totals[variable] = f"error: {type(error).__name__}: {error}"[:200]
    recipients = {}
    for variable, entity in PROGRAM_PEOPLE.items():
        try:
            value = arr(variable, map_to="person")
            recipients[variable] = float(weight[value > 0].sum())
        except VariableNotFoundError as error:
            recipients[variable] = f"error: {type(error).__name__}: {error}"[:200]
    result["program_totals"] = totals
    result["people_in_recipient_units"] = recipients
    result["timing_seconds"] = dict(
        load=round(loaded - started, 1),
        cliffs=round(cliffs_done - loaded, 1),
        total=round(time.time() - started, 1),
    )
    result["versions"] = {
        package: metadata.version(package)
        for package in ("policyengine-us", "policyengine-core")
    }
    result["dataset"] = f"{REPO}/{FILENAME}@{REVISION}"
    result["code"] = code_version()
    if medicaid_meta is not None:
        result["medicaid_totals"] = dict(
            file=args.medicaid_totals,
            sha256=medicaid_meta["sha256"],
            parts=medicaid_meta["parts"],
            states_with_enrollees=medicaid_meta["states_with_enrollees"],
            spending_total=medicaid_meta["spending_total"],
            enrolled_weight_total=medicaid_meta["enrolled_weight_total"],
        )
    result["python"] = platform.python_version()
    if factors is not None:
        result["deflation"] = (
            factors.groupby("index")
            .agg(columns=("column", "size"), factor=("factor", "first"))
            .reset_index()
            .to_dict(orient="records")
        )
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k not in ("program_totals",)}, indent=1))


if __name__ == "__main__":
    main()
