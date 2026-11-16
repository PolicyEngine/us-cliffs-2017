"""Count people in households that trip the raise test, the job test, or either, under 2017 rules.

Two tests, each changing one adult at a time and holding the rest of the household fixed:

- raise: a current worker among the household's two highest-earning adults gets a
  $1,000, $2,000 or $5,000 raise (the saved raise experiment, as
  scripts/expanded_raise_union.py reads it);
- job: a working-age adult with no earnings takes a full-time job at the state's
  2017 minimum wage (the national job-entry rows, scripts/expanded_job_entry_national.py).

A household trips a test at threshold t when any tested adult's household keeps less
than t of the gross change: the change in household resources divided by the gross
pay change, strictly below t, for t in 0.6, 0.5, 0.2 and 0. The test sets are each
raise, the raise union, the job test, the combined union (three raises and the job)
and combined_1000 ($1,000 raise and the job). For every set, threshold and resource
measure (with and without health coverage, as the raise union defines them) the
counts are households, flagged adults and household members.

For each set the strict-loss group is the households below 0% on any test in the set,
the additional group is the households below 50% on any test in the set, excluding
every household below 0% on any test in the set, and the below-half total is their
union. Each is measured directly as its own household set; none is a difference of
counts. Residents are counted once through ``map_to="person"``.

No tax or benefit formula runs. Each household part's frozen historical simulation
supplies only the entity mapping and the calibrated weights, inside MicroSeries;
stored weight columns are never read. Per-source-household totals for the bootstrap
come from MicroSeries ``groupby(...).sum()`` on the same flags. The intervals
resample all source households jointly, with the same draw for every count, as
scripts/driver_intervals.py does.

Each part's run asserts the invariants (threshold nesting, unions containing their
components, the strict and additional groups partitioning the below-half union,
each person counted once, adding a test never lowering the strict or below-half
union), reproduces the job runner's per-rank totals, and recounts with the job rows
emptied, which must reproduce results/expanded_raise_union_2017.json.

usage (the parts run on Modal, scripts/modal_combined_union.py):
  python scripts/expanded_combined_union.py combine --digest DIGEST [--draws 5000 --seed 0]
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import resource
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import combined_union_inputs as inputs  # noqa: E402
from scripts.expanded_raise_union import (  # noqa: E402
    CHANGES,
    CSV_COLUMNS,
    MEASURES,
    THRESHOLDS,
    add_variable,
    assert_counts_match,
    assert_scalar_match,
    flag_counts,
    full_mask,
    household_combination,
    household_counts,
    retention_flags,
    set_person_flag,
    validate_rows,
    validate_same_universe,
)

YEAR = 2017
RAISES = tuple(CHANGES)
JOB = "job"
SETS = {
    "raise_1000": ("raise_1000",),
    "raise_2000": ("raise_2000",),
    "raise_5000": ("raise_5000",),
    "raise_union": RAISES,
    "job": (JOB,),
    "combined": (*RAISES, JOB),
    "combined_1000": ("raise_1000", JOB),
}
HEADLINE_BASES = ("combined", "combined_1000")
# Each base's raise-only counterpart, for the households only the job test adds.
JOB_INCREMENT = {"combined": "raise_union", "combined_1000": "raise_1000"}
OVERLAP_BASES = ("raise_union", "combined", "combined_1000")
STRICT = "retains_lt_0pct"
HALF = "retains_lt_50pct"
NESTED = ("retains_lt_0pct", "retains_lt_20pct", "retains_lt_50pct", "retains_lt_60pct")
LEVELS = {"strict": STRICT, "below_half": HALF}
FIELDS = ("adults", "households", "household_members")
# Adding a test never lowers a union: (smaller, larger) set pairs.
GROWS = (
    ("raise_1000", "raise_union"), ("raise_2000", "raise_union"), ("raise_5000", "raise_union"),
    ("raise_union", "combined"), ("job", "combined"), ("raise_1000", "combined_1000"),
    ("job", "combined_1000"), ("combined_1000", "combined"),
)
JOB_COLUMNS = ["person_index", "person_id", "household_id", "state_code", "rank", "gross_pay",
               *MEASURES.values()]
HOURS_PER_YEAR = 2080
DRAWS = 5_000
BOOTSTRAP_SEED = 0
TOLERANCE = 1e-9  # relative, as scripts/driver_intervals.py and the raise runner allow


# ---------------------------------------------------------------------------
# Rows


def load_raise_part(files: dict, part: int, person_table: pd.DataFrame) -> tuple[dict, dict]:
    """The saved raises of one part, checked as scripts/expanded_raise_union.py checks them.

    The commit check (earnings_changes_summary.check_code) needs git, so the local
    combine step runs it.
    """
    frames, records, common = {}, {}, None
    for key, amount in CHANGES.items():
        record = json.loads(files[inputs.raise_metadata_rel(part, key)])
        for field, expected in {"year": YEAR, "parts": inputs.PARTS, "part": part,
                                "seed": inputs.SEED}.items():
            if record[field] != expected:
                raise ValueError(f"part {part} {key}: unexpected {field}")
        if record["key"] != key or record["problems"]:
            raise ValueError(f"part {part} {key}: failed or mismatched source result")
        if key == "raise_1000" and record["reproduces_committed_part"] is not True:
            raise ValueError(f"part {part}: source raise did not reproduce original results")
        for package, version in record["versions"].items():
            if metadata.version(package) != version:
                raise ValueError(f"historical {package} pin differs from the source experiment")
        shared = {field: record[field] for field in ("dataset", "versions", "stored_input_renames")}
        shared["code_hashes"] = {n: v for n, v in record["code"].items() if n != "commit"}
        if common is not None and shared != common:
            raise ValueError("saved raises within a part have different provenance")
        common = shared
        frame = pd.read_csv(io.BytesIO(files[record["per_person_file"]]), compression="gzip",
                            usecols=CSV_COLUMNS)
        validate_rows(frame, person_table, amount)
        if len(frame) != record["change"]["sample_adults_reached"]:
            raise ValueError(f"part {part} {key}: saved rows omit or add tested adults")
        frames[key], records[key] = frame, record
    validate_same_universe(frames)
    return frames, records


def validate_job_rows(frame: pd.DataFrame, person_table: pd.DataFrame, rates: dict) -> None:
    """Reject repeated people, wrong identities, unknown states and pay off the wage table."""
    missing = set(JOB_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"job rows lack {sorted(missing)}")
    if frame.empty:
        return
    indices = frame["person_index"]
    if not np.issubdtype(indices.dtype, np.integer):
        raise ValueError("person_index must contain integers")
    if indices.duplicated().any() or frame["person_id"].duplicated().any():
        raise ValueError("job rows repeat a person across ranks or scopes")
    if (indices < 0).any() or (indices >= len(person_table)).any():
        raise ValueError("person_index falls outside the source population")
    expected = person_table.iloc[indices]
    if not np.array_equal(frame["person_id"], expected["person_id"]):
        raise ValueError("job person IDs do not match the historical person ordering")
    if not np.array_equal(frame["household_id"], expected["person_household_id"]):
        raise ValueError("job household IDs do not match the historical entity mapping")
    if frame.duplicated(["rank", "household_id"]).any():
        raise ValueError("a job rank tests two adults in one household")
    unknown = set(frame["state_code"]) - set(rates)
    if unknown:
        raise ValueError(f"job rows in states without a recorded rate: {sorted(unknown)}")
    pay = frame["state_code"].map(rates).to_numpy(dtype=float) * HOURS_PER_YEAR
    if not np.allclose(frame["gross_pay"].to_numpy(dtype=float), pay, rtol=0, atol=1e-6):
        raise ValueError("job gross pay differs from the recorded rate times 2,080")
    for column in MEASURES.values():
        retention_flags(frame["gross_pay"], frame[column], 0)


def load_job_part(files: dict, entries: list[dict], part: int, person_table: pd.DataFrame,
                  expected_by_state: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Every included job rank of one part, each pair validated against its record."""
    from scripts.job_entry_outputs import validate_pair

    frames, records = [], []
    for entry in (e for e in entries if e["kind"] == "job_record"):
        json_bytes = files[entry["name"]]
        csv_rel = json.loads(json_bytes)["rows"]["file"]
        record = validate_pair(json_bytes, files[csv_rel],
                               dict(part=part, rank=entry["rank"], scope=entry["scope"]))
        frame = pd.read_csv(io.BytesIO(files[csv_rel]), compression="gzip", usecols=JOB_COLUMNS,
                            dtype={"state_code": str}, keep_default_na=False)
        if not (frame["rank"] == record["rank"]).all():
            raise ValueError(f"{entry['name']}: rows of another rank")
        by_state = frame["state_code"].value_counts().to_dict()
        if by_state != record["counts"]["sample_candidates_tested_by_state"]:
            raise ValueError(f"{entry['name']}: rows by state differ from the record")
        if frame["household_id"].nunique() != record["counts"]["sample_households_touched"]:
            raise ValueError(f"{entry['name']}: rows touch other households than the record")
        validate_job_rows(frame, person_table, record["provenance"]["rates_used"])
        frames.append(frame.assign(scope=record["scope"]))
        records.append(record)
    job = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame({c: pd.Series(dtype=t) for c, t in
                              zip([*JOB_COLUMNS, "scope"], ["int64", "int64", "int64", "str", "int64",
                                                            "float64", "float64", "float64", "str"])}))
    rates = {}
    for record in records:
        rates.update(record["provenance"]["rates_used"])
    validate_job_rows(job, person_table, rates)
    by_state = {s: int(n) for s, n in job["state_code"].value_counts().items()}
    if by_state != {s: n for s, n in expected_by_state.items() if n}:
        raise ValueError(f"part {part}: job rows by state differ from the coverage plan")
    return job, records


