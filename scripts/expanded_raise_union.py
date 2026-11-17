"""Recount saved raises as finite-grid retention unions using MicroSeries.

This script does not rerun tax or benefit counterfactuals. It reads saved
person-level resource changes from the frozen historical experiment, verifies
record identities and all strict-cliff totals against the committed part
metadata, and loads that experiment's entity mapping for weighted aggregation.
Stored CSV weights are never read. PolicyEngine's MicroSeries derives weights
from the calibrated household source and maps household flags to residents.

The preliminary population is current workers among the two adults per
household ranked highest by market income. The finite grid is $1k/$2k/$5k;
its union makes no claim about other raise sizes or a continuous earnings path.

Run from the expanded-analysis checkout with its historical environment:
  uv run --no-sync python scripts/expanded_raise_union.py --source-root ...
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd
from policyengine_core.periods import YEAR
from policyengine_core.variables import Variable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHANGES = {"raise_1000": 1000.0, "raise_2000": 2000.0, "raise_5000": 5000.0}
THRESHOLDS = {
    "retains_lt_60pct": 0.60,
    "retains_lt_50pct": 0.50,
    "retains_lt_20pct": 0.20,
    "retains_lt_0pct": 0.0,
}
MEASURES = {"with_health": "d_net_single_ptc", "without_health": "d_net_without_health"}
CSV_COLUMNS = [
    "person_index",
    "person_id",
    "household_id",
    "rank",
    "change",
    "worker",
    *MEASURES.values(),
]
BASELINE_KEYS = {
    "adults": "people_on_cliff",
    "households": "households_with_person_on_cliff",
    "household_members": "people_in_those_households",
}


def sha256(path: Path) -> str:
    """Hash an input artifact without interpreting its record-level fields."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retention_flags(
    change, delta_resources, threshold: float, eligible=None
) -> np.ndarray:
    """Strict retention test on stored, unweighted counterfactual changes."""
    change = np.asarray(change, dtype=float)
    delta_resources = np.asarray(delta_resources, dtype=float)
    if change.shape != delta_resources.shape:
        raise ValueError("earnings and resource changes must have the same shape")
    if not np.isfinite(change).all() or not np.isfinite(delta_resources).all():
        raise ValueError("saved changes must be finite")
    if (change <= 0).any():
        raise ValueError("the raise union requires strictly positive earnings changes")
    flags = delta_resources / change < threshold
    if eligible is not None:
        eligible = np.asarray(eligible, dtype=bool)
        if eligible.shape != change.shape:
            raise ValueError("the eligibility mask must align with saved changes")
        flags &= eligible
    return flags


def validate_rows(
    frame: pd.DataFrame, person_table: pd.DataFrame, amount: float
) -> None:
    """Reject missing, duplicated, reordered or inconsistent record identities."""
    missing = set(CSV_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"saved rows lack {sorted(missing)}")
    if frame.empty:
        raise ValueError("saved raise has no tested adults")
    indices = frame["person_index"]
    if not np.issubdtype(indices.dtype, np.integer):
        raise ValueError("person_index must contain integers")
    if indices.duplicated().any() or frame["person_id"].duplicated().any():
        raise ValueError("saved raise repeats a person")
    if (indices < 0).any() or (indices >= len(person_table)).any():
        raise ValueError("person_index falls outside the source population")
    expected = person_table.iloc[indices]
    if not np.array_equal(frame["person_id"], expected["person_id"]):
        raise ValueError("person IDs do not match the historical person ordering")
    if not np.array_equal(frame["household_id"], expected["person_household_id"]):
        raise ValueError("household IDs do not match the historical entity mapping")
    if not frame["rank"].isin([1, 2]).all():
        raise ValueError("saved rows exceed the top-two adult selection")
    if not np.allclose(frame["change"], amount, rtol=0, atol=1e-9):
        raise ValueError("saved raise size differs from its declared amount")
    if not frame["worker"].isin([True, False]).all():
        raise ValueError("saved worker flag is not boolean")
    for column in MEASURES.values():
        retention_flags(frame["change"], frame[column], 0)


def validate_same_universe(frames: dict[str, pd.DataFrame]) -> None:
    """Require all positive dollar raises to test exactly the same adults."""
    columns = ["person_index", "person_id", "household_id", "rank", "worker"]
    baseline = (
        frames["raise_1000"][columns].sort_values("person_index").reset_index(drop=True)
    )
    for key, frame in frames.items():
        other = frame[columns].sort_values("person_index").reset_index(drop=True)
        if not baseline.equals(other):
            raise ValueError(f"{key} changes the tested population or worker selection")


