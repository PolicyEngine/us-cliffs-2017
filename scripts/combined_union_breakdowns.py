"""Breakdowns of the combined raise-and-job union under 2017 rules, for the methodology note.

The union (scripts/expanded_combined_union.py, COMBINED_UNION.md) counts people in
households that trip the raise test, the job test, or either. This script splits its
groups for the note, with health coverage counted unless a label says otherwise:

1. Candidate pool: the adults the job test covers (aged 18-64, no wages or
   self-employment income, not full-time students, not reporting disability), the
   households holding one and their members; split by candidate rank, by age 62-64
   and by the state's Medicaid expansion status.
2. Ranks 1-2 only: the job, combined and combined_1000 strict, additional and
   below-half groups when the job test covers only candidates ranked 1 or 2 within
   their household. Candidate ranks order a household's candidates by person ID
   (scripts/expanded_job_entry.py, expanded_job_rank); the raise test's two adults
   are instead the two highest earners.
3. Ages 62-64: the candidates aged 62-64, and how far the job and combined strict
   and below-half groups fall when those candidates are not tested.
4. Largest loss: for the combined and job strict groups and the combined and job
   additional groups, the part of net income whose change lowers each flagged
   adult's household resources most, as scripts/driver_intervals.largest_loss
   assigns it with the premium tax credit counted once (cliffs2017.decompose.
   primary_driver over the saved components, leaving out the marketplace premium).
   A raise worker flagged by more than one raise takes the largest loss of the
   smallest raise that flags them.
5. Medicaid expansion: the combined and job strict groups split by whether the
   household's state covers the ACA adult group, read from the 2017 run's own
   parameters (gov.hhs.medicaid.eligibility.categories.adult.income_limit at
   1 January 2017, which the model backdates from its 2018 entries).
6. Without health: the combined and job strict groups without health coverage,
   with the sample and source households behind each.

Every count is its own set of households or adults, counted with MicroSeries in each
part's frozen historical simulation (``map_to="person"`` for residents). A fall is the
households in the full group but not in the smaller one, never a difference of counts.
Stored weight columns are never read. The 95% intervals resample all source
households jointly, 5,000 draws with seed 0, one draw for every count, as the union
does; shares take their intervals from the same draws.

The parts run on Modal (scripts/modal_combined_union_breakdowns.py). The combine step
checks every part against the all-scope union run and writes
results/combined_union_breakdowns_2017.json, aggregates only.

usage: python scripts/combined_union_breakdowns.py combine --digest TAG
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import combined_union_inputs as inputs  # noqa: E402

try:  # The Modal client's own Python, which lacks numpy, imports only the stdlib helpers.
    import numpy as np
    import pandas as pd

    from scripts.expanded_combined_union import (
        HALF,
        JOB,
        RAISES,
        SETS,
        STRICT,
        PartCounter,
        add_in_order,
        add_part_metrics,
        job_test_flags,
        load_job_part,
        load_per_source,
        load_raise_part,
        part_identities,
        peak_memory_gib,
        raise_test_flags,
        resample,
    )
    from scripts.expanded_raise_union import MEASURES, add_variable, full_mask
except ModuleNotFoundError as error:  # pragma: no cover - exercised only by the Modal client
    if error.name not in ("numpy", "pandas"):
        raise
    np = pd = None
    MEASURES = {"with_health": "d_net_single_ptc", "without_health": "d_net_without_health"}

YEAR = 2017
DRAWS = 5_000
BOOTSTRAP_SEED = 0
HEALTH = "with_health"
NO_HEALTH = "without_health"
BASES = ("job", "combined", "combined_1000")
LEVELS = ("strict", "below_half")
GROUPS = ("strict", "additional", "below_half")
FIELDS = ("adults", "households", "household_members")
# Job-test variants: every candidate (the union), ranks 1-2 only, and ages 62-64 left out.
FULL, RANKS_1_2, NO_62_64 = "full", "ranks_1_2", "excluding_ages_62_64"
VARIANT_BASES = {FULL: BASES, RANKS_1_2: BASES, NO_62_64: ("job", "combined")}
VARIANT_MEASURES = {FULL: tuple(MEASURES), RANKS_1_2: (HEALTH,), NO_62_64: (HEALTH,)}
OLDER = (62, 64)
POOL_SPLITS = {"rank": ("rank_1_2", "rank_3_plus"), "age": ("age_62_64", "age_18_61")}
# Largest-loss groups: (base, group).
DRIVER_GROUPS = (("combined", "strict"), ("job", "strict"), ("combined", "additional"), ("job", "additional"))
FAMILIES = ("health_coverage", "other")
MARKET = "d_household_market_income"
PREMIUM = "d_marketplace_net_premium"
NONE = "none"
# Medicaid adult group: covered to at least 138% of poverty (ACA expansion), covered below it
# (Wisconsin's waiver, 100%), or not covered (-inf in the model's parameter).
EXPANDED_LIMIT = 1.38
EXPANSION = ("expanded", "not_expanded_partial", "not_expanded")
EXPANSION_PARAMETER = "gov.hhs.medicaid.eligibility.categories.adult.income_limit"
TOLERANCE = 1e-9
IDENTITY_DOLLARS = 1.0

OUT_BASE = "results/combined_union/breakdowns"  # git-ignored with results/combined_union/
FINAL_JSON = "results/combined_union_breakdowns_2017.json"
# The union run over every complete wage scope (51 jurisdictions) these breakdowns reproduce.
REFERENCE_TAG = "1c0cc9ddcfd7d876"
EXTRA_CODE_FILES = (
    "scripts/combined_union_breakdowns.py",
    "scripts/modal_combined_union_breakdowns.py",
    "scripts/expanded_job_entry.py",
)
UNION_THRESHOLD = {"strict": "retains_lt_0pct", "below_half": "retains_lt_50pct", "additional": "additional"}

LABELS = {
    "medicaid_cost": "Medicaid",
    "chip": "CHIP",
    "chip_premium": "CHIP premium",
    "assigned_aca_ptc": "ACA premium tax credit",
    "msp_cost": "Medicare Savings Programs",
    "basic_health_program": "Basic Health Program",
    "snap": "SNAP",
    "ssi": "SSI",
    "tanf": "TANF",
    "wic": "WIC",
    "housing_assistance": "Housing assistance",
    "free_school_meals": "Free school meals",
    "reduced_price_school_meals": "Reduced-price school meals",
    "household_refundable_tax_credits": "Refundable tax credits (EITC, refundable CTC and state credits together)",
    "household_tax_before_refundable_credits": "Taxes before refundable credits (income and employee payroll)",
    "total_unemployment_compensation": "Unemployment compensation",
    "social_security": "Social Security",
    "household_state_benefits": "State benefits",
    "household_local_benefits": "Local benefits",
    "acp": "Affordable Connectivity Program",
    "ebb": "Emergency Broadband Benefit",
    NONE: "No part of net income fell",
}


# ---------------------------------------------------------------------------
# Paths and code (standard library)


def tag(digest: str) -> str:
    return digest[:16]


def manifest_rel(digest: str) -> str:
    return f"{OUT_BASE}/manifests/{tag(digest)}.json"


def part_json_rel(digest: str, part: int) -> str:
    return f"{OUT_BASE}/parts/{tag(digest)}/part_{part}.json"


def per_source_rel(digest: str, part: int, run_id: str) -> str:
    if not run_id.isalnum():
        raise ValueError("run id must be alphanumeric")
    return f"{OUT_BASE}/per_source/{tag(digest)}_part_{part}_{run_id}.npz"


def bootstrap_rel(digest: str, draws: int, seed: int) -> str:
    return f"{OUT_BASE}/bootstrap/{tag(digest)}_d{draws}_s{seed}.json"


def code_files() -> tuple:
    return (*inputs.CODE_FILES, *EXTRA_CODE_FILES)


def code_hashes(root: Path) -> dict:
    """The union's code hashes plus these breakdowns' own files."""
    hashes = inputs.code_hashes(root)
    hashes.update({rel: inputs.sha256((Path(root) / rel).read_bytes()) for rel in EXTRA_CODE_FILES})
    return hashes


def code_record(root: Path) -> dict:
    """The launching commit and its code hashes; refuses uncommitted code."""
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *code_files(), "cliffs2017"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise RuntimeError(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return {"commit": commit, "sha256": code_hashes(root)}


def verify_code(code: dict, root: Path) -> None:
    ours = code_hashes(root)
    if ours != code["sha256"]:
        changed = sorted(k for k in set(ours) | set(code["sha256"]) if ours.get(k) != code["sha256"].get(k))
        raise RuntimeError(f"this copy of the code differs from commit {code['commit'][:7]}: {changed}")


def reference_manifest(root: Path) -> dict:
    return json.loads((Path(root) / inputs.manifest_rel(REFERENCE_TAG)).read_text())


def check_same_inputs(manifest: dict, reference: dict) -> dict:
    """The breakdowns read exactly the inputs and coverage of the all-scope union run."""
    def keyed(m):
        return sorted((e["kind"], str(e["part"]), e["name"], e["sha256"]) for e in m["inputs"])

    if keyed(manifest) != keyed(reference):
        raise ValueError("the breakdown inputs differ from the all-scope union run's")
    if manifest["coverage"] != reference["coverage"]:
        raise ValueError("the breakdown coverage differs from the all-scope union run's")
    if manifest["coverage"]["status"] != inputs.STATUS_ALL or manifest["coverage"]["jurisdictions_deferred"]:
        raise ValueError("the breakdowns need every jurisdiction covered")
    return {"reference_digest": reference["digest"], "inputs": len(manifest["inputs"]), "same_inputs": True,
            "same_coverage": True}


# ---------------------------------------------------------------------------
# Rows, components and drivers


def expansion_category(limit) -> str:
    """The Medicaid adult group's coverage in a state from its income limit (share of poverty)."""
    if limit is None or (isinstance(limit, float) and math.isnan(limit)):
        raise ValueError("a state has no Medicaid adult income limit for the year")
    limit = float(limit)
    if limit == -math.inf:
        return "not_expanded"
    if limit >= EXPANDED_LIMIT - 1e-9:
        return "expanded"
    return "not_expanded_partial"