# ---------------------------------------------------------------------------
# Flags and set logic (unweighted booleans)


def raise_test_flags(frames: dict, people: int) -> dict:
    """measure -> raise key -> threshold -> person flags (current workers only)."""
    out = {}
    for measure, column in MEASURES.items():
        out[measure] = {
            key: {
                threshold: full_mask(frame, retention_flags(frame["change"], frame[column], value,
                                                            frame["worker"]), people)
                for threshold, value in THRESHOLDS.items()
            }
            for key, frame in frames.items()
        }
    return out


def job_test_flags(frame: pd.DataFrame, people: int) -> dict:
    """measure -> threshold -> person flags: the tested adult whose household keeps < t of the pay."""
    return {
        measure: {
            threshold: full_mask(frame, retention_flags(frame["gross_pay"], frame[column], value), people)
            for threshold, value in THRESHOLDS.items()
        }
        for measure, column in MEASURES.items()
    }


def set_flags(tests: dict) -> dict:
    """measure -> set -> threshold -> person flags, each set the OR of its tests."""
    return {
        measure: {
            name: {
                threshold: np.logical_or.reduce([tests[measure][c][threshold] for c in components])
                for threshold in THRESHOLDS
            }
            for name, components in SETS.items()
        }
        for measure in tests
    }


def household_any(flags, household_index, households: int) -> np.ndarray:
    """Households with at least one flagged member (unweighted)."""
    flags = np.asarray(flags, dtype=bool)
    return np.bincount(np.asarray(household_index)[flags], minlength=households) > 0


def subset(a, b) -> bool:
    return not bool((np.asarray(a, bool) & ~np.asarray(b, bool)).any())


def check_set_invariants(household: dict, groups: dict) -> dict:
    """Household-level invariants; ``household[measure][set][threshold]`` and
    ``groups[measure][set]`` hold boolean household arrays."""
    nesting = union = grows = partition = True
    for measure, sets in household.items():
        for name, by_threshold in sets.items():
            for low, high in zip(NESTED, NESTED[1:]):
                nesting &= subset(by_threshold[low], by_threshold[high])
            for threshold in THRESHOLDS:
                parts = [household[measure][c][threshold] for c in SETS[name]]
                union &= all(subset(p, by_threshold[threshold]) for p in parts)
                union &= bool(np.array_equal(np.logical_or.reduce(parts), by_threshold[threshold]))
            strict, half = by_threshold[STRICT], by_threshold[HALF]
            additional = groups[measure][name]["additional"]
            partition &= not bool((strict & additional).any())
            partition &= bool(np.array_equal(strict | additional, half))
            partition &= bool(np.array_equal(additional, half & ~strict))
        for small, large in GROWS:
            for threshold in (STRICT, HALF):
                grows &= subset(sets[small][threshold], sets[large][threshold])
    return {
        "threshold_nesting_households": nesting,
        "union_contains_components_households": union,
        "strict_additional_partition_below_half_households": partition,
        "adding_a_test_never_shrinks_strict_or_below_half_households": grows,
    }


