"""Split the with-health strict-loss group by what happens to each person's public coverage.

With health coverage counted at government cost (``d_net_single_ptc``: the change in
household net income plus the marketplace net premium, so the premium tax credit counts
once), about 31.9 million people live in households that a raise or a job would leave
with less (the 51-jurisdiction combined union, run 1c0cc9ddcfd7d876). This module asks,
for each person whose health value falls in a strict scenario, whether their coverage
ended, moved or only shrank:

- (a) covered by a public program before and by none after;
- (b) covered before and after, but by a different primary program;
- (c) the same primary program before and after, with a lower modelled value, split
  into Medicaid/CHIP/MSP value changes (``c_mcm``) and falls in the premium credit, a
  state subsidy or a CHIP premium (``c_other``).

A person's primary program is the first they hold of Medicaid (``medicaid_enrolled``),
CHIP (``chip_enrolled``), a Medicare Savings Program (``msp_cost > 0``; MSP has no
enrolment variable), the premium credit (``is_aca_ptc_eligible`` in a tax unit with
``assigned_aca_ptc > 0``) and a state health program (a positive value in the person's
tax unit, or ``or_healthier_oregon_cost``). A person's health value is their own
``medicaid_cost``, ``chip`` and ``msp_cost`` plus their share of tax-unit amounts: the
credit split over the unit's credit-eligible members, state programs over all members,
and the CHIP premium (a cost) over the unit's CHIP enrollees. The shares add up to the
household's health value, so the people's changes add up to the household's.

The counterfactual adds back the Medicaid/CHIP/MSP change of every bucket (c) person
(``medicaid_cost + chip + msp_cost``, whose program did not change) and asks whether the
household still keeps less: a smaller premium credit, state subsidy or larger CHIP
premium stays a real loss. A sensitivity adds back every same-program Medicaid/CHIP/MSP
change in either direction, including in households that were not strict.

Three steps, the first and last on Modal (scripts/modal_coverage_split.py):

1. ``job_scenario`` / ``raise_scenario`` rerun one test of one household part exactly as
   the frozen experiment ran it, with the coverage and value of every member before and
   after, and stop unless every tested adult's household change reproduces the saved row
   to $0.01;
2. ``classify`` (local, light) assigns buckets, household categories and the
   counterfactual, and writes each part's flags;
3. ``aggregate_part`` counts them with MicroSeries in each part's frozen simulation, as
   the combined union does (household flags mapped to residents with
   ``map_to="person"``), and ``combine`` adds the parts in part order.

usage:
  python scripts/coverage_split.py classify [--job-root ...] [--raise-rows-root ...] [--union-root ...]
  python scripts/coverage_split.py combine --tag TAG
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import math
import resource
import sys
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import coverage_split_outputs as out  # noqa: E402

YEAR = out.YEAR
NET = "household_net_income"
PREMIUM = "marketplace_net_premium"
RESOURCES = "expanded_job_resources"
CHIP_PREMIUM = "chip_premium"
PTC = "assigned_aca_ptc"
MCM = ("medicaid_cost", "chip", "msp_cost")
PERSON_FLAGS = ("medicaid_enrolled", "is_medicaid_eligible", "chip_enrolled", "is_chip_eligible",
                "is_aca_ptc_eligible")
PERSON_ENUMS = ("medicaid_category", "medicaid_group", "chip_category")
MSP_CATEGORIES = ("QMB", "SLMB", "QI")
PROGRAMS = ("medicaid", "chip", "msp", "ptc", "state")  # precedence for the primary program
FALL = 0.005  # a value falls when it drops by more than half a cent
# Worst first: a person's bucket in a set is the worst over the set's strict scenarios.
BUCKETS = ("a", "b", "c_other", "c_mcm", "other")
# Worst first: a household's category in a set is the worst over its strict scenarios.
CATEGORIES = ("any_a", "b_no_a", "only_c_other", "only_c_mcm", "other_only", "no_fall")
DEFAULT_ROOTS = {
    # Where the frozen experiment's rows live. Each defaults to this checkout;
    # set CLIFFS_JOB_ROOT, CLIFFS_RAISE_ROWS_ROOT or CLIFFS_UNION_ROOT to point elsewhere.
    "job_root": os.environ.get("CLIFFS_JOB_ROOT", str(ROOT)),
    "raise_rows_root": os.environ.get("CLIFFS_RAISE_ROWS_ROOT", str(ROOT)),
    "union_root": os.environ.get("CLIFFS_UNION_ROOT", str(ROOT)),
}


# ---------------------------------------------------------------------------
# Container side: rerun one scenario with every member's coverage before and after


def peak_memory_gib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024**3 if sys.platform == "darwin" else 1024**2), 3)


def arr(sim, variable: str, period, map_to: str | None = None) -> np.ndarray:
    return np.asarray(sim.calculate(variable, period, map_to=map_to, use_weights=False, decode_enums=True))


def health_variables(sim, year: int = YEAR) -> dict:
    """The health benefits and costs net income counts, by entity (the marketplace premium is
    left out: the with-health measure cancels it)."""
    p = sim.tax_benefit_system.parameters(year)
    benefits = list(p.gov.household.household_health_benefits)
    costs = [c for c in p.gov.household.household_health_costs if c != PREMIUM]
    out_ = {"person": [], "tax_unit": [], "costs_tax_unit": []}
    for v in benefits:
        entity = sim.tax_benefit_system.variables[v].entity.key
        if entity not in ("person", "tax_unit"):
            raise ValueError(f"{v} is a {entity} variable; the split handles person and tax unit")
        out_[entity].append(v)
    for v in costs:
        if sim.tax_benefit_system.variables[v].entity.key != "tax_unit" or v != CHIP_PREMIUM:
            raise ValueError(f"unexpected health cost {v}")
        out_["costs_tax_unit"].append(v)
    for v in MCM:
        if v not in out_["person"]:
            raise ValueError(f"{v} is not a person-level health benefit")
    return out_


def person_arrays(sim, year: int, health: dict) -> dict:
    """Coverage and value of every person (tax-unit amounts mapped to each member)."""
    values = {}
    for v in PERSON_FLAGS:
        values[v] = arr(sim, v, year).astype(bool)
    for v in PERSON_ENUMS:
        values[v] = arr(sim, v, year).astype(str)
    for v in health["person"]:
        values[v] = arr(sim, v, year).astype(np.float64)
    for v in health["tax_unit"] + health["costs_tax_unit"]:
        values[f"tu_{v}"] = arr(sim, v, year, map_to="person").astype(np.float64)
    months = {c: np.zeros(len(values["medicaid_cost"]), dtype=np.int64) for c in MSP_CATEGORIES}
    for m in range(1, 13):
        period = f"{year}-{m:02d}"
        category = arr(sim, "msp_category", period).astype(str)
        unexpected = set(np.unique(category)) - {"NONE", *MSP_CATEGORIES}
        if unexpected:
            raise ValueError(f"msp_category decoded to {sorted(unexpected)}")
        paid = arr(sim, "msp_benefit_value", period) > 0
        for c in MSP_CATEGORIES:
            months[c] += (category == c) & paid
    for c in MSP_CATEGORIES:
        values[f"msp_{c.lower()}_months"] = months[c]
    return values


def _changed(base: dict, alt: dict) -> np.ndarray:
    changed = np.zeros(len(base["medicaid_cost"]), dtype=bool)
    for v in base:
        changed |= base[v] != alt[v]
    return changed


def _reproduce(merged: pd.DataFrame, strict_rerun: np.ndarray, strict_saved: np.ndarray,
               scenario: str) -> dict:
    """Stop unless every tested adult's household change matches the saved row to $0.01."""
    diff = (merged["d_with"] - merged["saved_d_with"]).abs().to_numpy()
    diff_without = (merged["d_without"] - merged["saved_d_without"]).abs().to_numpy()
    worst = float(diff.max()) if len(diff) else 0.0
    worst_strict = float(diff[strict_saved | strict_rerun].max()) if (strict_saved | strict_rerun).any() else 0.0
    worst_without = float(diff_without.max()) if len(diff_without) else 0.0
    same_strict = bool(np.array_equal(strict_rerun, strict_saved))
    ok = worst <= out.REPRODUCTION_TOLERANCE and worst_without <= out.REPRODUCTION_TOLERANCE and same_strict
    record = {
        "pass": ok,
        "tolerance": out.REPRODUCTION_TOLERANCE,
        "tested_adults_compared": int(len(merged)),
        "max_abs_difference_d_with": worst,
        "max_abs_difference_d_with_strict": worst_strict,
        "max_abs_difference_d_without": worst_without,
        "exact_d_with": bool(worst == 0.0),
        "strict_sets_equal": same_strict,
        "sample_strict_saved": int(strict_saved.sum()),
        "sample_strict_rerun": int(strict_rerun.sum()),
    }
    if not ok:
        bad = merged.assign(diff=diff).sort_values("diff", ascending=False).head(10)
        raise RuntimeError(f"{scenario}: the rerun does not reproduce the saved rows: {record}\n"
                           f"{bad[['person_index', 'person_id', 'd_with', 'saved_d_with', 'd_without', 'saved_d_without']]}")
    return record