def json_limit(value: float):
    """A limit for strict JSON: the share of poverty, or None for the model's -inf (no adult group)."""
    value = float(value)
    if math.isnan(value):
        raise ValueError("a Medicaid adult income limit is NaN")
    return None if value == -math.inf else value


def model_expansion(simulation, states, year: int = YEAR) -> dict:
    """Each state's Medicaid adult income limit as the run's formulas read it, and its category.

    is_adult_for_medicaid_fc reads parameters(period).gov.hhs.medicaid.eligibility.categories.adult
    .income_limit[state]; for the 2017 run the period starts on 1 January 2017. Limits are shares
    of poverty; None stands for the model's -inf, a state with no adult group.
    """
    system = simulation.tax_benefit_system
    at = system.get_parameters_at_instant(f"{year}-01-01")
    node = system.parameters
    for step in EXPANSION_PARAMETER.split("."):
        node = getattr(node, step)
    out = {}
    # Plain str keys: a numpy string has __array__, which the parameter node reads as fancy indexing.
    for state in sorted({str(s) for s in states}):
        value = float(at.gov.hhs.medicaid.eligibility.categories.adult.income_limit[state])
        child = node.children[state]
        out[state] = {
            "limit_2017": json_limit(value),
            "limit_2018": json_limit(child(f"{year + 1}-01-01")),
            "dated_values": {v.instant_str: json_limit(v.value) for v in child.values_list
                             if v.instant_str <= "2019-12-31"},
            "category": expansion_category(value),
        }
    return out


def driver_names(components: list[str]) -> list[str]:
    """Every part that can be a largest loss: the components less market income and the premium."""
    return sorted({c.removeprefix("d_") for c in components if c not in (MARKET, PREMIUM)} | {NONE})


def drivers_from_components(frame, components: list[str]):
    """Each row's largest loss with the premium tax credit counted once, as largest_loss assigns it.

    Stops unless the components, less the marketplace premium, add to d_net_single_ptc.
    """
    from cliffs2017.decompose import primary_driver

    columns = [c for c in components if c != PREMIUM]
    if not len(frame):
        return np.array([], dtype=object)
    gap = (frame[columns].sum(axis=1) - frame[MEASURES[HEALTH]]).abs()
    if len(frame) and float(gap.max()) > IDENTITY_DOLLARS:
        raise ValueError(f"components miss d_net_single_ptc by up to {float(gap.max()):.2f}")
    return primary_driver(frame[columns]).to_numpy(dtype=object)


def person_drivers(frame, drivers, people: int):
    out = np.full(people, "", dtype=object)
    out[frame["person_index"].to_numpy()] = drivers
    return out


def assign_drivers(flagged, ordered_flags, ordered_drivers):
    """Each flagged adult's largest loss from the first test in order that flags them.

    Raise tests come in order of size, so a raise worker takes the smallest raise that flags
    them; raise workers and job candidates are disjoint.
    """
    flagged = np.asarray(flagged, dtype=bool)
    out = np.full(len(flagged), "", dtype=object)
    for flags, drivers in zip(ordered_flags, ordered_drivers):
        take = flagged & np.asarray(flags, dtype=bool) & (out == "")
        out[take] = drivers[take]
    if not np.array_equal(out != "", flagged):
        raise ValueError("a flagged adult has no test that flags them")
    return out


def read_columns(data: bytes, columns: list[str], dtype=None):
    return pd.read_csv(io.BytesIO(data), compression="gzip", usecols=columns, dtype=dtype, keep_default_na=False)


def job_components(files: dict, entries: list[dict], job) -> tuple:
    """Component columns of every job row, in load_job_part's order, and the records' column lists."""
    frames, lists = [], set()
    for entry in (e for e in entries if e["kind"] == "job_record"):
        record = json.loads(files[entry["name"]])
        components, health = record["component_columns"], record["health_columns"]
        lists.add((tuple(components), tuple(health)))
        frames.append(read_columns(files[record["rows"]["file"]], ["person_index", *components]))
    if len(lists) != 1:
        raise ValueError("job records list different component columns")
    components, health = (list(x) for x in lists.pop())
    if not set(health) <= set(components) or MARKET not in components:
        raise ValueError("job health or market columns are not components")
    table = pd.concat(frames, ignore_index=True)
    if not np.array_equal(table["person_index"].to_numpy(), job["person_index"].to_numpy()):
        raise ValueError("job components are not in the job rows' order")
    return table, components, health


def raise_components(files: dict, raise_records: dict, raise_frames: dict, components: list[str]) -> dict:
    out = {}
    for key, record in raise_records.items():
        table = read_columns(files[record["per_person_file"]], ["person_index", *components])
        if not np.array_equal(table["person_index"].to_numpy(), raise_frames[key]["person_index"].to_numpy()):
            raise ValueError(f"{key}: components are not in the saved rows' order")
        out[key] = table
    return out