def _le(a: float, b: float) -> bool:
    return a <= b + TOLERANCE * max(abs(b), 1.0)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=TOLERANCE, abs_tol=1e-6)


def check_count_invariants(metrics: dict) -> dict:
    """Weighted-count invariants on ``metrics[label][field]`` (a part's or the national totals)."""
    nesting = bounded = partition = grows = overlap = once = True
    for measure in MEASURES:
        def get(name, stat):
            return metrics[f"{measure}|{name}|{stat}"]

        for name, components in SETS.items():
            for low, high in zip(NESTED, NESTED[1:]):
                nesting &= all(_le(get(name, low)[f], get(name, high)[f]) for f in FIELDS)
            for threshold in THRESHOLDS:
                value = get(name, threshold)
                for f in FIELDS:
                    parts = [get(c, threshold)[f] for c in components]
                    bounded &= _le(max(parts), value[f]) and _le(value[f], sum(parts))
                once &= _le(value["adults"], value["household_members"])
            strict, half, extra = get(name, STRICT), get(name, HALF), get(name, "additional")
            for f in ("households", "household_members"):
                partition &= _close(strict[f] + extra[f], half[f]) and extra[f] >= 0
        for small, large in GROWS:
            for threshold in (STRICT, HALF):
                grows &= all(_le(get(small, threshold)[f], get(large, threshold)[f]) for f in FIELDS)
        original = metrics[f"{measure}|original_raise_1000"]
        for base in OVERLAP_BASES:
            for level in LEVELS:
                inside = get(base, f"original_1000_in_{level}")
                outside = get(base, f"original_1000_outside_{level}")
                for f in ("households", "household_members"):
                    overlap &= _close(inside[f] + outside[f], original[f])
    return {
        "threshold_nesting_counts": nesting,
        "union_between_largest_component_and_sum_counts": bounded,
        "strict_plus_additional_equals_below_half_counts": partition,
        "adding_a_test_never_lowers_strict_or_below_half_counts": grows,
        "overlap_inside_plus_outside_equals_original_counts": overlap,
        "flagged_adults_within_household_members_counts": once,
    }


# ---------------------------------------------------------------------------
# MicroSeries counting


class PartCounter:
    """Registers analysis flags in one part's simulation and counts them with MicroSeries.

    ``household_source`` gives each simulation household's source household, so
    the same flags also give per-source totals through ``MicroSeries.groupby``.
    """

    def __init__(self, simulation, year: int, prefix: str, household_source=None,
                 per_source: bool = True):
        self.sim, self.year, self.prefix = simulation, year, prefix
        self.household_index = np.asarray(simulation.populations["household"].members_entity_id)
        self.households = simulation.populations["household"].count
        self.people = simulation.populations["person"].count
        self.per_source = per_source and household_source is not None
        if self.per_source:
            self.household_source = np.asarray(household_source)
            if len(self.household_source) != self.households:
                raise ValueError("source households must align with simulation households")
            self.person_source = self.household_source[self.household_index]
            self.sources = np.unique(self.household_source)
        self.metrics, self.sources_totals, self.sample = {}, {}, {}

    def name(self, label: str) -> str:
        return f"{self.prefix}_{label}".replace("-", "_").replace(".", "_")

    def person_flag(self, label: str, flags) -> tuple[str, str]:
        person = self.name(label)
        flags = np.asarray(flags, dtype=bool)
        if flags.shape != (self.people,):
            raise ValueError(f"{label}: flags do not cover the part's people")
        return person, set_person_flag(self.sim, person, flags, self.year)

    def household_flag(self, label: str, left: str, right: str, operation: str) -> str:
        household = self.name(label)
        add_variable(self.sim, household, "household", household_combination(left, right, operation))
        return household

    def households_of(self, household: str) -> np.ndarray:
        return np.asarray(self.sim.calculate(household, period=self.year, use_weights=False), dtype=bool)

    def _source_totals(self, series, by) -> np.ndarray:
        totals = series.groupby(by).sum()
        return totals.reindex(self.sources, fill_value=0.0).to_numpy(dtype=np.float64)

    def record(self, label: str, household: str, person: str | None = None,
               adults_in: str | None = None) -> dict:
        """Households and residents of a household set, and its flagged adults: the set's own
        flag (``person``, as flag_counts) or flagged adults inside it (``adults_in``)."""
        if person is not None:
            values = flag_counts(self.sim, person, household, self.year)
        else:
            values = household_counts(self.sim, household, self.year, adults_in)
        values = {f: float(v) for f, v in values.items()}
        members = self.sim.calc(household, period=self.year, map_to="person")
        mapped = np.asarray(self.sim.calculate(household, period=self.year, map_to="person", use_weights=False))
        if not np.isin(mapped, (0, 1)).all():
            raise ValueError(f"{label}: a resident is counted more than once")
        if person is not None or adults_in is not None:
            flagged = np.asarray(self.sim.calculate(person or adults_in, period=self.year, use_weights=False),
                                 dtype=bool)
            if person is not None and not subset(flagged, mapped.astype(bool)):
                raise ValueError(f"{label}: a flagged adult lives outside the flagged households")
        if self.per_source:
            totals = {
                "households": self._source_totals(self.sim.calc(household, period=self.year),
                                                  self.household_source),
                "household_members": self._source_totals(members, self.person_source),
            }
            if person is not None:
                totals["adults"] = self._source_totals(self.sim.calc(person, period=self.year),
                                                       self.person_source)
            elif adults_in is not None:
                totals["adults"] = self._source_totals(
                    self.sim.calc(adults_in, period=self.year) * members, self.person_source)
            for f, column in totals.items():
                if not _close(float(column.sum()), values[f]):
                    raise ValueError(f"{label}.{f}: per-source totals do not add to the count")
            self.sources_totals[label] = totals
        self.metrics[label] = values
        self.sample[label] = int(self.households_of(household).sum())
        return values