def _rows(sim, branch_values: dict, base_values: dict, parts, health_set, tested: np.ndarray,
          extra: dict, base_people: dict, alt_people: dict, d_with: np.ndarray, d_without: np.ndarray,
          d_net: np.ndarray, year: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Tested-adult rows and member rows of every household that is strict or whose health moved."""
    household_index = np.asarray(sim.populations["household"].members_entity_id)
    tax_unit_index = np.asarray(sim.populations["tax_unit"].members_entity_id)
    person_id = arr(sim, "person_id", year)
    household_id = arr(sim, "household_id", year, map_to="person")
    state = arr(sim, "state_code_str", year, map_to="person").astype(str)
    age = arr(sim, "age", year)
    people = np.flatnonzero(tested)
    households = household_index[people]
    tested_rows = pd.DataFrame({
        "person_index": people,
        "person_id": person_id[people],
        "household_id": household_id[people],
        "household_index": households,
        "state_code": state[people],
        **{k: v[people] if isinstance(v, np.ndarray) and len(v) == len(tested) else v for k, v in extra.items()},
        "d_with": d_with[households],
        "d_without": d_without[households],
        "d_net": d_net[households],
    })
    for v, sign in parts:
        if f"d_{v}" in health_set:
            tested_rows[f"dh_{v}"] = (sign * (branch_values[v] - base_values[v]))[households]
    health_cols = [c for c in tested_rows.columns if c.startswith("dh_") and c != f"dh_{PREMIUM}"]
    gap = (tested_rows["d_with"] - tested_rows["d_without"] - tested_rows[health_cols].sum(axis=1)).abs()
    moved = np.zeros(len(d_with), dtype=bool)
    moved[household_index[_changed(base_people, alt_people)]] = True
    keep = np.zeros(len(d_with), dtype=bool)
    keep[households] = True
    keep &= moved | (d_with < 0)
    members = np.flatnonzero(keep[household_index])
    persons = pd.DataFrame({
        "person_index": members,
        "person_id": person_id[members],
        "household_id": household_id[members],
        "household_index": household_index[members],
        "tax_unit_index": tax_unit_index[members],
        "state_code": state[members],
        "age": age[members],
    })
    for v in base_people:
        persons[f"base_{v}"] = base_people[v][members]
        persons[f"alt_{v}"] = alt_people[v][members]
    checks = {"health_parts_vs_measure_max_abs_gap": float(gap.max()) if len(gap) else 0.0,
              "households_written": int(keep.sum()), "people_written": int(len(members))}
    if checks["health_parts_vs_measure_max_abs_gap"] > 1.0:
        raise RuntimeError(f"health parts do not add to d_with - d_without: {checks}")
    return tested_rows, persons, checks


def _saved_frame(rows: pd.DataFrame, change_column: str) -> pd.DataFrame:
    return rows.rename(columns={"d_net_single_ptc": "saved_d_with", "d_net_without_health": "saved_d_without",
                                change_column: "saved_change"})


def job_scenario(part: int, rank: int, pairs: list[tuple[bytes, bytes]], rates: dict, *, smoke: int = 0,
                 smoke_seed: int = 17, year: int = YEAR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """The job test at one candidate rank of one part, every jurisdiction (both wage scopes)."""
    import scripts.expanded_job_entry_national as national
    from cliffs2017.changes import health_parts
    from cliffs2017.decompose import components, household_values
    from scripts.expanded_job_entry import make_job_branch

    timing, started = {}, time.time()
    saved = []
    for record_bytes, rows_bytes in pairs:
        record = json.loads(record_bytes)
        if record["part"] != part or record["rank"] != rank:
            raise ValueError("job inputs of another part or rank")
        frame = pd.read_csv(io.BytesIO(rows_bytes), compression="gzip", dtype={"state_code": str},
                            keep_default_na=False)
        saved.append(frame.assign(scope=record["scope"]))
    saved = _saved_frame(pd.concat(saved, ignore_index=True), "gross_pay")
    if saved["person_id"].duplicated().any():
        raise ValueError("a candidate appears in two scopes")

    dataset = national.load_part(part)
    sample = None
    if smoke:
        dataset, sample = national.smoke_sample(dataset, smoke, smoke_seed)
    timing["load"] = round(time.time() - started, 1)
    t = time.time()
    sim = national.build(dataset)
    timing["build"] = round(time.time() - t, 1)

    t = time.time()
    c = national.candidates(sim, rates, "resolved", year)
    if not bool(np.asarray(c["in_scope"])[np.asarray(c["eligible"], dtype=bool)].all()):
        raise ValueError("a candidate's jurisdiction has no rate")
    selected = c["eligible"] & c["in_scope"] & (c["rank"] == rank)
    sel = np.asarray(selected, dtype=bool)
    person_id = arr(sim, "person_id", year)
    ours = set(person_id[sel].tolist())
    theirs = saved if not smoke else saved[saved["person_id"].isin(set(person_id.tolist()))]
    if ours != set(theirs["person_id"].tolist()):
        raise RuntimeError(f"part {part} rank {rank}: tested adults differ from the saved rows "
                           f"({len(ours)} here, {len(theirs)} saved)")
    parts = components(sim, year)
    names = [n for n, _ in parts]
    health = health_parts(sim, year)
    health_set = set(health)
    tracked = names + [NET, RESOURCES]
    base = household_values(sim, tracked, year)
    hv = health_variables(sim, year)
    base_people = person_arrays(sim, year, hv)
    timing["baseline"] = round(time.time() - t, 1)

    t = time.time()
    name, branch, gross = make_job_branch(sim, selected, c["hourly"], rank, year)
    alt = household_values(branch, tracked, year)
    alt_people = person_arrays(branch, year, hv)
    d = {v: alt[v] - base[v] for v in tracked}
    signed = {v: sign * d[v] for v, sign in parts}
    d_without = sum(signed[v] for v in names if f"d_{v}" not in health_set)
    gross_np = np.asarray(gross, dtype=np.float64)
    tested_rows, persons, checks = _rows(
        sim, alt, base, parts, health_set, sel, {"rank": rank, "gross_pay": gross_np},
        base_people, alt_people, d[RESOURCES], d_without, d[NET], year)
    del sim.branches[name], branch
    gc.collect()
    timing["branch"] = round(time.time() - t, 1)

    merged = tested_rows.merge(theirs[["person_id", "person_index", "household_id", "saved_d_with",
                                       "saved_d_without", "saved_change", "scope"]],
                               on="person_id", how="left", suffixes=("", "_saved"), validate="one_to_one")
    if not smoke and not (merged["person_index"] == merged["person_index_saved"]).all():
        raise RuntimeError("person_index differs from the saved rows")
    if not (merged["household_id"] == merged["household_id_saved"]).all():
        raise RuntimeError("household_id differs from the saved rows")
    pay_gap = float((merged["gross_pay"] - merged["saved_change"]).abs().max())
    if pay_gap > 1e-6:
        raise RuntimeError(f"gross pay differs from the saved rows by {pay_gap}")
    merged = merged.drop(columns=["person_index_saved", "household_id_saved", "saved_change"])
    merged["worker"] = True
    strict_rerun = (merged["d_with"] / merged["gross_pay"] < 0).to_numpy()
    strict_saved = (merged["saved_d_with"] / merged["gross_pay"] < 0).to_numpy()
    repro = _reproduce(merged, strict_rerun, strict_saved, f"part {part} job rank {rank}")
    merged["strict"] = strict_saved
    record = {
        "status": "complete",
        "test": "job",
        "part": part,
        "rank": rank,
        "smoke": bool(smoke),
        "smoke_sample": sample,
        "reproduction": repro,
        "checks": dict(checks, gross_pay_max_abs_gap=pay_gap),
        "health_variables": hv,
        "scopes": sorted(set(merged["scope"])),
        "sample_tested": int(len(merged)),
        "timing_seconds": timing,
    }
    return merged, persons, record


def raise_scenario(part: int, key: str, rank: int, rows_bytes: bytes, *, smoke: int = 0,
                   smoke_seed: int = 17, year: int = YEAR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """One raise at one adult rank of one part, as cliffs2017.changes.decompose_change builds it."""
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
        earnings_increments,
    )

    import scripts.expanded_job_entry_national as national
    from cliffs2017.changes import EARNINGS, health_parts, parse, person_changes, positive_earnings
    from cliffs2017.decompose import components, household_values
    from scripts.expanded_historical import build_historical_simulation, load_historical_dataset

    amount = out.RAISE_KEYS[key]
    change = parse(f"+{amount:g}")
    if change.key != key:
        raise ValueError(f"{key} parses as {change.key}")
    timing, started = {}, time.time()
    saved = pd.read_csv(io.BytesIO(rows_bytes), compression="gzip")
    saved = _saved_frame(saved[saved["rank"] == rank], "change")
    if saved.empty or not (saved["change_key"] == key).all():
        raise ValueError(f"saved rows for {key} rank {rank} are missing or mislabelled")

    dataset = load_historical_dataset(year, parts=out.PARTS, part=part, seed=out.SEED)
    sample = None
    if smoke:
        dataset, sample = national.smoke_sample(dataset, smoke, smoke_seed)
    timing["load"] = round(time.time() - started, 1)
    t = time.time()
    sim = build_historical_simulation(dataset, year, health=True)
    timing["build"] = round(time.time() - t, 1)

    t = time.time()
    p = sim.tax_benefit_system.parameters(year)
    if int(p.simulation.marginal_tax_rate_adults) < rank:
        raise ValueError("rank beyond the model's measured adults")
    parts = components(sim, year)
    names = [n for n, _ in parts]
    health = health_parts(sim, year)
    health_set = set(health)
    person = sim.populations["person"]
    adult_rank = np.asarray(sim.calculate("adult_earnings_index", year))
    is_adult = np.asarray(sim.calculate("is_adult", year)).astype(bool)
    earnings = positive_earnings(*(np.asarray(sim.calculate(v, year)) for v in EARNINGS))
    signed_earnings = sum(np.asarray(sim.calculate(v, year).values) for v in EARNINGS)
    base = household_values(sim, names + [NET], year)
    # decompose_change reads these before branching; keep the order.
    for v in ("aca_magi_fraction", PTC):
        sim.calculate(v, year, map_to="person")
    hv = health_variables(sim, year)
    base_people = person_arrays(sim, year, hv)
    timing["baseline"] = round(time.time() - t, 1)

    t = time.time()
    amounts = person_changes(change, is_adult & (adult_rank == rank), earnings)
    tested = amounts != 0
    person_id = arr(sim, "person_id", year)
    theirs = saved if not smoke else saved[saved["person_id"].isin(set(person_id.tolist()))]
    if set(person_id[tested].tolist()) != set(theirs["person_id"].tolist()):
        raise RuntimeError(f"part {part} {key} rank {rank}: tested adults differ from the saved rows")
    name = f"cliffs2017_change_{change.key}_adult_{rank}"
    branch = create_perturbed_branch(sim, year, name, earnings_increments(person, year, amounts))
    alt = household_values(branch, names + [NET], year)
    alt_people = person_arrays(branch, year, hv)
    household_index = np.asarray(sim.populations["household"].members_entity_id)
    people = np.flatnonzero(tested)
    households = household_index[people]
    frame = pd.DataFrame({"person_index": people})
    for v, sign in parts:
        frame[f"d_{v}"] = sign * (alt[v] - base[v])[households]
    frame["d_net"] = (alt[NET] - base[NET])[households]
    premium = f"d_{PREMIUM}"
    frame["d_net_single_ptc"] = frame["d_net"] - (frame[premium] if premium in frame else 0)
    keep = [c for c in frame.columns if c.startswith("d_") and c not in ("d_net", "d_parts", "d_net_single_ptc")
            and c not in health_set]
    frame["d_net_without_health"] = frame[keep].sum(axis=1)
    d_with = np.zeros(len(base[NET]))
    d_without = np.zeros(len(base[NET]))
    d_net = np.zeros(len(base[NET]))
    d_with[households] = frame["d_net_single_ptc"].to_numpy()
    d_without[households] = frame["d_net_without_health"].to_numpy()
    d_net[households] = frame["d_net"].to_numpy()
    tested_rows, persons, checks = _rows(
        sim, alt, base, parts, health_set, tested,
        {"rank": rank, "change": amounts, "worker": signed_earnings > 0},
        base_people, alt_people, d_with, d_without, d_net, year)
    del sim.branches[name], branch
    gc.collect()
    timing["branch"] = round(time.time() - t, 1)

    merged = tested_rows.merge(theirs[["person_id", "person_index", "household_id", "saved_d_with",
                                       "saved_d_without", "saved_change", "worker"]],
                               on="person_id", how="left", suffixes=("", "_saved"), validate="one_to_one")
    if not smoke and not (merged["person_index"] == merged["person_index_saved"]).all():
        raise RuntimeError("person_index differs from the saved rows")
    if not (merged["household_id"] == merged["household_id_saved"]).all():
        raise RuntimeError("household_id differs from the saved rows")
    if not (merged["worker"] == merged["worker_saved"]).all():
        raise RuntimeError("worker flags differ from the saved rows")
    change_gap = float((merged["change"] - merged["saved_change"]).abs().max())
    if change_gap > 1e-9:
        raise RuntimeError(f"raise sizes differ from the saved rows by {change_gap}")
    merged = merged.drop(columns=["person_index_saved", "household_id_saved", "saved_change", "worker_saved"])
    worker = merged["worker"].to_numpy(dtype=bool)
    strict_rerun = (merged["d_with"] / merged["change"] < 0).to_numpy() & worker
    strict_saved = (merged["saved_d_with"] / merged["change"] < 0).to_numpy() & worker
    repro = _reproduce(merged, strict_rerun, strict_saved, f"part {part} {key} rank {rank}")
    merged["strict"] = strict_saved
    record = {
        "status": "complete",
        "test": key,
        "part": part,
        "rank": rank,
        "smoke": bool(smoke),
        "smoke_sample": sample,
        "reproduction": repro,
        "checks": dict(checks, raise_size_max_abs_gap=change_gap),
        "health_variables": hv,
        "sample_tested": int(len(merged)),
        "timing_seconds": timing,
    }
    return merged, persons, record


def serialize(tested: pd.DataFrame, persons: pd.DataFrame, record: dict, part: int, test: str, rank: int,
              run_id: str, smoke: int, extra: dict) -> tuple[bytes, bytes, bytes]:
    from scripts.job_entry_outputs import csv_gzip

    blobs = {}
    for kind, frame in (("tested", tested), ("persons", persons)):
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        blobs[kind] = csv_gzip(buffer.getvalue())
    record = dict(record, **extra, run_id=run_id, peak_memory_gib=peak_memory_gib())
    record["rows"] = {
        kind: {"file": out.scenario_rows(part, test, rank, run_id, kind, smoke),
               "sha256": out.sha256(blobs[kind]), "count": len(frame), "columns": list(frame.columns),
               "record_level": "git-ignored; never commit"}
        for kind, frame in (("tested", tested), ("persons", persons))
    }
    json_bytes = (json.dumps(record, indent=1, default=_json_scalar) + "\n").encode()
    out.validate_scenario(json_bytes, blobs["tested"], blobs["persons"])
    return json_bytes, blobs["tested"], blobs["persons"]


def _json_scalar(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot serialize {type(value).__name__}")


# ---------------------------------------------------------------------------
# Local: classify people and households (unweighted, pure pandas)


def person_values(persons: pd.DataFrame, when: str, person_benefits: list[str], tu_benefits: list[str],
                  tu_costs: list[str]) -> pd.DataFrame:
    """Each person's primary program and health value at baseline (``base``) or after (``alt``).

    Tax-unit amounts are shared out so they add up to the unit's: the premium credit over the
    unit's credit-eligible members, state programs over every member, the CHIP premium over
    the unit's CHIP enrollees (each over every member when nobody qualifies).
    """
    def col(v):
        return persons[f"{when}_{v}"]

    tu = persons["tax_unit_index"]
    size = tu.map(tu.value_counts())
    medicaid = col("medicaid_enrolled").astype(bool)
    chip_cov = col("chip_enrolled").astype(bool)
    msp_cov = col("msp_cost") > 0
    ptc_total = col(f"tu_{PTC}") if PTC in tu_benefits else pd.Series(0.0, index=persons.index)
    ptc_eligible = col("is_aca_ptc_eligible").astype(bool) & (ptc_total > 0)
    n_ptc = ptc_eligible.groupby(tu).transform("sum")
    ptc_fallback = (ptc_total > 0) & (n_ptc == 0)
    ptc_cov = ptc_eligible | ptc_fallback
    ptc_share = np.where(n_ptc > 0, ptc_total * ptc_eligible / n_ptc.where(n_ptc > 0, 1), ptc_total / size)
    state_tu = sum((col(f"tu_{v}") for v in tu_benefits if v != PTC), pd.Series(0.0, index=persons.index))
    state_person = sum((col(v) for v in person_benefits if v not in MCM), pd.Series(0.0, index=persons.index))
    state_cov = (state_tu > 0) | (state_person > 0)
    cost_total = sum((col(f"tu_{v}") for v in tu_costs), pd.Series(0.0, index=persons.index))
    n_chip = chip_cov.groupby(tu).transform("sum")
    cost_share = np.where(n_chip > 0, cost_total * chip_cov / n_chip.where(n_chip > 0, 1), cost_total / size)
    mcm = col("medicaid_cost") + col("chip") + col("msp_cost")
    value = mcm + state_person + ptc_share + state_tu / size - cost_share
    covered = pd.DataFrame({"medicaid": medicaid, "chip": chip_cov, "msp": msp_cov, "ptc": ptc_cov,
                            "state": state_cov})
    primary = pd.Series("", index=persons.index, dtype=object)
    programs = pd.Series("", index=persons.index, dtype=object)
    for program in reversed(PROGRAMS):
        primary = primary.mask(covered[program], program)
    for program in PROGRAMS:
        programs = programs + np.where(covered[program].to_numpy(), program + "+", "")
    return pd.DataFrame({
        "primary": primary,
        "programs": programs.str.rstrip("+"),
        "value": value.astype(np.float64),
        "mcm": mcm.astype(np.float64),
        "ptc_share": pd.Series(ptc_share, index=persons.index, dtype=np.float64),
        "cost_share": pd.Series(cost_share, index=persons.index, dtype=np.float64),
        "ptc_fallback": ptc_fallback,
    }, index=persons.index)


def classify_persons(persons: pd.DataFrame, health: dict) -> pd.DataFrame:
    """Bucket, value change and counterfactual add-backs for every person row."""
    lists = (health["person"], health["tax_unit"], health["costs_tax_unit"])
    before = person_values(persons, "base", *lists)
    after = person_values(persons, "alt", *lists)
    delta = after["value"] - before["value"]
    mcm_delta = after["mcm"] - before["mcm"]
    other_delta = delta - mcm_delta
    falls = delta < -FALL
    had, has = before["primary"] != "", after["primary"] != ""
    same = before["primary"] == after["primary"]
    bucket = pd.Series("none", index=persons.index, dtype=object)
    bucket[falls & ~had] = "other"
    bucket[falls & had & ~has] = "a"
    bucket[falls & had & has & ~same] = "b"
    c = falls & had & has & same
    c_mcm = c & (mcm_delta < -FALL) & (mcm_delta <= other_delta)
    bucket[c & c_mcm] = "c_mcm"
    bucket[c & ~c_mcm] = "c_other"
    same_mcm_program = same & before["primary"].isin(["medicaid", "chip", "msp"])
    return pd.DataFrame({
        "person_index": persons["person_index"].to_numpy(),
        "household_index": persons["household_index"].to_numpy(),
        "state_code": persons["state_code"].to_numpy(),
        "primary_base": before["primary"].to_numpy(),
        "primary_alt": after["primary"].to_numpy(),
        "programs_base": before["programs"].to_numpy(),
        "programs_alt": after["programs"].to_numpy(),
        "value_base": before["value"].to_numpy(),
        "value_alt": after["value"].to_numpy(),
        "delta": delta.to_numpy(),
        "mcm_delta": mcm_delta.to_numpy(),
        "other_delta": other_delta.to_numpy(),
        "bucket": bucket.to_numpy(),
        # Primary counterfactual: zero the Medicaid/CHIP/MSP change of every bucket (c) person.
        "addback": np.where(c.to_numpy(), -mcm_delta.to_numpy(), 0.0),
        # Sensitivity: zero every same-program Medicaid/CHIP/MSP change, either direction.
        "addback_both_signs": np.where(same_mcm_program.to_numpy(), -mcm_delta.to_numpy(), 0.0),
        "ptc_fallback": (before["ptc_fallback"] | after["ptc_fallback"]).to_numpy(),
    })


def household_category(buckets: pd.Series) -> str:
    """A strict household's category from its members' buckets in one scenario."""
    present = set(buckets)
    if "a" in present:
        return "any_a"
    if "b" in present:
        return "b_no_a"
    if "c_other" in present:
        return "only_c_other"
    if "c_mcm" in present:
        return "only_c_mcm"
    if "other" in present:
        return "other_only"
    return "no_fall"


def retention_below_zero(change, d) -> np.ndarray:
    """The union's strict test, ``d / change < 0`` (scripts/expanded_raise_union.retention_flags)."""
    from scripts.expanded_raise_union import retention_flags

    return retention_flags(change, d, 0)


def scenario_households(tested: pd.DataFrame, classified: pd.DataFrame, change_column: str) -> pd.DataFrame:
    """One row per tested household: strict, category, and strict after each counterfactual."""
    change = tested[change_column].to_numpy(dtype=float)
    worker = tested["worker"].to_numpy(dtype=bool)
    strict = retention_below_zero(change, tested["saved_d_with"]) & worker
    if not np.array_equal(strict, tested["strict"].to_numpy(dtype=bool)):
        raise ValueError("strict flags differ from the scenario record")
    sums = classified.groupby("household_index")[["addback", "addback_both_signs"]].sum()
    categories = classified.groupby("household_index")["bucket"].agg(household_category)
    households = tested["household_index"].to_numpy()
    missing = set(households[strict]) - set(classified["household_index"])
    if missing:
        raise ValueError(f"{len(missing)} strict households have no member rows")
    addback = sums["addback"].reindex(households, fill_value=0.0).to_numpy()
    addback_both = sums["addback_both_signs"].reindex(households, fill_value=0.0).to_numpy()
    d = tested["saved_d_with"].to_numpy(dtype=float)
    return pd.DataFrame({
        "household_index": households,
        "person_index": tested["person_index"].to_numpy(),
        "strict": strict,
        "category": np.where(strict, categories.reindex(households, fill_value="no_fall").to_numpy(), ""),
        "d_with": d,
        "addback": addback,
        "strict_after_counterfactual": strict & (retention_below_zero(change, d + addback)),
        "strict_after_both_signs": worker & retention_below_zero(change, d + addback_both),
    })


def check_household_sums(tested: pd.DataFrame, classified: pd.DataFrame, persons: pd.DataFrame,
                         health: dict) -> dict:
    """People's changes in each Medicaid/CHIP/MSP value add up to their household's."""
    worst = {}
    by_household = persons.groupby("household_index")
    for v in MCM:
        people = (persons[f"alt_{v}"] - persons[f"base_{v}"]).groupby(persons["household_index"]).sum()
        household = tested.set_index("household_index")[f"dh_{v}"]
        common = household.index.intersection(people.index)
        gap = (people.reindex(common) - household.reindex(common)).abs()
        outside = household.drop(common, errors="ignore").abs()
        worst[v] = float(max(gap.max() if len(gap) else 0.0, outside.max() if len(outside) else 0.0))
    total = classified.groupby("household_index")["delta"].sum()
    health_cols = [f"dh_{v}" for v in health["person"] + health["tax_unit"]] + [
        f"dh_{v}" for v in health["costs_tax_unit"]]
    household = tested.set_index("household_index")[health_cols].sum(axis=1)
    common = household.index.intersection(total.index)
    worst["all_health"] = float((total.reindex(common) - household.reindex(common)).abs().max()) if len(common) else 0.0
    del by_household
    return worst


def classify_scenario(record: dict, tested: pd.DataFrame, persons: pd.DataFrame) -> dict:
    health = record["health_variables"]
    classified = classify_persons(persons, health)
    change_column = "gross_pay" if record["test"] == "job" else "change"
    households = scenario_households(tested, classified, change_column)
    sums = check_household_sums(tested, classified, persons, health)
    if max(sums.values()) > 0.10:
        raise ValueError(f"{record['test']} part {record['part']} rank {record['rank']}: person changes do not "
                         f"add up to the household's: {sums}")
    return {"classified": classified, "households": households, "sum_checks": sums}


# ---------------------------------------------------------------------------
# Local: sets across scenarios


def worst(values, order) -> str:
    rank = {v: i for i, v in enumerate(order)}
    return min(values, key=lambda v: rank[v])


def set_flags(scenarios: dict) -> dict:
    """Household and person flags for each test set, from every scenario of one part.

    ``scenarios`` maps (test, rank) to classify_scenario output. A household is strict in a
    set when it is strict in any of the set's scenarios; its category is the worst over
    those; it stays strict after a counterfactual when any of those stays strict. A
    person's bucket is the worst over the strict scenarios of the set.
    """
    out_ = {}
    for name, tests in out.SETS.items():
        rows = [s["households"].assign(test=test, rank=rank) for (test, rank), s in scenarios.items()
                if test in tests]
        hh = pd.concat(rows, ignore_index=True)
        strict_rows = hh[hh["strict"]]
        strict_households = sorted(set(strict_rows["household_index"]))
        category = strict_rows.groupby("household_index")["category"].agg(lambda v: worst(v, CATEGORIES))
        cf = strict_rows.groupby("household_index")["strict_after_counterfactual"].any()
        sens = hh.groupby("household_index")["strict_after_both_signs"].any()
        person_rows = []
        for (test, rank), s in scenarios.items():
            if test not in tests:
                continue
            strict_hh = set(s["households"].loc[s["households"]["strict"], "household_index"])
            cls = s["classified"]
            person_rows.append(cls[cls["household_index"].isin(strict_hh) & (cls["bucket"] != "none")])
        people = pd.concat(person_rows, ignore_index=True)
        bucket = people.groupby("person_index")["bucket"].agg(lambda v: worst(v, BUCKETS))
        out_[name] = {
            "strict_adults": sorted(set(strict_rows["person_index"].tolist())),
            "strict_households": strict_households,
            "category": {c: sorted(category.index[category == c].tolist()) for c in CATEGORIES},
            "strict_after_counterfactual": sorted(cf.index[cf].tolist()),
            "strict_after_both_signs": sorted(sens.index[sens].tolist()),
            "person_bucket": {b: sorted(bucket.index[bucket == b].tolist()) for b in BUCKETS},
        }
        assigned = sorted(i for c in CATEGORIES for i in out_[name]["category"][c])
        if assigned != strict_households:
            raise ValueError(f"{name}: categories do not partition the strict households")
        if not set(out_[name]["strict_after_counterfactual"]) <= set(strict_households):
            raise ValueError(f"{name}: the counterfactual added a household")
    return out_


def union_strict_adults(inputs: dict) -> dict:
    """The union's strict adults per set, recomputed from the saved rows (person indices)."""
    from scripts.expanded_raise_union import retention_flags

    tests = {}
    for key, data in inputs["raise"].items():
        frame = pd.read_csv(io.BytesIO(data), compression="gzip",
                            usecols=["person_index", "change", "worker", "d_net_single_ptc"])
        flags = retention_flags(frame["change"], frame["d_net_single_ptc"], 0, frame["worker"])
        tests[key] = set(frame.loc[flags, "person_index"].tolist())
    job = set()
    for pairs in inputs["job"].values():
        for _, rows_bytes in pairs:
            frame = pd.read_csv(io.BytesIO(rows_bytes), compression="gzip",
                                usecols=["person_index", "gross_pay", "d_net_single_ptc"])
            job |= set(frame.loc[retention_flags(frame["gross_pay"], frame["d_net_single_ptc"], 0),
                                 "person_index"].tolist())
    tests["job"] = job
    return {name: sorted(set().union(*(tests[t] for t in members))) for name, members in out.SETS.items()}


def summarize_scenarios(scenarios: dict) -> dict:
    """Unweighted sample tallies of one part (aggregates only)."""
    tally = {}
    for (test, rank), s in scenarios.items():
        hh = s["households"]
        strict_hh = set(hh.loc[hh["strict"], "household_index"])
        cls = s["classified"]
        fallers = cls[cls["household_index"].isin(strict_hh) & (cls["bucket"] != "none")]
        transitions = (fallers["primary_base"].replace("", "none") + ">" + fallers["primary_alt"].replace("", "none"))
        c_mcm = fallers[fallers["bucket"] == "c_mcm"]
        tally[f"{test}|rank_{rank:02d}"] = {
            "strict_households": int(len(strict_hh)),
            "categories": {c: int((hh.loc[hh["strict"], "category"] == c).sum()) for c in CATEGORIES},
            "strict_after_counterfactual": int(hh["strict_after_counterfactual"].sum()),
            "fallers_by_bucket": {b: int((fallers["bucket"] == b).sum()) for b in BUCKETS},
            "transitions": {k: int(v) for k, v in transitions.value_counts().items()},
            "c_mcm_by_state": {k: int(v) for k, v in c_mcm["state_code"].value_counts().items()},
            "ptc_share_fallbacks": int(cls["ptc_fallback"].sum()),
            "sum_checks_max_abs": s["sum_checks"],
        }
    return tally


def load_scenarios(root: Path, part: int, labels: list[tuple[str, int]]) -> dict:
    """Validated scenario records and rows of one part, keyed by (test, rank)."""
    loaded = {}
    for test, rank in labels:
        rel = out.scenario_json(part, test, rank)
        record = out.local_scenario(root, rel)
        if record is None:
            raise FileNotFoundError(f"{rel} has no validated result")
        tested = pd.read_csv(root / record["rows"]["tested"]["file"], compression="gzip",
                             dtype={"state_code": str}, keep_default_na=False)
        persons = pd.read_csv(root / record["rows"]["persons"]["file"], compression="gzip",
                              dtype={"state_code": str}, keep_default_na=False)
        for column in persons.columns:
            if column.endswith(tuple(PERSON_ENUMS)):
                persons[column] = persons[column].astype(str)
        loaded[test, rank] = (record, tested, persons)
    return loaded


def scenario_labels(manifest: dict, part: int, tests: tuple[str, ...]) -> list[tuple[str, int]]:
    labels = []
    if "job" in tests:
        ranks = sorted({e["rank"] for e in manifest["inputs"] if e["part"] == part and e["kind"] == "job_record"})
        labels += [("job", r) for r in ranks]
    labels += [(k, r) for k in out.RAISE_KEYS if k in tests for r in out.RAISE_RANKS]
    return labels


def classify_part(root: Path, part: int, manifest: dict, job_root: Path, raise_rows_root: Path,
                  union_root: Path, tests: tuple[str, ...]) -> dict:
    labels = scenario_labels(manifest, part, tests)
    loaded = load_scenarios(root, part, labels)
    scenarios = {k: classify_scenario(*v) for k, v in loaded.items()}
    payload = {"part": part, "tests": list(tests), "scenarios": [list(k) for k in labels],
               "sample": summarize_scenarios(scenarios)}
    if set(tests) == {"job", *out.RAISE_KEYS}:
        flags = set_flags(scenarios)
        inputs = out.part_inputs(manifest, part, job_root, raise_rows_root)
        union = union_strict_adults(inputs)
        for name in out.SETS:
            if flags[name]["strict_adults"] != union[name]:
                raise ValueError(f"part {part} {name}: strict adults differ from the saved rows")
        reference = out.union_part_record(union_root, part)
        payload["sets"] = flags
        payload["reference"] = {name: reference["metrics"][f"with_health|{name}|retains_lt_0pct"]
                                for name in out.SETS}
        payload["reference_sample_households"] = {
            name: reference["sample_households"][f"with_health|{name}|retains_lt_0pct"] for name in out.SETS}
        for name in out.SETS:
            ours = len(flags[name]["strict_households"])
            if ours != payload["reference_sample_households"][name]:
                raise ValueError(f"part {part} {name}: {ours} strict sample households, the union has "
                                 f"{payload['reference_sample_households'][name]}")
    return payload


# ---------------------------------------------------------------------------
# Container side: weighted counts with MicroSeries in each part's frozen simulation


def aggregate_part(part: int, payload: dict, year: int = YEAR) -> dict:
    from scripts.expanded_combined_union import PartCounter, part_identities
    from scripts.expanded_raise_union import historical_part

    started = time.time()
    dataset, simulation = historical_part(year, out.PARTS, part, out.SEED)
    part_identities(simulation, dataset, year)
    counter = PartCounter(simulation, year, "cs", per_source=False)
    people = counter.people
    household_index = counter.household_index

    def person_mask(indices) -> np.ndarray:
        mask = np.zeros(people, dtype=bool)
        mask[np.asarray(indices, dtype=np.int64)] = True
        return mask

    def household_mask(indices) -> np.ndarray:
        chosen = np.zeros(counter.households, dtype=bool)
        chosen[np.asarray(indices, dtype=np.int64)] = True
        return chosen[household_index]

    reproduction = {}
    for name, flags in payload["sets"].items():
        person, household = counter.person_flag(f"{name}_strict", person_mask(flags["strict_adults"]))
        counts = counter.record(f"{name}|strict", household, person=person)
        strict_households = np.flatnonzero(counter.households_of(household))
        if strict_households.tolist() != flags["strict_households"]:
            raise ValueError(f"part {part} {name}: strict households differ from the classified ones")
        reference = payload["reference"][name]
        gaps = {f: abs(counts[f] - reference[f]) for f in ("adults", "households", "household_members")}
        if any(not math.isclose(counts[f], reference[f], rel_tol=1e-9, abs_tol=1e-6) for f in gaps):
            raise ValueError(f"part {part} {name}: strict counts {counts} differ from the union's {reference}")
        reproduction[name] = {"pass": True, "exact": all(g == 0.0 for g in gaps.values()), "max_abs_gap": max(gaps.values())}
        groups = {c: flags["category"][c] for c in CATEGORIES}
        groups["only_c"] = flags["category"]["only_c_other"] + flags["category"]["only_c_mcm"]
        groups["strict_after_counterfactual"] = flags["strict_after_counterfactual"]
        groups["strict_after_both_signs"] = flags["strict_after_both_signs"]
        for label, households in groups.items():
            person, household = counter.person_flag(f"{name}_hh_{label}", household_mask(households))
            counter.record(f"{name}|{label}", household, person=person)
            if counter.sample[f"{name}|{label}"] != len(set(households)):
                raise ValueError(f"part {part} {name} {label}: sample households differ")
        for bucket, persons in flags["person_bucket"].items():
            person, household = counter.person_flag(f"{name}_person_{bucket}", person_mask(persons))
            counter.record(f"{name}|person_{bucket}", household, person=person)
        total = sum(counter.metrics[f"{name}|{c}"]["household_members"] for c in CATEGORIES)
        if not math.isclose(total, counts["household_members"], rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(f"part {part} {name}: categories add to {total}, strict is {counts['household_members']}")
    sample_people = {name: {b: len(v) for b, v in flags["person_bucket"].items()}
                     for name, flags in payload["sets"].items()}
    from scripts.expanded_historical import historical_provenance

    return {
        "status": "complete",
        "part": part,
        "metrics": counter.metrics,
        "sample_households": counter.sample,
        "sample_people_by_bucket": sample_people,
        "union_reproduction": reproduction,
        "runtime": {"historical_loader": historical_provenance(), "seconds": round(time.time() - started, 1),
                    "peak_memory_gib": peak_memory_gib()},
    }


# ---------------------------------------------------------------------------
# Local: national totals


def combine(root: Path, tag: str, union_root: Path) -> dict:
    from scripts.expanded_combined_union import add_in_order

    records = []
    for part in range(out.PARTS):
        record = json.loads((root / out.aggregate_json(part, tag)).read_text())
        if record.get("status") != "complete" or record["part"] != part:
            raise ValueError(f"part {part}: aggregate record incomplete")
        if not all(r["pass"] for r in record["union_reproduction"].values()):
            raise ValueError(f"part {part}: union reproduction failed")
        records.append(record)
    labels = sorted(records[0]["metrics"])
    totals = {label: {f: add_in_order(r["metrics"][label][f] for r in records)
                      for f in sorted(records[0]["metrics"][label])} for label in labels}
    sample_hh = {label: sum(r["sample_households"][label] for r in records) for label in labels}
    final = json.loads((Path(union_root) / "results/combined_union/final/"
                        "expanded_combined_union_2017_all_scopes_1c0cc9dd.json").read_text())
    reproduction = {}
    for name in out.SETS:
        ours = totals[f"{name}|strict"]
        theirs = final["metrics"][f"with_health|{name}|retains_lt_0pct"]
        reproduction[name] = {f: {"ours": ours[f], "union": theirs[f], "exact": ours[f] == theirs[f]}
                              for f in ("adults", "households", "household_members")}
        if not all(math.isclose(ours[f], theirs[f], rel_tol=1e-9, abs_tol=1e-6) for f in theirs):
            raise ValueError(f"{name}: national strict counts differ from the union's")
        if sample_hh[f"{name}|strict"] != final["sample_households"][f"with_health|{name}|retains_lt_0pct"]:
            raise ValueError(f"{name}: strict sample households differ from the union's")
    sets = {}
    for name in out.SETS:
        strict = totals[f"{name}|strict"]["household_members"]

        def members(label):
            return totals[f"{name}|{label}"]["household_members"]

        cats = {c: members(c) for c in CATEGORIES}
        if not math.isclose(sum(cats.values()), strict, rel_tol=1e-9):
            raise ValueError(f"{name}: categories do not add to strict")
        sets[name] = {
            "strict": strict,
            "any_a": cats["any_a"],
            "b_no_a": cats["b_no_a"],
            "only_c": members("only_c"),
            "only_c_mcm": cats["only_c_mcm"],
            "only_c_other": cats["only_c_other"],
            "other_only": cats["other_only"],
            "no_health_fall": cats["no_fall"],
            "strict_after_zeroing_c": members("strict_after_counterfactual"),
            "strict_after_zeroing_all_same_program_mcm_changes": members("strict_after_both_signs"),
            "households": {k: totals[f"{name}|{k}"]["households"] for k in
                           ("strict", *CATEGORIES, "only_c", "strict_after_counterfactual", "strict_after_both_signs")},
            "sample_households": {k: sample_hh[f"{name}|{k}"] for k in
                                  ("strict", *CATEGORIES, "only_c", "strict_after_counterfactual",
                                   "strict_after_both_signs")},
            "people_by_bucket": {
                b: {"weighted_people": totals[f"{name}|person_{b}"]["adults"],
                    "weighted_members_of_their_households": totals[f"{name}|person_{b}"]["household_members"],
                    "sample_people": sum(r["sample_people_by_bucket"][name][b] for r in records)}
                for b in BUCKETS
            },
        }
    return {"totals": totals, "sample_households": sample_hh, "sets": sets, "reproduction": reproduction,
            "parts": [{"part": r["part"], "union_reproduction": r["union_reproduction"], "runtime": r["runtime"],
                       "app_id": r.get("modal", {}).get("app_id")} for r in records]}


def add_tallies(a, b):
    """Add two nested count dictionaries key by key (a missing key counts zero)."""
    if isinstance(a, dict) or isinstance(b, dict):
        a, b = a or {}, b or {}
        return {k: add_tallies(a.get(k), b.get(k)) for k in sorted(set(a) | set(b))}
    return (a or 0) + (b or 0)


def scenario_reproduction(root: Path, manifest: dict) -> dict:
    """The worst reproduction gaps over every installed scenario record."""
    worst = {"max_abs_difference_d_with": 0.0, "max_abs_difference_d_with_strict": 0.0,
             "max_abs_difference_d_without": 0.0, "scenarios": 0, "tested_adults_compared": 0,
             "every_scenario_exact_d_with": True, "every_strict_set_equal": True}
    tests = ("job", *out.RAISE_KEYS)
    for part in range(out.PARTS):
        for test, rank in scenario_labels(manifest, part, tests):
            record = out.local_scenario(root, out.scenario_json(part, test, rank))
            if record is None:
                raise FileNotFoundError(f"part {part} {test} rank {rank}: no validated scenario")
            r = record["reproduction"]
            for k in ("max_abs_difference_d_with", "max_abs_difference_d_with_strict", "max_abs_difference_d_without"):
                worst[k] = max(worst[k], r[k])
            worst["scenarios"] += 1
            worst["tested_adults_compared"] += r["tested_adults_compared"]
            worst["every_scenario_exact_d_with"] &= r["exact_d_with"]
            worst["every_strict_set_equal"] &= r["strict_sets_equal"]
    return worst


def write_final(root: Path, tag: str, union_root: Path) -> dict:
    import subprocess

    manifest = out.union_manifest(union_root)
    national = combine(root, tag, union_root)
    tallies = {}
    for part in range(out.PARTS):
        payload = json.loads((root / out.classified_json(part)).read_text())
        sample = {k: {kk: vv for kk, vv in v.items() if kk != "sum_checks_max_abs"} for k, v in payload["sample"].items()}
        tallies = add_tallies(tallies, sample)
    result = {
        "status": "complete_unreviewed",
        "year": YEAR,
        "question": "For people in households a raise or a job would leave worse off with health coverage "
                    "counted (with_health strict), did public coverage end, move to another program, or only "
                    "shrink within the same program?",
        "union_run": out.UNION_TAG,
        "measure": "with_health: change in household_net_income + marketplace_net_premium (health coverage at "
                   "government cost, premium tax credit counted once); a household is strict when a tested "
                   "adult's household keeps strictly less than 0% of the gross change (current workers only for "
                   "raises).",
        "definitions": {
            "primary_program": "first of medicaid (medicaid_enrolled), chip (chip_enrolled), msp (msp_cost > 0), "
                               "ptc (is_aca_ptc_eligible in a tax unit with assigned_aca_ptc > 0), state (a "
                               "positive state health program in the tax unit, or or_healthier_oregon_cost)",
            "health_value": "medicaid_cost + chip + msp_cost of the person, plus shares of tax-unit amounts: "
                            "assigned_aca_ptc over credit-eligible members, state programs over all members, "
                            "minus chip_premium over CHIP enrollees; shares add up to the household's health value",
            "falls": f"health value drops by more than ${FALL}",
            "a": "covered before, no primary program after",
            "b": "covered before and after, different primary program",
            "c_mcm": "same primary program, value lower, mainly through medicaid_cost, chip or msp_cost",
            "c_other": "same primary program, value lower, mainly through the premium credit, a state program or "
                       "the CHIP premium",
            "other": "value fell with no program before (a CHIP premium share); counted apart",
            "household_categories": "a strict household's category in a set is the worst over its strict "
                                    "scenarios: any_a > b_no_a > only_c_other > only_c_mcm > other_only > "
                                    "no_fall; only_c = only_c_other + only_c_mcm",
            "person_buckets": "a person's bucket in a set is the worst over the set's strict scenarios: "
                              "a > b > c_other > c_mcm > other",
            "strict_after_zeroing_c": "household members still strict after adding back the "
                                      "medicaid_cost + chip + msp_cost change of every bucket (c) person; premium "
                                      "credit, state subsidy and CHIP premium changes stay",
            "strict_after_zeroing_all_same_program_mcm_changes": "sensitivity: add back every same-program "
                                                                 "Medicaid/CHIP/MSP change in either direction, "
                                                                 "including in households that were not strict",
        },
        "totals": national["sets"],
        "reproduction": {
            "union_strict_national": national["reproduction"],
            "union_strict_parts": [p["union_reproduction"] for p in national["parts"]],
            "scenarios_vs_saved_rows": scenario_reproduction(root, manifest),
        },
        "sample_tallies_by_scenario": tallies,
        "metrics": national["totals"],
        "aggregation": "MicroSeries.sum on analysis flags in each part's frozen simulation; household flags "
                       "mapped to residents with map_to='person'; parts added in part order. Stored weight "
                       "columns are not read.",
        "code": {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                 "aggregate_tag": tag},
        "modal": {"app": "us-cliffs-2017-coverage-split", "volume": "us-cliffs-2017-coverage-split",
                  "parts": national["parts"]},
    }
    path = root / out.FINAL_JSON
    path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify", help="classify the installed scenarios and write each part's flags")
    for name, default in DEFAULT_ROOTS.items():
        c.add_argument(f"--{name.replace('_', '-')}", default=default)
    c.add_argument("--tests", default="job,raise_1000,raise_2000,raise_5000")
    c.add_argument("--parts", default="0,1,2,3")
    f = sub.add_parser("combine", help="add the aggregate records and write results/coverage_split_2017.json")
    f.add_argument("--tag", required=True)
    f.add_argument("--union-root", default=DEFAULT_ROOTS["union_root"])
    args = parser.parse_args()
    if args.command == "combine":
        result = write_final(ROOT, args.tag, Path(args.union_root))
        for name, entry in result["totals"].items():
            print(f"{name}: strict {entry['strict']:,.0f}; any a {entry['any_a']:,.0f}; b no a {entry['b_no_a']:,.0f}; "
                  f"only c {entry['only_c']:,.0f}; no health fall {entry['no_health_fall']:,.0f}; "
                  f"strict after zeroing c {entry['strict_after_zeroing_c']:,.0f}")
        print(f"wrote {out.FINAL_JSON}")
        return 0
    if args.command == "classify":
        manifest = out.union_manifest(Path(args.union_root))
        tests = tuple(t for t in args.tests.split(","))
        summary = {}
        for part in (int(p) for p in args.parts.split(",")):
            payload = classify_part(ROOT, part, manifest, Path(args.job_root), Path(args.raise_rows_root),
                                    Path(args.union_root), tests)
            summary[part] = payload["sample"]
            if "sets" in payload:
                path = ROOT / out.classified_json(part)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload) + "\n")
                print(f"part {part}: wrote {path.relative_to(ROOT)}")
            for key, entry in payload["sample"].items():
                print(f"part {part} {key}: strict {entry['strict_households']}, {entry['categories']}, "
                      f"cf {entry['strict_after_counterfactual']}, buckets {entry['fallers_by_bucket']}")
        path = ROOT / out.BASE / f"classified/sample_{'_'.join(tests)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=1) + "\n")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