# ---------------------------------------------------------------------------
# Counting


if np is not None:

    class BreakdownCounter(PartCounter):
        """PartCounter, plus counts of a set of adults alone and household inputs."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.serial = 0
            self.sample_adults = {}

        def fresh(self) -> str:
            self.serial += 1
            return f"v{self.serial}"

        def flag(self, flags) -> tuple[str, str]:
            return self.person_flag(self.fresh(), flags)

        def combine(self, left: str, right: str, operation: str) -> str:
            return self.household_flag(self.fresh(), left, right, operation)

        def household_input(self, flags) -> str:
            flags = np.asarray(flags, dtype=bool)
            if flags.shape != (self.households,):
                raise ValueError("household flags do not cover the part's households")
            name = self.name(self.fresh())
            add_variable(self.sim, name, "household")
            self.sim.set_input(name, self.year, flags)
            return name

        def adults(self, label: str, flags) -> float:
            """Weighted adults in ``flags``, stored under ``label`` beside any household counts."""
            flags = np.asarray(flags, dtype=bool)
            if flags.shape != (self.people,):
                raise ValueError(f"{label}: flags do not cover the part's people")
            if flags.any():
                name = self.name(self.fresh())
                add_variable(self.sim, name, "person")
                self.sim.set_input(name, self.year, flags)
                series = self.sim.calc(name, period=self.year)
                value = float(series.sum())
                totals = self._source_totals(series, self.person_source) if self.per_source else None
            else:
                value = 0.0
                totals = np.zeros(len(self.sources)) if self.per_source else None
            self.metrics.setdefault(label, {})["adults"] = value
            if self.per_source:
                if not math.isclose(float(totals.sum()), value, rel_tol=TOLERANCE, abs_tol=1e-6):
                    raise ValueError(f"{label}.adults: per-source totals do not add to the count")
                self.sources_totals.setdefault(label, {})["adults"] = totals
            self.sample_adults[label] = int(flags.sum())
            return value


def variant_flags(raise_tests: dict, job, people: int, measures) -> dict:
    """measure -> base -> level -> person flags, with the job test on ``job``'s rows only."""
    job_flags = job_test_flags(job, people)
    out = {}
    for m in measures:
        tests = {**raise_tests[m], JOB: job_flags[m]}
        out[m] = {
            base: {level: np.logical_or.reduce([tests[c][t] for c in SETS[base]])
                   for level, t in (("strict", STRICT), ("below_half", HALF))}
            for base in BASES
        }
    return out


def count_breakdowns(counter, raise_frames: dict, raise_drivers: dict, job, job_drivers, candidate, rank, age,
                     household_category, names: list[str], health_drivers: set) -> dict:
    """Every breakdown count of one part. Arrays are unweighted: person-level ``candidate``,
    ``rank`` (0 off the candidates), ``age`` and ``job_drivers``; household-level
    ``household_category`` (an EXPANSION entry). Returns the household sets for checks."""
    people, hh = counter.people, counter.household_index
    candidate = np.asarray(candidate, dtype=bool)
    rank, age = np.asarray(rank), np.asarray(age)
    tested = full_mask(job, np.ones(len(job), dtype=bool), people)
    if not np.array_equal(tested, candidate):
        raise ValueError("the job rows do not test exactly the candidates")
    if not np.array_equal(job["rank"].to_numpy(), rank[job["person_index"].to_numpy()]):
        raise ValueError("job row ranks differ from the candidate ranks")
    if (rank[candidate] < 1).any() or (rank[~candidate] != 0).any():
        raise ValueError("candidate ranks must start at 1 and be 0 elsewhere")
    category = np.asarray(household_category, dtype=object)
    if category.shape != (counter.households,) or not set(category) <= set(EXPANSION):
        raise ValueError("every household needs a Medicaid expansion category")
    older = candidate & (age >= OLDER[0]) & (age <= OLDER[1])
    person_category = category[hh]

    # 1. Candidate pool and its splits.
    p, h = counter.flag(candidate)
    counter.record("pool|candidates", h, person=p)
    splits = {
        "rank_1_2": candidate & (rank <= 2), "rank_3_plus": candidate & (rank >= 3),
        "age_62_64": older, "age_18_61": candidate & ~older,
        **{f"expansion_{c}": candidate & (person_category == c) for c in EXPANSION},
    }
    for label, mask in splits.items():
        p, h = counter.flag(mask)
        counter.record(f"pool|{label}", h, person=p)

    # 2-3, 6. The groups under each variant of the job test.
    raise_tests = raise_test_flags(raise_frames, people)
    rows = {FULL: job, RANKS_1_2: job[job["rank"] <= 2],
            NO_62_64: job[~older[job["person_index"].to_numpy()]]}
    flags = {v: variant_flags(raise_tests, rows[v], people, VARIANT_MEASURES[v]) for v in rows}
    names_of, houses = {}, {}
    for v, bases in VARIANT_BASES.items():
        for m in VARIANT_MEASURES[v]:
            for base in bases:
                strict_p, strict_h = counter.flag(flags[v][m][base]["strict"])
                counter.record(f"{v}|{m}|{base}|strict", strict_h, person=strict_p)
                half_p, half_h = counter.flag(flags[v][m][base]["below_half"])
                counter.record(f"{v}|{m}|{base}|below_half", half_h, person=half_p)
                extra = counter.combine(half_h, strict_h, "left_only")
                counter.record(f"{v}|{m}|{base}|additional", extra, adults_in=half_p)
                names_of[v, m, base] = {"strict": (strict_p, strict_h), "below_half": (half_p, half_h),
                                        "additional": extra}
                houses[v, m, base] = {g: counter.households_of(names_of[v, m, base][g] if g == "additional"
                                                               else names_of[v, m, base][g][1]) for g in GROUPS}

    # The fall from the full group: households and residents in the full group and not the
    # smaller one; adults flagged in the full group and not the smaller one.
    for v in (RANKS_1_2, NO_62_64):
        for base in VARIANT_BASES[v]:
            for level in LEVELS:
                full_house, small_house = houses[FULL, HEALTH, base][level], houses[v, HEALTH, base][level]
                if (small_house & ~full_house).any():
                    raise ValueError(f"{v} {base} {level}: a smaller job test added households")
                drop = counter.combine(names_of[FULL, HEALTH, base][level][1], names_of[v, HEALTH, base][level][1],
                                       "left_only")
                counter.record(f"drop|{v}|{base}|{level}", drop)
                full_people, small_people = flags[FULL][HEALTH][base][level], flags[v][HEALTH][base][level]
                if (small_people & ~full_people).any():
                    raise ValueError(f"{v} {base} {level}: a smaller job test flagged other adults")
                counter.adults(f"drop|{v}|{base}|{level}", full_people & ~small_people)
            # Narrowing the job test can move a household from strict to additional, so only
            # this weaker relation holds for the additional group.
            if (houses[v, HEALTH, base]["additional"] & ~houses[FULL, HEALTH, base]["below_half"]).any():
                raise ValueError(f"{v} {base}: an additional household lies outside the full below-half group")

    # 4. Largest loss.
    tests_health = {**raise_tests[HEALTH], JOB: job_test_flags(job, people)[HEALTH]}
    driver_of = {**raise_drivers, JOB: job_drivers}
    if set(np.unique(np.concatenate([d[d != ""] for d in driver_of.values()] + [np.array([], dtype=object)]))) - set(names):
        raise ValueError("a largest loss falls outside the component list")
    assigned_all = {}
    for base, group in DRIVER_GROUPS:
        if group == "strict":
            flagged, threshold = flags[FULL][HEALTH][base]["strict"], STRICT
        else:
            flagged = flags[FULL][HEALTH][base]["below_half"] & houses[FULL, HEALTH, base]["additional"][hh]
            threshold = HALF
        order = [c for c in (*RAISES, JOB) if c in SETS[base]]
        assigned = assign_drivers(flagged, [tests_health[c][threshold] for c in order],
                                  [driver_of[c] for c in order])
        assigned_all[base, group] = assigned
        counter.adults(f"driver_total|{base}|{group}", flagged)
        for name in names:
            counter.adults(f"driver|{base}|{group}|{name}", assigned == name)
        health = flagged & np.isin(assigned, sorted(health_drivers))
        counter.adults(f"driver_family|{base}|{group}|health_coverage", health)
        counter.adults(f"driver_family|{base}|{group}|other", flagged & ~health)

    # 5. Medicaid expansion.
    category_var = {c: counter.household_input(category == c) for c in EXPANSION}
    for base in ("combined", "job"):
        strict_p, strict_h = names_of[FULL, HEALTH, base]["strict"]
        for c in EXPANSION:
            flag = counter.combine(strict_h, category_var[c], "intersection")
            counter.record(f"expansion|{base}|strict|{c}", flag, adults_in=strict_p)
    return {"houses": houses, "assigned": assigned_all, "flags": flags}