def count_sets(counter: PartCounter, raise_frames: dict, raise_records: dict, job: pd.DataFrame) -> dict:
    """Every set, threshold, group and overlap count of one part, and its household sets."""
    people = counter.people
    raise_flags = raise_test_flags(raise_frames, people)
    job_flags = job_test_flags(job, people)
    workers = {key: full_mask(f, f["worker"].to_numpy(dtype=bool), people) for key, f in raise_frames.items()}
    tested = full_mask(job, np.ones(len(job), dtype=bool), people)
    if any((w & tested).any() for w in workers.values()):
        raise ValueError("a raise worker is also a job-entry candidate")
    tests = {m: {**raise_flags[m], JOB: job_flags[m]} for m in MEASURES}
    sets = set_flags(tests)

    names, household, groups = {}, {}, {}
    worker_validation = {}
    for key in RAISES:
        person, _ = counter.person_flag(f"workers_{key}", workers[key])
        reached = counter.sim.calc(person, period=counter.year).sum()
        assert_scalar_match(reached, raise_records[key]["change"]["workers_reached"], f"{key}.workers_reached")
        worker_validation[key] = {"workers_reached": float(reached)}
    for measure, column in MEASURES.items():
        household[measure], groups[measure] = {}, {}
        for name in SETS:
            household[measure][name] = {}
            for threshold in THRESHOLDS:
                flags = sets[measure][name][threshold]
                person, hh = counter.person_flag(f"{measure}_{name}_{threshold}", flags)
                counter.record(f"{measure}|{name}|{threshold}", hh, person=person)
                names[measure, name, threshold] = (person, hh)
                ours = counter.households_of(hh)
                if not np.array_equal(ours, household_any(flags, counter.household_index, counter.households)):
                    raise ValueError(f"{measure} {name} {threshold}: household mapping disagrees")
                household[measure][name][threshold] = ours
        for key, frame in raise_frames.items():
            flags = full_mask(frame, retention_flags(frame["change"], frame[column], 0), people)
            person, hh = counter.person_flag(f"{measure}_original_{key}", flags)
            counts = counter.record(f"{measure}|original_{key}", hh, person=person)
            assert_counts_match(counts, raise_records[key]["change"][measure], f"{key}.{measure}")
            on_cliff = (counter.sim.calc(person, period=counter.year)
                        * counter.sim.calc(counter.name(f"workers_{key}"), period=counter.year)).sum()
            assert_scalar_match(on_cliff, raise_records[key]["change"][measure]["workers_on_cliff"],
                                f"{key}.{measure}.workers_on_cliff")
            worker_validation[key][f"{measure}_workers_on_cliff"] = float(on_cliff)
            names[measure, f"original_{key}"] = (person, hh)
        original = names[measure, "original_raise_1000"][1]
        for name in SETS:
            half_person, half = names[measure, name, HALF]
            strict = names[measure, name, STRICT][1]
            extra = counter.household_flag(f"{measure}_{name}_additional", half, strict, "left_only")
            counter.record(f"{measure}|{name}|additional", extra, adults_in=half_person)
            groups[measure][name] = {"additional": counter.households_of(extra)}
        for base in OVERLAP_BASES:
            for level, threshold in LEVELS.items():
                target = names[measure, base, threshold][1]
                for where, operation in (("in", "intersection"), ("outside", "left_only")):
                    label = f"original_1000_{where}_{level}"
                    flag = counter.household_flag(f"{measure}_{base}_{label}", original, target, operation)
                    counter.record(f"{measure}|{base}|{label}", flag)
            half_person, half = names[measure, base, HALF]
            flag = counter.household_flag(f"{measure}_{base}_below_half_outside_original", half, original,
                                          "left_only")
            counter.record(f"{measure}|{base}|below_half_outside_original_1000", flag, adults_in=half_person)
        for base, raise_only in JOB_INCREMENT.items():
            for level, threshold in LEVELS.items():
                person, target = names[measure, base, threshold]
                flag = counter.household_flag(f"{measure}_{base}_added_by_job_{level}", target,
                                              names[measure, raise_only, threshold][1], "left_only")
                counter.record(f"{measure}|{base}|added_by_job_{level}", flag, adults_in=person)
    return {"household": household, "groups": groups, "names": names, "sets": sets,
            "worker_validation": worker_validation, "job_tested": tested}


# ---------------------------------------------------------------------------
# Reproductions


def raise_union_view(metrics: dict, base: str = "raise_union") -> tuple[dict, dict]:
    """Our counts under the raise union JSON's keys, with ``base`` as its union."""
    view, originals = {}, {}
    for m in MEASURES:
        for key in RAISES:
            for threshold in THRESHOLDS:
                view[f"{m}.{key}.{threshold}"] = metrics[f"{m}|{key}|{threshold}"]
            originals[f"{m}.{key}"] = metrics[f"{m}|original_{key}"]
        for threshold in THRESHOLDS:
            view[f"{m}.union.{threshold}"] = metrics[f"{m}|{base}|{threshold}"]
        view[f"{m}.additional_below_half_excluding_strict"] = metrics[f"{m}|{base}|additional"]
        for level, theirs in (("below_half", "union_below_half"), ("strict", "union_strict")):
            view[f"{m}.original_1000_in_{theirs}"] = metrics[f"{m}|{base}|original_1000_in_{level}"]
            view[f"{m}.original_1000_outside_{theirs}"] = metrics[f"{m}|{base}|original_1000_outside_{level}"]
        view[f"{m}.union_below_half_outside_original_1000"] = metrics[f"{m}|{base}|below_half_outside_original_1000"]
    return view, originals