def household_formula(person_name: str):
    """Build a household union without exporting a weighted result array."""

    def formula(household, period, parameters):
        return household.any(household.members(person_name, period))

    return formula


def household_combination(left: str, right: str, operation: str):
    """Build a household intersection or left-only set."""
    if operation not in {"intersection", "left_only"}:
        raise ValueError("unsupported household set operation")

    def formula(household, period, parameters):
        a = household(left, period)
        b = household(right, period)
        return a & (b if operation == "intersection" else ~b)

    return formula


def add_variable(simulation, name: str, entity: str, formula=None) -> None:
    """Register an analysis-only boolean variable in this simulation."""
    attributes = {
        "value_type": bool,
        "entity": simulation.populations[entity].entity,
        "definition_period": YEAR,
        "label": name.replace("_", " "),
    }
    if formula is not None:
        attributes["formula"] = formula
    simulation.tax_benefit_system.add_variable(type(name, (Variable,), attributes))


def set_person_flag(simulation, name: str, flags: np.ndarray, year: int) -> str:
    """Set an unweighted person input and define its household union."""
    add_variable(simulation, name, "person")
    simulation.set_input(name, year, flags)
    household_name = name + "_household"
    add_variable(simulation, household_name, "household", household_formula(name))
    return household_name


def flag_counts(simulation, person_name: str, household_name: str, year: int) -> dict:
    """Count adults, unique households and residents using MicroSeries only."""
    return {
        "adults": simulation.calc(person_name, period=year).sum(),
        "households": simulation.calc(household_name, period=year).sum(),
        "household_members": simulation.calc(
            household_name, period=year, map_to="person"
        ).sum(),
    }


def household_counts(
    simulation, household_name: str, year: int, adult_name=None
) -> dict:
    """Count a disjoint household set and optionally its qualifying adults."""
    out = {
        "households": simulation.calc(household_name, period=year).sum(),
        "household_members": simulation.calc(
            household_name, period=year, map_to="person"
        ).sum(),
    }
    if adult_name is not None:
        out["adults"] = (
            simulation.calc(adult_name, period=year)
            * simulation.calc(household_name, period=year, map_to="person")
        ).sum()
    return out