def raise_ambiguity(raise_frames: dict, raise_drivers: dict, people: int) -> dict:
    """Sample raise workers flagged by more than one raise, and those whose largest loss differs
    across the raises that flag them (unweighted record counts)."""
    tests = raise_test_flags(raise_frames, people)[HEALTH]
    out = {}
    for level, t in (("strict", STRICT), ("below_half", HALF)):
        stacked = np.vstack([tests[k][t] for k in RAISES])
        multi = stacked.sum(axis=0) > 1
        differs = np.zeros(people, dtype=bool)
        for i in np.flatnonzero(multi):
            seen = {raise_drivers[k][i] for j, k in enumerate(RAISES) if stacked[j, i]}
            differs[i] = len(seen) > 1
        out[level] = {"flagged_by_more_than_one_raise": int(multi.sum()), "largest_loss_differs": int(differs.sum())}
    return out


# ---------------------------------------------------------------------------
# Invariants on counts (a part's or the national totals)


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=TOLERANCE, abs_tol=1e-6)


def le(a: float, b: float) -> bool:
    return a <= b + TOLERANCE * max(abs(b), 1.0)


def check_count_invariants(metrics: dict, names: list[str]) -> dict:
    """Each breakdown's parts add to its group, and a narrower job test never raises a count."""
    get = metrics.__getitem__
    pool = get("pool|candidates")
    pool_parts = all(close(sum(get(f"pool|{s}")["adults"] for s in pair), pool["adults"])
                     for pair in POOL_SPLITS.values())
    pool_parts &= all(close(sum(get(f"pool|expansion_{c}")[f] for c in EXPANSION), pool[f]) for f in FIELDS)
    pool_parts &= all(le(get(f"pool|{s}")[f], pool[f]) for pair in POOL_SPLITS.values() for s in pair for f in FIELDS)
    groups = narrower = drops = drivers = expansion = True
    for v, bases in VARIANT_BASES.items():
        for m in VARIANT_MEASURES[v]:
            for base in bases:
                s, a, b = (get(f"{v}|{m}|{base}|{g}") for g in GROUPS)
                groups &= all(close(s[f] + a[f], b[f]) for f in ("households", "household_members"))
                groups &= all(le(s[f], b[f]) for f in FIELDS) and le(s["adults"], s["household_members"])
                if v != FULL:
                    for level in LEVELS:
                        full, small = get(f"{FULL}|{m}|{base}|{level}"), get(f"{v}|{m}|{base}|{level}")
                        drop = get(f"drop|{v}|{base}|{level}")
                        narrower &= all(le(small[f], full[f]) for f in FIELDS)
                        drops &= all(close(full[f] - small[f], drop[f]) or close(full[f], small[f] + drop[f])
                                     for f in FIELDS)
                    narrower &= all(le(a[f], get(f"{FULL}|{m}|{base}|below_half")[f]) for f in FIELDS)
    for base, group in DRIVER_GROUPS:
        total = get(f"driver_total|{base}|{group}")["adults"]
        drivers &= close(total, get(f"{FULL}|{HEALTH}|{base}|{group}")["adults"])
        drivers &= close(sum(get(f"driver|{base}|{group}|{n}")["adults"] for n in names), total)
        drivers &= close(sum(get(f"driver_family|{base}|{group}|{x}")["adults"] for x in FAMILIES), total)
    for base in ("combined", "job"):
        total = get(f"{FULL}|{HEALTH}|{base}|strict")
        expansion &= all(close(sum(get(f"expansion|{base}|strict|{c}")[f] for c in EXPANSION), total[f])
                         for f in FIELDS)
    return {
        "pool_splits_add_to_the_pool": bool(pool_parts),
        "strict_plus_additional_equals_below_half": bool(groups),
        "narrower_job_test_never_raises_strict_or_below_half": bool(narrower),
        "fall_equals_full_minus_narrower": bool(drops),
        "largest_losses_add_to_each_group": bool(drivers),
        "expansion_split_adds_to_each_group": bool(expansion),
    }


# ---------------------------------------------------------------------------
# One part


def breakdown_part(simulation, dataset, files: dict, manifest: dict, part: int, year: int = YEAR) -> tuple[dict, dict]:
    from scripts.expanded_job_entry import register_analysis_variables

    entries = [e for e in manifest["inputs"] if e["part"] == part]
    person_table = dataset.person
    raise_frames, raise_records = load_raise_part(files, part, person_table)
    job, job_records = load_job_part(files, entries, part, person_table,
                                     manifest["coverage"]["expected_rows_by_part"][str(part)])
    job_table, components, health_columns = job_components(files, entries, job)
    raise_tables = raise_components(files, raise_records, raise_frames, components)
    source = part_identities(simulation, dataset, year)
    people = simulation.populations["person"].count

    job_drivers = person_drivers(job, drivers_from_components(
        job_table.assign(**{MEASURES[HEALTH]: job[MEASURES[HEALTH]].to_numpy()}), components), people)
    raise_drivers = {
        key: person_drivers(frame, drivers_from_components(
            raise_tables[key].assign(**{MEASURES[HEALTH]: frame[MEASURES[HEALTH]].to_numpy()}), components), people)
        for key, frame in raise_frames.items()
    }
    names = driver_names(components)
    health_drivers = {c.removeprefix("d_") for c in health_columns if c != PREMIUM}

    register_analysis_variables(simulation.tax_benefit_system)
    candidate = np.asarray(simulation.calculate("expanded_job_eligible", period=year, use_weights=False), dtype=bool)
    rank = np.asarray(simulation.calculate("expanded_job_rank", period=year, use_weights=False)).astype(np.int64)
    rank = np.where(candidate, rank, 0)
    age = np.asarray(simulation.calculate("age", period=year, use_weights=False), dtype=np.float64)
    state = np.asarray(simulation.calculate("state_code_str", period=year, use_weights=False)).astype(str)
    hh = np.asarray(simulation.populations["household"].members_entity_id)
    if not np.array_equal(job["state_code"].to_numpy(dtype=str), state[hh][job["person_index"].to_numpy()]):
        raise ValueError("job row states differ from the households' states")
    expansion = model_expansion(simulation, set(state), year)
    counter = BreakdownCounter(simulation, year, "bd", source)
    return summarize_counts(counter, raise_frames, raise_drivers, job, job_drivers, candidate, rank, age, state,
                            expansion, names, health_drivers, job_records, manifest, part)