def compare_counts(ours: dict, theirs: dict, label: str) -> dict:
    """Every count in ``theirs`` against ours: exact when every difference is zero; stops past 1e-9."""
    if set(ours) != set(theirs):
        raise ValueError(f"{label}: keys differ: {sorted(set(ours) ^ set(theirs))}")
    worst_abs = worst_rel = 0.0
    compared = 0
    for key, fields in theirs.items():
        if set(fields) != set(ours[key]):
            raise ValueError(f"{label}.{key}: fields differ")
        for f, value in fields.items():
            gap = abs(ours[key][f] - value)
            worst_abs = max(worst_abs, gap)
            worst_rel = max(worst_rel, gap / max(abs(value), 1.0))
            compared += 1
            if not _close(ours[key][f], value):
                raise ValueError(f"{label}.{key}.{f}: {ours[key][f]} differs from {value}")
    return {"pass": True, "exact": worst_abs == 0.0, "counts_compared": compared,
            "max_abs_difference": worst_abs, "max_relative_difference": worst_rel}


def reproduce_job_records(counter: PartCounter, job: pd.DataFrame, records: list[dict], job_flags_sample: dict) -> dict:
    """The job runner's own per-rank totals, recounted from the rows with MicroSeries."""
    worst = 0.0
    out = []
    for record in records:
        rows = job[(job["scope"] == record["scope"]) & (job["rank"] == record["rank"])]
        mask = full_mask(rows, np.ones(len(rows), dtype=bool), counter.people)
        person, household = counter.person_flag(f"jobrank_{record['scope']}_{record['rank']}", mask)
        tested = float(counter.sim.calc(person, period=counter.year).sum())
        members = float(counter.sim.calc(household, period=counter.year, map_to="person").sum())
        for ours, key in ((tested, "weighted_candidates_tested"),
                          (members, "weighted_members_of_touched_households")):
            theirs = record["counts"][key]
            worst = max(worst, abs(ours - theirs) / max(abs(theirs), 1.0))
            if not _close(ours, theirs):
                raise ValueError(f"job {record['scope']} rank {record['rank']} {key}: {ours} vs {theirs}")
        below = {
            column: {f"keeps_less_than_{value:g}": int(retention_flags(rows["gross_pay"], rows[column], value).sum())
                     for value in THRESHOLDS.values()}
            for column in MEASURES.values()
        }
        if below != record["counts"]["sample_tested_below_threshold"]:
            raise ValueError(f"job {record['scope']} rank {record['rank']}: sample counts below thresholds differ")
        out.append({"scope": record["scope"], "rank": record["rank"],
                    "weighted_candidates_tested": tested, "weighted_members_of_touched_households": members,
                    "sample_tested_below_threshold": below})
    for measure, column in MEASURES.items():
        for threshold, value in THRESHOLDS.items():
            runner = sum(r["counts"]["sample_tested_below_threshold"][column][f"keeps_less_than_{value:g}"]
                         for r in records)
            if runner != job_flags_sample[measure][threshold]:
                raise ValueError(f"job {measure} {threshold}: flagged adults differ from the runner's counts")
    return {"pass": True, "ranks": out, "max_relative_difference": worst,
            "weighted_candidates_tested": sum(r["weighted_candidates_tested"] for r in out)}


# ---------------------------------------------------------------------------
# One part


def peak_memory_gib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024**3 if sys.platform == "darwin" else 1024**2), 3)


def part_identities(simulation, dataset, year: int = YEAR) -> np.ndarray:
    """Check the simulation's people and households against the dataset; return household sources."""
    person_id = np.asarray(simulation.calculate("person_id", period=year, use_weights=False))
    household_id = np.asarray(simulation.calculate("household_id", period=year, use_weights=False))
    if not np.array_equal(person_id, dataset.person["person_id"].to_numpy()):
        raise ValueError("simulation people are not in the dataset's person order")
    if len(np.unique(person_id)) != len(person_id):
        raise ValueError("the part repeats a person")
    if not np.array_equal(household_id, dataset.household["household_id"].to_numpy()):
        raise ValueError("simulation households are not in the dataset's household order")
    index = np.asarray(simulation.populations["household"].members_entity_id)
    if not np.array_equal(household_id[index], dataset.person["person_household_id"].to_numpy()):
        raise ValueError("simulation membership differs from the dataset's person mapping")
    return dataset.household["household_source_id"].to_numpy()