def assert_counts_match(actual: dict, expected: dict, label: str) -> None:
    """Stop if mapped MicroSeries totals fail the frozen experiment's totals."""
    for ours, theirs in BASELINE_KEYS.items():
        if not math.isclose(actual[ours], expected[theirs], rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(
                f"{label}.{ours}: {actual[ours]} differs from {expected[theirs]}"
            )


def assert_scalar_match(actual, expected, label: str) -> None:
    """Validate a mapped worker total against the saved experiment metadata."""
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError(f"{label}: {actual} differs from {expected}")


def full_mask(frame: pd.DataFrame, flags: np.ndarray, people: int) -> np.ndarray:
    """Place unweighted saved person flags in the historical population order."""
    out = np.zeros(people, dtype=bool)
    out[frame["person_index"]] = flags
    return out


def summarize_part(simulation, person_table, frames, records, year: int) -> dict:
    """Recount one disjoint source-household part; no economic formulas run."""
    validate_same_universe(frames)
    metrics = {}
    baselines = {}
    masks = {}
    names = {}
    people = len(person_table)
    worker_names = {}
    worker_validation = {}
    for key, frame in frames.items():
        worker_name = f"expanded_{key}_workers_reached"
        worker_flags = full_mask(frame, frame["worker"].to_numpy(dtype=bool), people)
        set_person_flag(simulation, worker_name, worker_flags, year)
        workers_reached = simulation.calc(worker_name, period=year).sum()
        assert_scalar_match(
            workers_reached,
            records[key]["change"]["workers_reached"],
            f"{key}.workers_reached",
        )
        worker_names[key] = worker_name
        worker_validation[key] = {"workers_reached": workers_reached}
    for measure, delta in MEASURES.items():
        masks[measure] = {}
        for key, frame in frames.items():
            base_name = f"expanded_{measure}_{key}_original_strict"
            baseline = full_mask(
                frame, retention_flags(frame["change"], frame[delta], 0), people
            )
            household = set_person_flag(simulation, base_name, baseline, year)
            counts = flag_counts(simulation, base_name, household, year)
            assert_counts_match(
                counts, records[key]["change"][measure], f"{key}.{measure}"
            )
            workers_on_cliff = (
                simulation.calc(base_name, period=year)
                * simulation.calc(worker_names[key], period=year)
            ).sum()
            assert_scalar_match(
                workers_on_cliff,
                records[key]["change"][measure]["workers_on_cliff"],
                f"{key}.{measure}.workers_on_cliff",
            )
            worker_validation[key][measure + "_workers_on_cliff"] = workers_on_cliff
            baselines[f"{measure}.{key}"] = counts
            if key == "raise_1000":
                names[measure + ".original_household"] = household
            masks[measure][key] = {}
            for threshold, value in THRESHOLDS.items():
                flag = full_mask(
                    frame,
                    retention_flags(
                        frame["change"], frame[delta], value, frame["worker"]
                    ),
                    people,
                )
                name = f"expanded_{measure}_{key}_{threshold}"
                household = set_person_flag(simulation, name, flag, year)
                metrics[f"{measure}.{key}.{threshold}"] = flag_counts(
                    simulation, name, household, year
                )
                masks[measure][key][threshold] = flag
        for threshold in THRESHOLDS:
            flags = np.logical_or.reduce(
                [masks[measure][key][threshold] for key in CHANGES]
            )
            name = f"expanded_{measure}_union_{threshold}"
            household = set_person_flag(simulation, name, flags, year)
            metrics[f"{measure}.union.{threshold}"] = flag_counts(
                simulation, name, household, year
            )
            names[f"{measure}.{threshold}.person"] = name
            names[f"{measure}.{threshold}.household"] = household

        half = names[f"{measure}.retains_lt_50pct.household"]
        strict = names[f"{measure}.retains_lt_0pct.household"]
        original = names[measure + ".original_household"]
        half_person = names[f"{measure}.retains_lt_50pct.person"]
        for label, left, right, operation, adult_name in (
            (
                "additional_below_half_excluding_strict",
                half,
                strict,
                "left_only",
                half_person,
            ),
            ("original_1000_in_union_below_half", original, half, "intersection", None),
            (
                "original_1000_outside_union_below_half",
                original,
                half,
                "left_only",
                None,
            ),
            (
                "union_below_half_outside_original_1000",
                half,
                original,
                "left_only",
                half_person,
            ),
            ("original_1000_in_union_strict", original, strict, "intersection", None),
            ("original_1000_outside_union_strict", original, strict, "left_only", None),
        ):
            name = f"expanded_{measure}_{label}"
            add_variable(
                simulation,
                name,
                "household",
                household_combination(left, right, operation),
            )
            metrics[f"{measure}.{label}"] = household_counts(
                simulation, name, year, adult_name
            )

        half_count = metrics[f"{measure}.union.retains_lt_50pct"]
        strict_count = metrics[f"{measure}.union.retains_lt_0pct"]
        extra = metrics[f"{measure}.additional_below_half_excluding_strict"]
        for field in ("households", "household_members"):
            if not math.isclose(
                half_count[field],
                strict_count[field] + extra[field],
                rel_tol=1e-12,
                abs_tol=1e-6,
            ):
                raise ValueError(
                    f"{measure}: disjoint strict and additional {field} do not add to union"
                )
    return {
        "metrics": metrics,
        "original_all_adults_strict": baselines,
        "worker_validation": worker_validation,
    }


def add_part_totals(parts: list[dict], key: str) -> dict:
    """Combine already weighted totals from disjoint population parts."""
    expected = {name: set(counts) for name, counts in parts[0][key].items()}
    for part in parts[1:]:
        actual = {name: set(counts) for name, counts in part[key].items()}
        if actual != expected:
            raise ValueError("population parts have inconsistent result keys")
    return {
        name: {field: sum(part[key][name][field] for part in parts) for field in fields}
        for name, fields in expected.items()
    }


def historical_part(year: int, parts: int, part: int, seed: int):
    """Load the frozen experiment's mapping without computing policy outputs.

    The latest wrapper rejects this intentionally older country-model version
    at certification. Reproducing saved historical output uses the existing
    adapter and its pinned model, explicitly recorded as unmanaged. This path
    is not a new current-law analysis or a certification bypass.
    """
    from scripts.expanded_historical import (
        build_historical_simulation,
        load_historical_dataset,
    )

    dataset = load_historical_dataset(year, parts=parts, part=part, seed=seed)
    simulation = build_historical_simulation(dataset, year, health=False)
    if simulation.populations["person"].count != len(dataset.person):
        raise ValueError(
            "simulation and historical dataset have different population sizes"
        )
    return dataset, simulation


def load_part_records(
    source: Path, year: int, parts: int, part: int, seed: int, person_table
):
    """Load and validate provenance, identities and the saved earnings grid."""
    frames, records, inputs = {}, {}, []
    common = None
    for key, amount in CHANGES.items():
        stem = f"changes_{year}_p{parts}_{part}_s{seed}"
        path = source / "results" / "earnings_changes" / "parts" / stem / f"{key}.json"
        record = json.loads(path.read_text())
        for field, expected in {
            "year": year,
            "parts": parts,
            "part": part,
            "seed": seed,
        }.items():
            if record[field] != expected:
                raise ValueError(f"{path}: unexpected {field}")
        if record["key"] != key or record["problems"]:
            raise ValueError(f"{path}: failed or mismatched source result")
        if key == "raise_1000" and record["reproduces_committed_part"] is not True:
            raise ValueError(f"{path}: source raise did not reproduce original results")
        for package, version in record["versions"].items():
            if metadata.version(package) != version:
                raise ValueError(
                    f"historical {package} pin differs from the source experiment"
                )
        shared = {
            field: record[field]
            for field in ("dataset", "versions", "stored_input_renames")
        }
        shared["code_hashes"] = {
            name: value for name, value in record["code"].items() if name != "commit"
        }
        if common is not None and shared != common:
            raise ValueError("saved raises within a part have different provenance")
        common = shared
        csv = source / record["per_person_file"]
        if not csv.resolve().is_relative_to(source.resolve()):
            raise ValueError(
                "record-level output escapes the explicitly supplied source checkout"
            )
        frame = pd.read_csv(csv, usecols=CSV_COLUMNS)
        validate_rows(frame, person_table, amount)
        if len(frame) != record["change"]["sample_adults_reached"]:
            raise ValueError(f"{path}: saved rows omit or add tested adults")
        frames[key], records[key] = frame, record
        inputs.append(
            {
                "metadata_file": str(path),
                "metadata_sha256": sha256(path),
                "rows_file": str(csv),
                "rows_sha256": sha256(csv),
            }
        )
    from scripts.earnings_changes_summary import check_code

    check_code(year, list(records.values()))
    return frames, records, inputs


def main() -> int:
    from scripts.expanded_historical import historical_provenance

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--year", type=int, choices=[2017], default=2017)
    parser.add_argument("--parts", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "results" / "expanded_raise_union_2017.json"
    )
    args = parser.parse_args()
    source = args.source_root.resolve()
    results, inputs = [], []
    for part in range(args.parts):
        dataset, simulation = historical_part(args.year, args.parts, part, args.seed)
        frames, records, provenance = load_part_records(
            source, args.year, args.parts, part, args.seed, dataset.person
        )
        result = summarize_part(simulation, dataset.person, frames, records, args.year)
        results.append(dict(part=part, **result))
        inputs.extend(provenance)
        print(
            f"part {part}: strict totals reproduced, retention and household unions counted",
            flush=True,
        )
        del dataset, simulation, frames, records
        gc.collect()
    out = {
        "status": "preliminary_selected_worker_subset",
        "year": args.year,
        "raises": list(CHANGES.values()),
        "thresholds": THRESHOLDS,
        "population": "Current workers among up to two adults per household ranked highest by market income; worker means positive wages plus both signed self-employment income components.",
        "scope": "Finite union over $1,000, $2,000 and $5,000 raises to one adult at a time. No claim about untested adults, other sizes, a continuous earnings interval, job entry, or childcare expenses.",
        "additional_group": "Households below 50% retention for at least one tested raise, excluding every household with negative retention for any tested raise; residents counted once.",
        "health_measure": "Government-valued health coverage, with ACA PTC counted once, marketplace net-premium changes excluded and CHIP premiums retained.",
        "uncertainty": "Point estimates only; no new sampling intervals for unions have been calculated.",
        "aggregation": "MicroSeries.sum with household boolean unions and map_to='person'; saved CSV weight columns are not read.",
        "runtime": {
            "mode": "unmanaged_frozen_historical_output_postprocessing",
            "historical_loader": historical_provenance(),
            "versions": {
                p: metadata.version(p)
                for p in ("policyengine-us", "policyengine-core", "microdf-python")
            },
        },
        "code": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "script_sha256": sha256(Path(__file__)),
        },
        "inputs": inputs,
        "metrics": add_part_totals(results, "metrics"),
        "original_all_adults_strict": add_part_totals(
            results, "original_all_adults_strict"
        ),
        "worker_validation": add_part_totals(results, "worker_validation"),
        "parts": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