def summarize_counts(counter, raise_frames: dict, raise_drivers: dict, job, job_drivers, candidate, rank, age,
                     state, expansion: dict, names: list[str], health_drivers: set, job_records: list[dict],
                     manifest: dict, part: int) -> tuple[dict, dict]:
    """Count one part, check its invariants and assemble its record and per-source totals.

    ``state`` is each household's state; ``expansion`` maps a state to its Medicaid entry
    (model_expansion)."""
    category = np.array([expansion[str(s)]["category"] for s in state], dtype=object)
    sets = count_breakdowns(counter, raise_frames, raise_drivers, job, job_drivers, candidate, rank, age, category,
                            names, health_drivers)
    checks = check_count_invariants(counter.metrics, names)
    weighted_tested = add_in_order(r["counts"]["weighted_candidates_tested"] for r in job_records)
    checks["pool_equals_job_runner_weighted_candidates"] = close(counter.metrics["pool|candidates"]["adults"],
                                                                  weighted_tested)
    failed = [k for k, ok in checks.items() if ok is not True]
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
        "sample_adults": counter.sample_adults,
        "driver_names": names,
        "health_drivers": sorted(health_drivers),
        "medicaid_expansion_by_state": {str(s): expansion[str(s)] for s in sorted(set(state))},
        "raise_ambiguity": raise_ambiguity(raise_frames, raise_drivers, counter.people),
        "job": {"sample_candidates_tested": int(len(job)), "weighted_candidates_tested_by_runner": weighted_tested,
                "sample_candidates_by_rank": {str(int(k)): int(n)
                                              for k, n in job["rank"].value_counts().sort_index().items()},
                "jurisdictions": sorted(set(job["state_code"]))},
        "invariants": {k: {"pass": v} for k, v in checks.items()},
        "source_households": int(len(counter.sources)),
        "source_household_ids_sha256": hashlib.sha256(np.ascontiguousarray(counter.sources).tobytes()).hexdigest(),
    }
    del sets
    gc.collect()
    return record, {"sources": counter.sources, "matrix": matrix, "columns": columns}


def run_part(part: int, manifest: dict, files: dict, year: int = YEAR) -> tuple[dict, bytes]:
    from importlib import metadata

    from scripts.expanded_historical import historical_provenance
    from scripts.expanded_raise_union import historical_part

    inputs.check_files(manifest, part, files)
    started = time.time()
    dataset, simulation = historical_part(year, inputs.PARTS, part, inputs.SEED)
    loaded = round(time.time() - started, 1)
    record, totals = breakdown_part(simulation, dataset, files, manifest, part, year)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, sources=totals["sources"], matrix=totals["matrix"],
                        columns=np.array(totals["columns"]))
    npz = buffer.getvalue()
    record["per_source"] = {"sha256": inputs.sha256(npz), "columns": totals["columns"],
                            "rows": int(totals["matrix"].shape[0]),
                            "record_level": "per-source-household totals; git-ignored; never commit"}
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


def ratio_pairs(columns: list[str], names: list[str]) -> dict:
    """Shares to interval: name -> (numerator column, denominator column)."""
    present = set(columns)
    pairs = {}

    def add(name, top, bottom):
        if top in present and bottom in present:
            pairs[name] = (top, bottom)

    for split in (*POOL_SPLITS["rank"], *POOL_SPLITS["age"], *(f"expansion_{c}" for c in EXPANSION)):
        for f in FIELDS:
            add(f"pool|{split}|{f}", f"pool|{split}|{f}", f"pool|candidates|{f}")
    for v in (RANKS_1_2, NO_62_64):
        for base in VARIANT_BASES[v]:
            for group in GROUPS:
                for f in FIELDS:
                    add(f"{v}|{base}|{group}|{f}", f"{v}|{HEALTH}|{base}|{group}|{f}",
                        f"{FULL}|{HEALTH}|{base}|{group}|{f}")
            for level in LEVELS:
                for f in FIELDS:
                    add(f"drop|{v}|{base}|{level}|{f}", f"drop|{v}|{base}|{level}|{f}",
                        f"{FULL}|{HEALTH}|{base}|{level}|{f}")
    for base, group in DRIVER_GROUPS:
        for n in (*names, *(f"family:{x}" for x in FAMILIES)):
            top = (f"driver_family|{base}|{group}|{n.removeprefix('family:')}|adults" if n.startswith("family:")
                   else f"driver|{base}|{group}|{n}|adults")
            add(f"driver|{base}|{group}|{n}", top, f"driver_total|{base}|{group}|adults")
    for base in ("combined", "job"):
        for c in EXPANSION:
            for f in FIELDS:
                add(f"expansion|{base}|strict|{c}|{f}", f"expansion|{base}|strict|{c}|{f}",
                    f"{FULL}|{HEALTH}|{base}|strict|{f}")
    return pairs


def ratio_interval(top, bottom) -> list:
    """Percentile interval of a share over the draws; draws with an empty denominator are dropped."""
    from scripts.driver_intervals import interval

    keep = bottom != 0
    if not keep.any():
        return [None, None]
    return interval(top[keep] / bottom[keep])


def bootstrap_breakdowns(records: list[dict], npz_list: list[bytes], draws: int = DRAWS,
                         seed: int = BOOTSTRAP_SEED) -> dict:
    """Joint percentile intervals for every count and share, one resample of all source households."""
    from scripts.driver_intervals import interval, support

    if sorted(r["part"] for r in records) != list(range(inputs.PARTS)):
        raise ValueError("the bootstrap needs every part")
    order = sorted(range(len(records)), key=lambda i: records[i]["part"])
    records = [records[i] for i in order]
    parts = [load_per_source(npz_list[i]) for i in order]
    columns = parts[0]["columns"]
    if any(p["columns"] != columns for p in parts):
        raise ValueError("parts hold different per-source columns")
    sources = np.concatenate([p["sources"] for p in parts])
    if len(np.unique(sources)) != len(sources):
        raise ValueError("a source household appears in two parts")
    stats = np.vstack([p["matrix"] for p in parts])
    totals = add_part_metrics(records)
    flat = {f"{label}|{f}": v for label, fields in totals.items() for f, v in fields.items()}
    estimates = stats.sum(axis=0)
    for j, column in enumerate(columns):
        if not close(float(estimates[j]), flat[column]):
            raise ValueError(f"{column}: per-source totals add to {estimates[j]}, counts to {flat[column]}")
    started = time.time()
    out = resample(stats, draws, seed)
    index = {c: j for j, c in enumerate(columns)}
    result = {}
    for j, column in enumerate(columns):
        result[column] = {
            "estimate": flat[column],
            "standard_error": float(out[:, j].std(ddof=1)),
            "interval_95": interval(out[:, j]),
            **{k: v for k, v in support(stats[:, j], 0).items() if k != "sample_people_on_cliff"},
        }
    names = records[0]["driver_names"]
    shares = {}
    for name, (top, bottom) in ratio_pairs(columns, names).items():
        t, b = index[top], index[bottom]
        shares[name] = {"numerator": top, "denominator": bottom,
                        "estimate": flat[top] / flat[bottom] if flat[bottom] else None,
                        "interval_95": ratio_interval(out[:, t], out[:, b])}
    return {
        "draws": draws,
        "seed": seed,
        "method": "percentile; multinomial resample of all source households jointly, one draw for every count "
                  "and share (scripts/expanded_combined_union.resample, as scripts/driver_intervals.resample)",
        "source_households": int(len(sources)),
        "seconds": round(time.time() - started, 1),
        "columns": result,
        "shares": shares,
    }