def summarize_part(simulation, dataset, files: dict, manifest: dict, part: int, year: int = YEAR) -> tuple[dict, dict]:
    """Counts, invariants and reproductions for one part; and its per-source totals."""
    entries = [e for e in manifest["inputs"] if e["part"] == part]
    person_table = dataset.person
    raise_frames, raise_records = load_raise_part(files, part, person_table)
    job, job_records = load_job_part(files, entries, part, person_table,
                                     manifest["coverage"]["expected_rows_by_part"][str(part)])
    source = part_identities(simulation, dataset, year)

    counter = PartCounter(simulation, year, "cu", source)
    main = count_sets(counter, raise_frames, raise_records, job)
    sample_job = {m: {t: int(main["sets"][m][JOB][t].sum()) for t in THRESHOLDS} for m in MEASURES}
    job_repro = reproduce_job_records(counter, job, job_records, sample_job)
    set_checks = check_set_invariants(main["household"], main["groups"])

    # Empty the job rows and count again in fresh analysis variables.
    empty = PartCounter(simulation, year, "cu0", per_source=False)
    emptied = count_sets(empty, raise_frames, raise_records, job.iloc[0:0])
    for measure in MEASURES:
        for threshold in THRESHOLDS:
            if not (np.array_equal(emptied["sets"][measure]["combined"][threshold],
                                   main["sets"][measure]["raise_union"][threshold])
                    and np.array_equal(emptied["sets"][measure]["combined_1000"][threshold],
                                       main["sets"][measure]["raise_1000"][threshold])
                    and not emptied["sets"][measure][JOB][threshold].any()):
                raise ValueError(f"{measure} {threshold}: emptied job rows do not reduce to the raise sets")
    raise_json = json.loads(files[inputs.RAISE_UNION_JSON])
    theirs = next(p for p in raise_json["parts"] if p["part"] == part)
    view, originals = raise_union_view(counter.metrics)
    emptied_view, emptied_originals = raise_union_view(empty.metrics, base="combined")
    reproduction = {
        "raise_union_metrics": compare_counts(view, theirs["metrics"], f"part {part} raise union"),
        "raise_union_original_all_adults_strict": compare_counts(originals, theirs["original_all_adults_strict"],
                                                                 f"part {part} originals"),
        "raise_union_worker_validation": compare_counts(main["worker_validation"], theirs["worker_validation"],
                                                        f"part {part} workers"),
        "emptied_job_combined_metrics": compare_counts(emptied_view, theirs["metrics"],
                                                       f"part {part} emptied combined"),
        "emptied_job_combined_original_all_adults_strict": compare_counts(
            emptied_originals, theirs["original_all_adults_strict"], f"part {part} emptied originals"),
    }
    same = all(empty.metrics[f"{m}|combined|{t}"] == counter.metrics[f"{m}|raise_union|{t}"]
               and empty.metrics[f"{m}|combined_1000|{t}"] == counter.metrics[f"{m}|raise_1000|{t}"]
               for m in MEASURES for t in THRESHOLDS)
    if not same:
        raise ValueError("emptied combined counts differ from the raise union counts")
    count_checks = check_count_invariants(counter.metrics)
    invariants = {
        **{k: {"pass": v} for k, v in set_checks.items()},
        **{k: {"pass": v} for k, v in count_checks.items()},
        "each_person_counted_once": {
            "pass": True,
            "detail": "unique person IDs and rows; residents mapped once (0/1); flagged adults inside "
                      "their flagged households; raise workers and job candidates disjoint",
        },
        "emptied_job_combined_equals_raise_union": {"pass": same, "exact": True},
        "raise_union_reproduced": {"pass": True, "exact": all(r["exact"] for r in reproduction.values())},
        "job_runner_totals_reproduced": {"pass": True,
                                         "max_relative_difference": job_repro["max_relative_difference"]},
    }
    failed = [k for k, v in invariants.items() if v["pass"] is not True]
    if failed:
        raise ValueError(f"part {part}: invariants failed: {failed}")
    labels = sorted(counter.sources_totals)
    columns = [f"{label}|{f}" for label in labels for f in sorted(counter.sources_totals[label])]
    matrix = np.column_stack([counter.sources_totals[label][f] for label in labels
                              for f in sorted(counter.sources_totals[label])])
    record = {
        "status": "complete",
        "part": part,
        "digest": manifest["digest"],
        "code": manifest["code"],
        "metrics": counter.metrics,
        "sample_households": counter.sample,
        "worker_validation": main["worker_validation"],
        "job": {"sample_candidates_tested": int(len(job)), "sample_flagged": sample_job,
                "jurisdictions": sorted(set(job["state_code"])), "runner_reproduction": job_repro},
        "reproduction": reproduction,
        "invariants": invariants,
        "source_households": int(len(counter.sources)),
        "source_household_ids_sha256": hashlib.sha256(np.ascontiguousarray(counter.sources).tobytes()).hexdigest(),
    }
    del emptied, empty
    gc.collect()
    return record, {"sources": counter.sources, "matrix": matrix, "columns": columns}


def run_part(part: int, manifest: dict, files: dict, year: int = YEAR) -> tuple[dict, bytes]:
    """Load one part's frozen simulation, summarize it, and serialize its per-source totals."""
    from scripts.expanded_historical import historical_provenance
    from scripts.expanded_raise_union import historical_part

    inputs.check_files(manifest, part, files)
    started = time.time()
    dataset, simulation = historical_part(year, inputs.PARTS, part, inputs.SEED)
    loaded = round(time.time() - started, 1)
    record, totals = summarize_part(simulation, dataset, files, manifest, part, year)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, sources=totals["sources"], matrix=totals["matrix"],
                        columns=np.array(totals["columns"]))
    npz = buffer.getvalue()
    record["per_source"] = {
        "sha256": inputs.sha256(npz),
        "columns": totals["columns"],
        "rows": int(totals["matrix"].shape[0]),
        "record_level": "per-source-household totals; git-ignored; never commit",
    }
    record["runtime"] = {
        "historical_loader": historical_provenance(),
        "versions": {p: metadata.version(p) for p in ("policyengine-us", "policyengine-core", "microdf-python",
                                                      "numpy", "pandas")},
        "seconds_load": loaded,
        "seconds_total": round(time.time() - started, 1),
        "peak_memory_gib": peak_memory_gib(),
    }
    return record, npz


# ---------------------------------------------------------------------------
# Bootstrap


def load_per_source(npz: bytes) -> dict:
    with np.load(io.BytesIO(npz), allow_pickle=False) as data:
        return {"sources": data["sources"], "matrix": data["matrix"], "columns": [str(c) for c in data["columns"]]}


def resample(stats: np.ndarray, draws: int, seed: int, batch: int = 250) -> np.ndarray:
    """scripts/driver_intervals.resample in batches: the same multinomial stream and draws."""
    n = len(stats)
    held = np.flatnonzero(np.any(stats != 0, axis=1))
    rng = np.random.default_rng(seed)
    p = np.full(n, 1 / n)
    out = np.empty((draws, stats.shape[1]))
    for start in range(0, draws, batch):
        size = min(batch, draws - start)
        counts = rng.multinomial(n, p, size=size)
        out[start:start + size] = counts[:, held] @ stats[held]
    return out


def bootstrap_parts(records: list[dict], npz_list: list[bytes], draws: int = DRAWS, seed: int = BOOTSTRAP_SEED) -> dict:
    """Joint percentile intervals for every count, resampling all source households at once."""
    from scripts.driver_intervals import interval

    parts = [load_per_source(b) for b in npz_list]
    columns = parts[0]["columns"]
    if any(p["columns"] != columns for p in parts):
        raise ValueError("parts hold different per-source columns")
    sources = np.concatenate([p["sources"] for p in parts])
    if len(np.unique(sources)) != len(sources):
        raise ValueError("a source household appears in two parts")
    if sorted(r["part"] for r in records) != list(range(inputs.PARTS)):
        raise ValueError("the bootstrap needs every part")
    stats = np.vstack([p["matrix"] for p in parts])
    totals = add_part_metrics(records)
    flat = {f"{label}|{f}": v for label, fields in totals.items() for f, v in fields.items()}
    estimates = stats.sum(axis=0)
    for j, column in enumerate(columns):
        if not _close(float(estimates[j]), flat[column]):
            raise ValueError(f"{column}: per-source totals add to {estimates[j]}, counts to {flat[column]}")
    started = time.time()
    out = resample(stats, draws, seed)
    result = {}
    for j, column in enumerate(columns):
        result[column] = {
            "estimate": flat[column],
            "standard_error": float(out[:, j].std(ddof=1)),
            "interval_95": interval(out[:, j]),
            "source_households_with_any": int((stats[:, j] != 0).sum()),
        }
    return {
        "draws": draws,
        "seed": seed,
        "method": "percentile; multinomial resample of all source households jointly, one draw for every count "
                  "(scripts/driver_intervals.resample, batched)",
        "source_households": int(len(sources)),
        "seconds": round(time.time() - started, 1),
        "columns": result,
    }


# ---------------------------------------------------------------------------
# Combine


def add_in_order(values) -> float:
    """Plain left-to-right float addition over the parts in part order.

    The raise union added numpy scalars, which Python's sum() adds one by one.
    Since Python 3.12, sum() of exact floats (here, values read back from JSON)
    compensates rounding instead, which can move a total by one unit in the last
    place; this keeps the raise union's arithmetic so its totals reproduce exactly.
    """
    total = 0.0
    for value in values:
        total = total + float(value)
    return total


def add_part_metrics(records: list[dict]) -> dict:
    records = sorted(records, key=lambda r: r["part"])
    keys = {label: set(fields) for label, fields in records[0]["metrics"].items()}
    for record in records[1:]:
        if {label: set(fields) for label, fields in record["metrics"].items()} != keys:
            raise ValueError("parts have inconsistent metric keys")
    return {label: {f: add_in_order(r["metrics"][label][f] for r in records) for f in sorted(fields)}
            for label, fields in sorted(keys.items())}


def add_nested(records: list[dict], key: str) -> dict:
    records = sorted(records, key=lambda r: r["part"])
    first = records[0][key]
    return {name: {f: add_in_order(r[key][name][f] for r in records) for f in fields}
            for name, fields in first.items()}


def with_interval(boot: dict, label: str, fields=FIELDS) -> dict:
    out = {}
    for f in fields:
        column = boot["columns"].get(f"{label}|{f}")
        if column is not None:
            out[f] = {"estimate": column["estimate"], "interval_95": column["interval_95"],
                      "standard_error": column["standard_error"]}
    return out


def headline(totals: dict, boot: dict, sample: dict) -> dict:
    out = {}
    for measure in MEASURES:
        out[measure] = {}
        for base in SETS:
            entry = {
                "strict_loss": with_interval(boot, f"{measure}|{base}|{STRICT}"),
                "additional_below_half": with_interval(boot, f"{measure}|{base}|additional"),
                "below_half_total": with_interval(boot, f"{measure}|{base}|{HALF}"),
                "sample_households": {
                    "strict_loss": sample[f"{measure}|{base}|{STRICT}"],
                    "additional_below_half": sample[f"{measure}|{base}|additional"],
                    "below_half_total": sample[f"{measure}|{base}|{HALF}"],
                },
            }
            if base in JOB_INCREMENT:
                entry["added_by_job"] = {
                    level: with_interval(boot, f"{measure}|{base}|added_by_job_{level}") for level in LEVELS
                }
            out[measure][base] = entry
    return out


def overlap(totals: dict, boot: dict) -> dict:
    out = {}
    for measure in MEASURES:
        out[measure] = {"original_raise_1000_all_adults_strict": with_interval(boot, f"{measure}|original_raise_1000")}
        for base in OVERLAP_BASES:
            out[measure][base] = {
                f"{where}_{level}": with_interval(boot, f"{measure}|{base}|original_1000_{where}_{level}",
                                                  ("households", "household_members"))
                for where in ("in", "outside") for level in LEVELS
            }
            out[measure][base]["below_half_outside_original"] = with_interval(
                boot, f"{measure}|{base}|below_half_outside_original_1000")
    return out