# ---------------------------------------------------------------------------
# Combine


# Published aggregates (numbers in thousands) from the Census Bureau's CPS ASEC table POV-24,
# "Did not work last year", people aged 18 to 64, by main reason for not working.
POV24_COLUMNS = ("total", "ill_or_disabled", "retired", "home_or_family", "could_not_find_work",
                 "school_or_other")
BENCHMARK_TABLES = (
    {
        "id": "census_cps_asec_pov24_2017",
        "publisher": "U.S. Census Bureau",
        "table": "CPS Poverty Table POV-24: Reason for Not Working or Reason for Spending Time Out of the "
                 "Labor Force -- Poverty Status of People Who Did Not Work or Who Spent Time Out of the "
                 "Labor Force: 2017 (all income levels, all races, both sexes)",
        "survey": "Current Population Survey, 2018 Annual Social and Economic Supplement",
        "data_year": 2017,
        "url": "https://www2.census.gov/programs-surveys/cps/tables/pov-24/2018/pov24_001_1.xls",
        "file_sha256": "fe302bd9ebba4c6995c725505cbd3fb44fad76859ea07a169195b96cf9d2c730",
        "row": "18 to 64 years",
        "did_not_work_last_year_thousands": dict(zip(POV24_COLUMNS, (45914, 12906, 7511, 12828, 1701, 10969))),
        "aged_55_64_thousands": dict(zip(POV24_COLUMNS, (13355, 5311, 5655, 1840, 267, 282))),
    },
    {
        "id": "census_cps_asec_pov24_2018",
        "publisher": "U.S. Census Bureau",
        "table": "CPS Poverty Table POV-24 (same table): 2018 (all income levels, all races, both sexes)",
        "survey": "Current Population Survey, 2019 Annual Social and Economic Supplement",
        "data_year": 2018,
        "url": "https://www2.census.gov/programs-surveys/cps/tables/pov-24/2019/pov24_001_1.xls",
        "file_sha256": "f99c78fdd902382ecc59b516c24b55650c177832aa9f821e94099bb006f93c5f",
        "row": "18 to 64 years",
        "did_not_work_last_year_thousands": dict(zip(POV24_COLUMNS, (44940, 12191, 7301, 12888, 1683, 10878))),
        "aged_55_64_thousands": dict(zip(POV24_COLUMNS, (13300, 5088, 5683, 2072, 235, 222))),
    },
)
BENCHMARK_GAPS = (
    "Census counts people who did not work at all in the year by their own main reason; the job test's "
    "candidates have no wages or self-employment income in the model's 2017 data and are not flagged as "
    "full-time students or as having a disability (is_full_time_student, is_disabled). A person with a "
    "disability who names another main reason stays in the Census rows after removing 'ill or disabled', "
    "and a person who names illness without a disability flag is a candidate.",
    "Census combines going to school with other reasons, so only bounds match the candidate pool: removing "
    "'ill or disabled' alone keeps every student (upper comparator); removing 'school or other' too also "
    "drops non-students who gave other reasons (lower comparator).",
    "Both keep retirees aged 18-64 who report no disability: the 2017 table counts 7.5 million adults aged "
    "18-64 who did not work and named retirement, 5.7 million of them aged 55-64. The table has no 62-64 row.",
    "Census weights CPS ASEC respondents; the model counts the calibrated Microcosm households of the "
    "2017 run, whose own calibration need not match these tables.",
)


def benchmark_comparators(table: dict) -> dict:
    """The table's 18-64 non-workers less those naming illness or disability, and less school or other too."""
    row = table["did_not_work_last_year_thousands"]
    # Each cell is rounded to the thousand, so the reasons may miss the total by a few.
    if abs(row["total"] - sum(row[c] for c in POV24_COLUMNS[1:])) > len(POV24_COLUMNS):
        raise ValueError(f"{table['id']}: the reasons do not add to the total")
    return {
        "did_not_work_18_64": row["total"] * 1e3,
        "excluding_ill_or_disabled": (row["total"] - row["ill_or_disabled"]) * 1e3,
        "excluding_ill_or_disabled_and_school_or_other": (row["total"] - row["ill_or_disabled"]
                                                          - row["school_or_other"]) * 1e3,
    }


def external_benchmark(pool: dict) -> dict:
    """Published counts of non-working adults aged 18-64 compared with the candidate pool (item 1)."""
    out = []
    for table in BENCHMARK_TABLES:
        comparators = benchmark_comparators(table)
        out.append({
            **table,
            "comparators": comparators,
            "pool_over_comparator": {k: {"estimate": pool["estimate"] / v,
                                         "pool_interval_over_comparator": [x / v for x in pool["interval_95"]]}
                                     for k, v in comparators.items()},
        })
    return {"candidate_pool_adults": {"estimate": pool["estimate"], "interval_95": pool["interval_95"]},
            "sources": out, "definitional_gaps": list(BENCHMARK_GAPS),
            "not_used": "Brookings' 'Meet the out-of-work' (2017) covers 130 cities and counties, not the nation."}


def reproduce_reference(records: list[dict], root: Path = ROOT) -> dict:
    """Every full-group count of every part against the all-scope union run's part record."""
    reference = reference_manifest(root)
    worst = 0.0
    compared = 0
    for record in records:
        theirs = inputs.local_part(root, reference["digest"], record["part"])
        if theirs is None:
            raise FileNotFoundError(f"the all-scope union run has no validated part {record['part']}")
        for m in MEASURES:
            for base in BASES:
                for group in GROUPS:
                    ours = record["metrics"][f"{FULL}|{m}|{base}|{group}"]
                    other = theirs["metrics"][f"{m}|{base}|{UNION_THRESHOLD[group]}"]
                    for f in FIELDS:
                        gap = abs(ours[f] - other[f])
                        worst = max(worst, gap / max(abs(other[f]), 1.0))
                        compared += 1
                        if not close(ours[f], other[f]):
                            raise ValueError(f"part {record['part']} {m} {base} {group} {f}: {ours[f]} vs {other[f]}")
    return {"reference_digest": reference["digest"], "counts_compared": compared,
            "max_relative_difference": worst, "exact": worst == 0.0}


def reproduce_reference_intervals(boot: dict, root: Path = ROOT) -> dict:
    """The full groups' intervals against the all-scope union run's bootstrap (same draws)."""
    reference = reference_manifest(root)
    theirs = json.loads((Path(root) / inputs.bootstrap_rel(reference["digest"], boot["draws"],
                                                           boot["seed"])).read_text())["columns"]
    worst = 0.0
    compared = 0
    for m in MEASURES:
        for base in BASES:
            for group in GROUPS:
                for f in FIELDS:
                    ours = boot["columns"][f"{FULL}|{m}|{base}|{group}|{f}"]
                    other = theirs[f"{m}|{base}|{UNION_THRESHOLD[group]}|{f}"]
                    for a, b in zip(ours["interval_95"], other["interval_95"]):
                        worst = max(worst, abs(a - b) / max(abs(b), 1.0))
                        compared += 1
    if worst > 1e-9:
        raise ValueError(f"intervals differ from the all-scope union run by up to {worst:.2e} (relative)")
    return {"intervals_compared": compared, "max_relative_difference": worst}