def combine(digest: str, draws: int, seed: int, out: Path) -> dict:
    from scripts.earnings_changes_summary import check_code
    from scripts.expanded_historical import historical_provenance

    manifest = json.loads((ROOT / inputs.manifest_rel(digest)).read_text())
    if inputs.manifest_digest(manifest) != manifest["digest"] or manifest["digest"] != digest:
        raise ValueError("the manifest does not match its digest")
    records = []
    for part in range(inputs.PARTS):
        record = inputs.local_part(ROOT, digest, part)
        if record is None:
            raise FileNotFoundError(f"part {part} has no validated result for {digest[:16]}")
        records.append(record)
    commits = {r["code"]["commit"] for r in records}
    if commits != {manifest["code"]["commit"]}:
        raise ValueError("parts ran other code than the manifest records")
    if inputs.code_hashes(ROOT) != manifest["code"]["sha256"]:
        raise ValueError("this checkout's code differs from the code the parts ran")
    raise_records = [json.loads((ROOT / inputs.raise_metadata_rel(p, k)).read_text())
                     for p in range(inputs.PARTS) for k in RAISES]
    raise_code = check_code(YEAR, raise_records)
    boot = json.loads((ROOT / inputs.bootstrap_rel(digest, draws, seed)).read_text())
    totals = add_part_metrics(records)
    flat = {f"{label}|{f}": v for label, fields in totals.items() for f, v in fields.items()}
    for column, entry in boot["columns"].items():
        if not _close(entry["estimate"], flat[column]):
            raise ValueError(f"bootstrap {column} estimate differs from the part totals")
    sample = {label: sum(r["sample_households"][label] for r in records) for label in records[0]["sample_households"]}
    count_checks = check_count_invariants(totals)
    if not all(count_checks.values()):
        raise ValueError(f"national invariants failed: {[k for k, v in count_checks.items() if not v]}")
    raise_json = json.loads((ROOT / inputs.RAISE_UNION_JSON).read_text())
    view, originals = raise_union_view(totals)
    national_repro = {
        "metrics": compare_counts(view, raise_json["metrics"], "national raise union"),
        "original_all_adults_strict": compare_counts(originals, raise_json["original_all_adults_strict"],
                                                     "national originals"),
        "worker_validation": compare_counts(add_nested(records, "worker_validation"),
                                            raise_json["worker_validation"], "national workers"),
    }
    part_exact = all(r["reproduction"][k]["exact"] for r in records for k in r["reproduction"])
    invariants = {}
    for name in records[0]["invariants"]:
        entries = [r["invariants"][name] for r in records]
        invariants[name] = {"pass_every_part": all(e["pass"] is True for e in entries)}
        for extra in ("exact", "max_relative_difference"):
            if extra in entries[0]:
                values = [e[extra] for e in entries]
                invariants[name][extra] = all(values) if extra == "exact" else max(values)
    invariants["national_counts"] = count_checks
    coverage = manifest["coverage"]
    launches_path = ROOT / inputs.launches_rel(digest)
    launches = [json.loads(line) for line in launches_path.read_text().splitlines()] if launches_path.exists() else []
    result = {
        "status": coverage["status"],
        "year": YEAR,
        "question": "People in households that trip the raise test or the job test under 2017 federal rules, "
                    "each person counted once.",
        "tests": {
            "raise": "A current worker among the household's two highest-earning adults (by market income) gets "
                     "a $1,000, $2,000 or $5,000 raise, one adult at a time.",
            "job": "A working-age adult (18-64) with no wages or self-employment income, excluding full-time "
                   "students and people reporting disability, takes a full-time job (40 hours x 52 weeks) at "
                   "the state's 2017 minimum wage, one adult at a time.",
        },
        "test_sets": {name: list(components) for name, components in SETS.items()},
        "thresholds": THRESHOLDS,
        "retention": "Change in household resources divided by the gross pay change; a household trips a test "
                     "at t when any tested adult's household keeps strictly less than t.",
        "measures": {
            "with_health": "Government-valued health coverage, ACA PTC counted once (d_net_single_ptc).",
            "without_health": "Every part of net income except health benefits and costs (d_net_without_health).",
        },
        "groups": {
            "strict_loss": "Households below 0% retention on any test in the set; residents counted once.",
            "additional_below_half": "Households below 50% on any test in the set, excluding every household "
                                     "below 0% on any test in the set; residents counted once; measured "
                                     "directly as its own household set.",
            "below_half_total": "Households below 50% on any test in the set (strict plus additional).",
            "added_by_job": "Households in the combined set but not its raise-only counterpart "
                            "(combined vs raise_union, combined_1000 vs raise_1000).",
        },
        "scope": "Finite grid of raises and one job offer per eligible adult; no claim about other raise sizes, "
                 "untested adults, additional childcare costs or new employer coverage.",
        "coverage": {k: coverage[k] for k in ("scopes_selected", "scopes_included", "scopes_excluded",
                                              "jurisdictions_covered",
                                              "jurisdictions_deferred", "sample_candidates_tested",
                                              "sample_candidates_deferred", "wages_json_sha256_by_scope")},
        "headline": headline(totals, boot, sample),
        "overlap_with_original_6_2_million": overlap(totals, boot),
        "metrics": totals,
        "sample_households": sample,
        "job": {
            "sample_candidates_tested": sum(r["job"]["sample_candidates_tested"] for r in records),
            "weighted_candidates_tested": sum(r["job"]["runner_reproduction"]["weighted_candidates_tested"]
                                              for r in records),
        },
        "reproduction": {
            "raise_union_national": national_repro,
            "raise_union_every_part_exact": part_exact,
            "raise_union_exact": part_exact and all(v["exact"] for v in national_repro.values()),
        },
        "invariants": invariants,
        "uncertainty": {k: boot[k] for k in ("draws", "seed", "method", "source_households", "seconds")},
        "intervals": boot["columns"],
        "aggregation": "MicroSeries.sum and MicroSeries.groupby(source household).sum on analysis flags in each "
                       "part's frozen simulation, with map_to='person' for residents; stored weight columns are "
                       "not read.",
        "runtime": {
            "mode": "unmanaged_frozen_historical_output_postprocessing",
            "historical_loader": historical_provenance(),
            "parts": [{"part": r["part"], **r["runtime"]} for r in records],
        },
        "code": {
            "launch_commit": manifest["code"]["commit"],
            "code_sha256": manifest["code"]["sha256"],
            "raise_experiment_code": raise_code,
            "combine_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        },
        "modal": {"app": "us-cliffs-2017-combined-union", "launches": launches},
        "manifest_digest": digest,
        "inputs": [{k: e[k] for k in ("kind", "source", "part", "name", "sha256")} for e in manifest["inputs"]],
        "parts": [{"part": r["part"], "metrics": r["metrics"], "source_households": r["source_households"],
                   "job_sample_candidates_tested": r["job"]["sample_candidates_tested"],
                   "reproduction": r["reproduction"]} for r in records],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("combine", help="add the installed part results and write the national JSON")
    c.add_argument("--digest", required=True)
    c.add_argument("--draws", type=int, default=DRAWS)
    c.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    c.add_argument("--out", type=Path, default=ROOT / inputs.FINAL_JSON)
    args = parser.parse_args()
    digest = args.digest
    if len(digest) == 16:
        matches = [p.stem for p in (ROOT / inputs.OUT_BASE / "manifests").glob(f"{digest}.json")]
        if not matches:
            raise SystemExit(f"no manifest {digest}")
        digest = json.loads((ROOT / inputs.manifest_rel(digest)).read_text())["digest"]
    result = combine(digest, args.draws, args.seed, args.out)
    for measure in MEASURES:
        for base in HEADLINE_BASES + ("job",):
            h = result["headline"][measure][base]
            parts = []
            for group in ("strict_loss", "additional_below_half", "below_half_total"):
                m = h[group]["household_members"]
                lo, hi = m["interval_95"]
                parts.append(f"{group} {m['estimate'] / 1e6:.2f}M ({lo / 1e6:.2f}-{hi / 1e6:.2f})")
            print(f"{measure} {base}: " + "; ".join(parts))
    print(f"status {result['status']}; raise union exact: {result['reproduction']['raise_union_exact']}")
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