def counts(boot: dict, label: str, sample: dict | None = None, fields=FIELDS) -> dict:
    out = {}
    for f in fields:
        column = boot["columns"].get(f"{label}|{f}")
        if column is not None:
            out[f] = {"estimate": column["estimate"], "interval_95": column["interval_95"],
                      "standard_error": column["standard_error"]}
    if sample is not None:
        out["sample"] = sample
    return out


def share(boot: dict, name: str) -> dict:
    s = boot["shares"][name]
    return {"estimate": s["estimate"], "interval_95": s["interval_95"]}


def support_of(boot: dict, label: str, sample_households: int, sample_adults: int | None = None) -> dict:
    column = boot["columns"][f"{label}|household_members"]
    adults = boot["columns"][f"{label}|adults"]
    return {"sample_households": sample_households, "sample_adults": sample_adults,
            "source_households": column["source_households"],
            "source_households_for_half_of_members": column["source_households_for_half"],
            "kish_effective_source_households_members": column["kish_effective_source_households"],
            "source_households_with_flagged_adults": adults["source_households"]}


def flagged_sample_adults(records: list[dict], label: str) -> int | None:
    values = [r["sample_adults"].get(label) for r in records]
    return None if any(v is None for v in values) else sum(values)


def build_result(records: list[dict], boot: dict, manifest: dict) -> dict:
    """The breakdown JSON's sections from the part records and the bootstrap."""
    records = sorted(records, key=lambda r: r["part"])
    names = records[0]["driver_names"]
    if any(r["driver_names"] != names for r in records):
        raise ValueError("parts list different largest losses")
    totals = add_part_metrics(records)
    sample_h = {label: sum(r["sample_households"][label] for r in records) for label in records[0]["sample_households"]}
    checks = check_count_invariants(totals, names)
    if not all(checks.values()):
        raise ValueError(f"national invariants failed: {[k for k, v in checks.items() if not v]}")
    for column, entry in boot["columns"].items():
        label, f = column.rsplit("|", 1)
        if not close(entry["estimate"], totals[label][f]):
            raise ValueError(f"bootstrap {column} differs from the part totals")

    pool = {"candidates": counts(boot, "pool|candidates", {"sample_households": sample_h["pool|candidates"]})}
    for split in (*POOL_SPLITS["rank"], *POOL_SPLITS["age"], *(f"expansion_{c}" for c in EXPANSION)):
        pool[split] = counts(boot, f"pool|{split}", {"sample_households": sample_h[f"pool|{split}"]})
        pool[split]["share_of_candidates"] = {f: share(boot, f"pool|{split}|{f}") for f in ("adults",)}
    pool["sample_candidates"] = sum(r["job"]["sample_candidates_tested"] for r in records)
    by_rank = {}
    for r in records:
        for k, n in r["job"]["sample_candidates_by_rank"].items():
            by_rank[str(k)] = by_rank.get(str(k), 0) + n
    pool["sample_candidates_by_rank"] = dict(sorted(by_rank.items(), key=lambda kv: int(kv[0])))

    def groups(v, m, base):
        return {g: counts(boot, f"{v}|{m}|{base}|{g}", {"sample_households": sample_h[f"{v}|{m}|{base}|{g}"]})
                for g in GROUPS}

    ranks = {}
    for base in BASES:
        ranks[base] = {
            "ranks_1_2": groups(RANKS_1_2, HEALTH, base),
            "all_ranks": groups(FULL, HEALTH, base),
            "fall": {level: counts(boot, f"drop|{RANKS_1_2}|{base}|{level}",
                                   {"sample_households": sample_h[f"drop|{RANKS_1_2}|{base}|{level}"]})
                     for level in LEVELS},
            "ranks_1_2_share_of_all_ranks": {g: share(boot, f"{RANKS_1_2}|{base}|{g}|household_members")
                                             for g in GROUPS},
        }
    older = {"candidates_aged_62_64": pool["age_62_64"]}
    for base in VARIANT_BASES[NO_62_64]:
        older[base] = {
            "all_candidates": {lv: groups(FULL, HEALTH, base)[lv] for lv in LEVELS},
            "excluding_ages_62_64": {lv: groups(NO_62_64, HEALTH, base)[lv] for lv in LEVELS},
            "fall": {lv: {**counts(boot, f"drop|{NO_62_64}|{base}|{lv}",
                                   {"sample_households": sample_h[f"drop|{NO_62_64}|{base}|{lv}"]}),
                          "share_of_group": {f: share(boot, f"drop|{NO_62_64}|{base}|{lv}|{f}")
                                             for f in ("household_members", "adults")}}
                     for lv in LEVELS},
        }

    drivers = {}
    for base, group in DRIVER_GROUPS:
        total_label = f"driver_total|{base}|{group}"
        entry = {"flagged_adults": counts(boot, total_label, {"sample_adults": flagged_sample_adults(records, total_label)},
                                          ("adults",)),
                 "by_largest_loss": {}, "by_family": {}}
        for n in names:
            label = f"driver|{base}|{group}|{n}"
            if totals[label]["adults"] == 0:
                continue
            entry["by_largest_loss"][n] = {
                "label": LABELS.get(n, n.replace("_", " ")),
                **counts(boot, label, {"sample_adults": flagged_sample_adults(records, label),
                                       "source_households": boot["columns"][f"{label}|adults"]["source_households"]},
                         ("adults",)),
                "share": share(boot, f"driver|{base}|{group}|{n}"),
            }
        entry["by_largest_loss"] = dict(sorted(entry["by_largest_loss"].items(),
                                               key=lambda kv: -kv[1]["adults"]["estimate"]))
        for x in FAMILIES:
            label = f"driver_family|{base}|{group}|{x}"
            entry["by_family"][x] = {**counts(boot, label, {"sample_adults": flagged_sample_adults(records, label)},
                                              ("adults",)),
                                     "share": share(boot, f"driver|{base}|{group}|family:{x}")}
        drivers[f"{base}_{group}"] = entry
    ambiguity = {level: {k: sum(r["raise_ambiguity"][level][k] for r in records)
                         for k in records[0]["raise_ambiguity"][level]} for level in LEVELS}

    expansion_states = {}
    for r in records:
        for state, entry in r["medicaid_expansion_by_state"].items():
            if expansion_states.setdefault(state, entry) != entry:
                raise ValueError(f"parts read different Medicaid limits for {state}")
    expansion = {
        "parameter": EXPANSION_PARAMETER,
        "how_read": "The 2017 run's own tax-benefit system, at 1 January 2017, the instant the Medicaid adult "
                    "formula (is_adult_for_medicaid_fc) reads for a 2017 period. The parameter's earliest dated "
                    "values are 1 January 2018; policyengine-us backdates each parameter's earliest value to "
                    "2015, so the 2017 run applies the January 2018 limits. A state covers the ACA adult group "
                    "when its limit is at least 1.38 (138% of poverty); a positive limit below 1.38 "
                    "(Wisconsin's 1.00) covers adults below it under a waiver without expanding; a null "
                    "limit stands for the model's -inf, no adult group.",
        "states": {c: sorted(s for s, e in expansion_states.items() if e["category"] == c) for c in EXPANSION},
        "jurisdictions": {c: sum(e["category"] == c for e in expansion_states.values()) for c in EXPANSION},
        "limit_2017_by_state": {s: e["limit_2017"] for s, e in sorted(expansion_states.items())},
        "limit_2017_equals_limit_2018_in_every_state": all(e["limit_2017"] == e["limit_2018"]
                                                           for e in expansion_states.values()),
    }
    for base in ("combined", "job"):
        expansion[f"{base}_strict"] = {
            "total": counts(boot, f"{FULL}|{HEALTH}|{base}|strict"),
            **{c: {**counts(boot, f"expansion|{base}|strict|{c}",
                            {"sample_households": sample_h[f"expansion|{base}|strict|{c}"]}),
                   "share": {f: share(boot, f"expansion|{base}|strict|{c}|{f}") for f in ("household_members", "adults")}}
               for c in EXPANSION},
        }
    expansion["candidate_pool"] = {c: pool[f"expansion_{c}"] for c in EXPANSION}

    without = {}
    for base in ("combined", "job", "combined_1000"):
        label = f"{FULL}|{NO_HEALTH}|{base}|strict"
        without[base] = {"strict": counts(boot, label),
                         "support": support_of(boot, label, sample_h[label], flagged_sample_adults(records, label)),
                         "with_health_for_comparison": counts(boot, f"{FULL}|{HEALTH}|{base}|strict")}
    return {
        "candidate_pool": pool,
        "ranks_1_2": ranks,
        "ages_62_64": older,
        "largest_loss": {"groups": drivers, "raise_workers_flagged_by_several_raises": ambiguity},
        "medicaid_expansion": expansion,
        "without_health": without,
        "invariants_national": checks,
    }


def combine(digest: str, draws: int, seed: int, out: Path) -> dict:
    from scripts.earnings_changes_summary import check_code
    from scripts.expanded_historical import historical_provenance

    manifest = json.loads((ROOT / manifest_rel(digest)).read_text())
    if inputs.manifest_digest(manifest) != manifest["digest"] or manifest["digest"] != digest:
        raise ValueError("the manifest does not match its digest")
    same = check_same_inputs(manifest, reference_manifest(ROOT))
    records = []
    for part in range(inputs.PARTS):
        path = ROOT / part_json_rel(digest, part)
        data = path.read_bytes()
        npz = (ROOT / json.loads(data)["per_source"]["file"]).read_bytes()
        records.append(inputs.validate_part_pair(data, npz, dict(part=part, digest=digest)))
    if {r["code"]["commit"] for r in records} != {manifest["code"]["commit"]}:
        raise ValueError("parts ran other code than the manifest records")
    if code_hashes(ROOT) != manifest["code"]["sha256"]:
        raise ValueError("this checkout's code differs from the code the parts ran")
    raise_code = check_code(YEAR, [json.loads((ROOT / inputs.raise_metadata_rel(p, k)).read_text())
                                   for p in range(inputs.PARTS) for k in RAISES])
    boot = json.loads((ROOT / bootstrap_rel(digest, draws, seed)).read_text())
    sections = build_result(records, boot, manifest)
    reproduction = {"inputs": same, "part_counts": reproduce_reference(records),
                    "intervals": reproduce_reference_intervals(boot)}
    coverage = manifest["coverage"]
    result = {
        "status": coverage["status"],
        "year": YEAR,
        "question": "Breakdowns of the combined raise-and-job union under 2017 federal rules, with health coverage "
                    "unless a section says otherwise.",
        "conventions": {
            "job_test": "A candidate (aged 18-64; no wages or self-employment income; not a full-time student; "
                        "not reporting disability) takes a full-time job (40 hours x 52 weeks) at the state's 2017 "
                        "minimum wage, one candidate at a time.",
            "candidate_rank": "Candidates are ranked within their household by person ID (expanded_job_rank); the "
                              "raise test instead takes the household's two highest earners by market income.",
            "groups": "strict: households below 0% retention on any test in the set; additional: below 50% and not "
                      "below 0% on any test; below_half: below 50%. Residents counted once.",
            "fall": "Households (and their residents) in the full group but not the narrower one; adults flagged "
                    "in the full group but not the narrower one. Narrowing the job test can move a household "
                    "from strict to additional, so the additional group is not bounded by its full count.",
            "largest_loss": "The part of net income whose change lowers household resources most for the flagged "
                            "adult's own test (cliffs2017.decompose.primary_driver), with the premium tax credit "
                            "counted once (the marketplace premium left out, as driver_intervals.largest_loss "
                            "does). A raise worker flagged by several raises takes the smallest such raise. EITC "
                            "is not separable: it is inside household_refundable_tax_credits.",
            "health": "with_health: government-valued health coverage, ACA premium tax credit counted once "
                      "(d_net_single_ptc); without_health: every part of net income except health benefits and "
                      "costs (d_net_without_health).",
            "units": "adults: flagged adults (or candidates); households; household_members: residents of those "
                     "households.",
        },
        "coverage": {k: coverage[k] for k in ("scopes_included", "jurisdictions_covered", "jurisdictions_deferred",
                                              "sample_candidates_tested", "wages_json_sha256_by_scope")},
        **sections,
        "external_benchmark": external_benchmark(sections["candidate_pool"]["candidates"]["adults"]),
        "reproduction": reproduction,
        "invariants_every_part": {name: all(r["invariants"][name]["pass"] is True for r in records)
                                  for name in records[0]["invariants"]},
        "uncertainty": {k: boot[k] for k in ("draws", "seed", "method", "source_households", "seconds")},
        "aggregation": "MicroSeries.sum and MicroSeries.groupby(source household).sum on analysis flags in each "
                       "part's frozen simulation, with map_to='person' for residents; stored weight columns are "
                       "not read.",
        "runtime": {"mode": "unmanaged_frozen_historical_output_postprocessing",
                    "historical_loader": historical_provenance(),
                    "parts": [{"part": r["part"], **r["runtime"]} for r in records]},
        "code": {"launch_commit": manifest["code"]["commit"], "code_sha256": manifest["code"]["sha256"],
                 "raise_experiment_code": raise_code,
                 "combine_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()},
        "modal": {"app": "us-cliffs-2017-combined-union-breakdowns"},
        "manifest_digest": digest,
        "metrics": add_part_metrics(records),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True, allow_nan=False) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("combine", help="add the installed part results and write the breakdown JSON")
    c.add_argument("--digest", required=True)
    c.add_argument("--draws", type=int, default=DRAWS)
    c.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    c.add_argument("--out", type=Path, default=ROOT / FINAL_JSON)
    args = parser.parse_args()
    digest = args.digest
    if len(digest) == 16:
        digest = json.loads((ROOT / manifest_rel(digest)).read_text())["digest"]
    result = combine(digest, args.draws, args.seed, args.out)
    pool = result["candidate_pool"]["candidates"]
    for f in ("adults", "household_members"):
        lo, hi = pool[f]["interval_95"]
        print(f"pool {f}: {pool[f]['estimate'] / 1e6:.2f}M ({lo / 1e6:.2f}-{hi / 1e6:.2f})")
    print(f"status {result['status']}; reproduction exact: {result['reproduction']['part_counts']['exact']}")
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
