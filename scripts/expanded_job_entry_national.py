"""National job-entry test: one candidate rank of one household part.

The pilot (scripts/expanded_job_entry.py) defines the test: the candidate
population, the within-household candidate rank, the full-time job inputs, the
branch that applies them, and the resource measure. This module runs that test
for every candidate of one rank in one of the frozen experiment's four disjoint
household parts (``--parts 4``, seed 0, full weight), at the national wage table
(scripts/job_entry_wages.py). The full-sample Medicaid totals make each
household's result independent of which part holds it.

For each tested adult it records the household's change in resources:

- with health coverage, the pilot's measure: household net income with health
  coverage at government cost plus the marketplace net premium, so the premium
  tax credit counts once (``d_net_single_ptc``, as in the raise experiment);
- without health coverage, every part of net income except the health benefits
  and costs (``d_net_without_health``, cliffs2017.changes.without_health);

with the signed change in every part of net income (cliffs2017.decompose).

Each run checks, and stops on failure: a zero-change branch leaves every
household's measures exactly unchanged; the job branch leaves every household
without a tested adult exactly unchanged; each entrant's earnings equal the
table's rate times 2,080, at 40 hours and 52 weeks, and nobody else's earnings
change; every month's stored WIC take-up draw is unchanged; the parts add up to
net income; and the with-health measure agrees with its decomposition. A smoke
run also rebuilds the job as changed inputs in a fresh simulation.

Candidates in a jurisdiction the wage table leaves unresolved are not tested;
the record counts them by state as deferred, for a later run in a ``states:``
scope. Weighted totals use MicroSeries; no stored weight column is read.
"""

from __future__ import annotations

import functools
import gc
import hashlib
import io
import json
import platform
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

from scripts.expanded_job_entry import (  # noqa: E402
    EARNINGS,
    THRESHOLDS,
    eligible_nonworkers,
    fresh_job_simulation,
    make_job_branch,
    map_flag,
    register_analysis_variables,
)
from scripts.job_entry_outputs import (  # noqa: E402
    CODE_FILES,
    PARTS,
    SEED,
    YEAR,
    csv_gzip,
    local_environment,
    scope_states,
    scope_tag,
    sha256,
    validate_pair,
    wage_table_fingerprint,
)
from scripts.job_entry_wages import HOURS_PER_YEAR, JURISDICTIONS, national_wage_table  # noqa: E402

RESOURCES = "expanded_job_resources"
PREMIUM = "marketplace_net_premium"
GROSS_TOLERANCE = 0.02  # float32 earnings near $25,000 round to about $0.002
MEASURE_TOLERANCE = 1.0  # two float32 routes to the same household total


def peak_memory_gib() -> float:
    """Peak resident memory of this process (Linux reports KiB, macOS bytes)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024**3 if sys.platform == "darwin" else 1024**2), 3)


def code_record() -> dict:
    hashes = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in CODE_FILES}
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *CODE_FILES, "cliffs2017"],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {"commit": commit, "uncommitted": dirty, "sha256": hashes}


# The installed versions a result records beside the requirements file's hash.
VERSIONED = ("policyengine-us", "policyengine-core", "microdf-python", "numpy", "pandas", "tables",
             "h5py", "huggingface-hub")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def environment() -> dict:
    """What fixes a result besides its request and wage table: code, dataset and packages.

    The checkout's part (job_entry_outputs.local_environment) plus the dataset
    file's SHA-256, the installed versions and the Python version. Only
    ``code``, ``dataset`` and ``packages`` keys, each JSON-native, so a launch's
    expectation and a stored record compare leaf by leaf.
    """
    from huggingface_hub import hf_hub_download

    from cliffs2017.run import FILENAME, REPO, REVISION

    env = local_environment(ROOT)
    path = hf_hub_download(REPO, FILENAME, repo_type="dataset", revision=REVISION)
    env["dataset"]["file_sha256"] = _dataset_sha256(str(path))
    env["packages"]["versions"] = {p: metadata.version(p) for p in VERSIONED}
    env["packages"]["python"] = platform.python_version()
    return json.loads(json.dumps(env))


@functools.lru_cache(maxsize=2)
def _dataset_sha256(path: str) -> str:
    return _file_sha256(Path(path))


def load_part(part: int, parts: int = PARTS, seed: int = SEED, year: int = YEAR):
    from scripts.expanded_historical import load_historical_dataset

    return load_historical_dataset(year, parts=parts, part=part, seed=seed)


def smoke_sample(dataset, households: int, seed: int):
    """A fixed subsample: one candidate household from every state the part holds,
    then random candidate and non-candidate households, about two to one, up to
    ``households``. Stored inputs choose it; weights stay as they are."""
    from cliffs2017.deflate import _keep_households

    p = dataset.person
    candidate = eligible_nonworkers(
        p.age,
        p.employment_income_before_lsr,
        p.self_employment_income_before_lsr,
        p.sstb_self_employment_income_before_lsr,
        p.is_full_time_college_student,
        p.is_disabled,
    )
    hh = dataset.household
    has = hh.household_id.isin(set(p.loc[candidate, "person_household_id"]))
    chosen = []
    for _, group in hh[has].groupby("state_fips"):
        chosen += group.sample(n=1, random_state=seed).household_id.tolist()
    if households < len(chosen):
        raise ValueError(f"a smoke sample needs at least {len(chosen)} households")
    left = households - len(chosen)
    pool = hh[has & ~hh.household_id.isin(chosen)]
    chosen += pool.sample(n=min(2 * left // 3, len(pool)), random_state=seed).household_id.tolist()
    pool = hh[~has]
    chosen += pool.sample(n=min(households - len(chosen), len(pool)), random_state=seed).household_id.tolist()
    sample = _keep_households(dataset, hh.household_id.isin(chosen).to_numpy(), 1.0)
    return sample, {"households": len(sample.household), "people": len(sample.person),
                    "states_with_a_candidate_household": int(hh[has].state_fips.nunique())}


def build(dataset, year: int = YEAR):
    from scripts.expanded_historical import build_historical_simulation

    sim = build_historical_simulation(dataset, year, health=True)
    register_analysis_variables(sim.tax_benefit_system)
    return sim


def scoped_hourly_wages(state, rates: dict, known=JURISDICTIONS):
    """Each person's rate where the table resolves their state, with MicroSeries
    arithmetic so the weight context stays; ``covered`` marks those people."""
    from microdf import MicroSeries

    present = set(np.unique(np.asarray(state)).tolist())
    if present - set(known):
        raise ValueError(f"state codes outside the 51 jurisdictions: {sorted(present - set(known))}")
    hourly = (state == "__no_state__") * 0.0
    covered = state == "__no_state__"
    for code, wage in rates.items():
        match = state == code
        covered = covered | match
        hourly = hourly + match * wage
    if not isinstance(hourly, MicroSeries) or not isinstance(covered, MicroSeries):
        raise TypeError("wage mapping must retain MicroSeries metadata")
    return hourly, covered


def in_states(state, codes):
    out = state == "__no_state__"
    for code in codes:
        out = out | (state == code)
    return out


def candidates(sim, rates: dict, scope: str, year: int = YEAR) -> dict:
    eligible = sim.calc("expanded_job_eligible", period=year)
    rank = sim.calc("expanded_job_rank", period=year)
    state = sim.calc("state_code_str", period=year, map_to="person")
    hourly, covered = scoped_hourly_wages(state, rates)
    explicit = scope_states(scope)
    if explicit is not None and set(explicit) - set(rates):
        raise ValueError(f"scope {scope} names unresolved states {sorted(set(explicit) - set(rates))}")
    in_scope = covered if explicit is None else in_states(state, explicit)
    return dict(eligible=eligible, rank=rank, state=state, hourly=hourly, in_scope=in_scope)


def sample_counts_by_state(mask, state) -> dict:
    """Unweighted sample record counts, for completeness checks across scopes."""
    values = np.asarray(state)[np.asarray(mask, dtype=bool)]
    codes, counts = np.unique(values, return_counts=True)
    return {str(c): int(n) for c, n in zip(codes, counts)}


def plan(sim, rates: dict, scope: str, year: int = YEAR) -> dict:
    """Candidates by rank in scope, and the deferred ones, for one part."""
    c = candidates(sim, rates, scope, year)
    eligible = np.asarray(c["eligible"], dtype=bool)
    rank = np.asarray(c["rank"])
    scoped = eligible & np.asarray(c["in_scope"], dtype=bool)
    by_rank = {int(k): int(n) for k, n in zip(*np.unique(rank[scoped], return_counts=True))}
    return {
        "sample_candidates": int(eligible.sum()),
        "sample_candidates_in_scope": int(scoped.sum()),
        "weighted_candidates_in_scope": float((c["eligible"] & c["in_scope"]).sum()),
        "sample_candidates_by_rank": by_rank,
        "max_rank": max(by_rank) if by_rank else 0,
        "sample_candidates_in_scope_by_state": sample_counts_by_state(scoped, c["state"]),
        "sample_candidates_outside_scope_by_state": sample_counts_by_state(eligible & ~scoped, c["state"]),
    }


def _check(value, ok: bool, **extra) -> dict:
    return {"value": value, "pass": bool(ok), **extra}


def run_rank(sim, dataset, k: int, rates: dict, scope: str, *, year: int = YEAR,
             fresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Rows for every in-scope candidate of rank ``k``, and the checks that passed."""
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
    )

    from cliffs2017.changes import health_parts
    from cliffs2017.decompose import NET, components, household_values

    timing = {}
    t = time.time()
    person_id = np.asarray(sim.calc("person_id", period=year))
    household_id = np.asarray(sim.calc("household_id", period=year, map_to="person"))
    if not np.array_equal(person_id, dataset.person.person_id.to_numpy()):
        raise RuntimeError("simulation people are not in the dataset's person order")
    if not np.array_equal(household_id, dataset.person.person_household_id.to_numpy()):
        raise RuntimeError("simulation households differ from the dataset's person mapping")
    c = candidates(sim, rates, scope, year)
    selected = c["eligible"] & c["in_scope"] & (c["rank"] == k)
    sel = np.asarray(selected, dtype=bool)
    if not sel.any():
        raise ValueError(f"rank {k} has no candidates in scope {scope}")
    state = np.asarray(c["state"]).astype(str)
    household_index = np.asarray(sim.populations["household"].members_entity_id)
    parts = components(sim, year)
    names = [name for name, _ in parts]
    health = set(health_parts(sim, year))
    tracked = names + [NET, RESOURCES]
    base = household_values(sim, tracked, year)
    timing["baseline"] = round(time.time() - t, 1)

    t = time.time()
    zero = create_perturbed_branch(
        sim, year, "expanded_job_zero_change", {"employment_income": c["eligible"] * 0}
    )
    zero_values = household_values(zero, tracked, year)
    zero_max = max(float(np.abs(zero_values[v] - base[v]).max()) for v in tracked)
    del sim.branches["expanded_job_zero_change"], zero, zero_values
    gc.collect()
    if zero_max != 0:
        raise RuntimeError(f"zero-change branch moved a household measure by {zero_max}")
    timing["zero_change_branch"] = round(time.time() - t, 1)

    t = time.time()
    name, branch, gross = make_job_branch(sim, selected, c["hourly"], k, year)
    alt = household_values(branch, tracked, year)
    d = {v: alt[v] - base[v] for v in tracked}
    signed = {v: sign * d[v] for v, sign in parts}
    d_parts = sum(signed.values())
    d_without = sum(signed[v] for v in names if f"d_{v}" not in health)
    d_single = d[NET] + (d[PREMIUM] if PREMIUM in d else 0.0)
    d_with = d[RESOURCES]

    household_flag, member_flag = map_flag(sim, selected, year)
    touched = np.asarray(household_flag, dtype=bool)
    touched_index = np.zeros(len(touched), dtype=bool)
    touched_index[household_index[sel]] = True
    if not np.array_equal(touched, touched_index):
        raise RuntimeError("model household mapping disagrees with the person index")
    outside = max(float(np.abs(d[v][~touched]).max()) if (~touched).any() else 0.0 for v in tracked)
    if outside != 0:
        raise RuntimeError(f"job entry changed an untouched household by {outside}")

    expected = np.array([rates[s] for s in state[sel]], dtype=np.float64) * HOURS_PER_YEAR
    earnings_alt = sum(np.asarray(branch.calc(v, period=year), dtype=np.float64) for v in EARNINGS)
    earnings_base = sum(np.asarray(sim.calc(v, period=year), dtype=np.float64) for v in EARNINGS)
    gross_error = float(np.abs(earnings_alt[sel] - expected).max())
    series_error = float(np.abs(np.asarray(gross, dtype=np.float64)[sel] - expected).max())
    others_error = float(np.abs(earnings_alt[~sel] - earnings_base[~sel]).max()) if (~sel).any() else 0.0
    hours = np.asarray(branch.calc("weekly_hours_worked", period=year))[sel]
    weeks = np.asarray(branch.calc("weeks_worked", period=year))[sel]
    if gross_error > GROSS_TOLERANCE or series_error > 1e-6:
        raise RuntimeError(f"job earnings don't equal the table rate x 2080: {gross_error}, {series_error}")
    if others_error != 0:
        raise RuntimeError(f"job branch changed a non-entrant's earnings by {others_error}")
    if not (hours == 40).all() or not (weeks == 52).all():
        raise RuntimeError("job branch failed the full-time hours/weeks identity")
    wic_changed = [
        month for month in range(1, 13)
        if not np.array_equal(
            np.asarray(branch.calc("takes_up_wic_if_eligible", period=f"{year}-{month:02d}")),
            np.asarray(sim.calc("takes_up_wic_if_eligible", period=f"{year}-{month:02d}")),
        )
    ]
    if wic_changed:
        raise RuntimeError(f"job branch changed the stored WIC take-up draw in months {wic_changed}")
    parts_error = float(np.abs(d_parts - d[NET]).max())
    measure_error = float(np.abs(d_single - d_with).max())
    if parts_error > MEASURE_TOLERANCE or measure_error > MEASURE_TOLERANCE:
        raise RuntimeError(f"decomposition disagrees: parts {parts_error}, PTC-once {measure_error}")
    timing["job_branch_and_checks"] = round(time.time() - t, 1)

    fresh_error = None
    if fresh:
        t = time.time()
        fresh_sim = fresh_job_simulation(dataset, sim, selected, c["hourly"], year)
        fresh_values = household_values(fresh_sim, [RESOURCES], year)[RESOURCES]
        fresh_error = float(np.abs(fresh_values - alt[RESOURCES]).max())
        del fresh_sim, fresh_values
        gc.collect()
        if fresh_error > MEASURE_TOLERANCE:
            raise RuntimeError(f"branch disagrees with a fresh input simulation by {fresh_error}")
        timing["fresh_simulation"] = round(time.time() - t, 1)

    households = household_index[sel]
    rows = pd.DataFrame({
        "person_index": np.flatnonzero(sel),
        "person_id": person_id[sel],
        "household_id": household_id[sel],
        "state_code": state[sel],
        "rank": k,
        "hourly_wage": np.asarray(c["hourly"], dtype=np.float64)[sel],
        "gross_pay": expected,
        "d_net_single_ptc": d_with[households],
        "d_net_without_health": d_without[households],
        "d_net": d[NET][households],
    })
    for v in names:
        rows[f"d_{v}"] = signed[v][households]
    weighted_tested = float(selected.sum())
    weighted_members = float(member_flag.sum())
    del sim.branches[name], branch, alt
    gc.collect()

    below = {}
    for measure in ("d_net_single_ptc", "d_net_without_health"):
        below[measure] = {
            f"keeps_less_than_{cutoff:g}": int((rows[measure] < cutoff * rows["gross_pay"]).sum())
            for cutoff in THRESHOLDS
        }
    identities = {
        "zero_change_max_household_change": _check(zero_max, zero_max == 0),
        "untouched_household_max_change": _check(outside, outside == 0,
                                                 untouched_households=int((~touched).sum())),
        "entrant_earnings_max_error_vs_rate_x_2080": _check(gross_error, gross_error <= GROSS_TOLERANCE,
                                                           tolerance=GROSS_TOLERANCE),
        "non_entrant_earnings_max_change": _check(others_error, others_error == 0),
        "entrant_hours_40_weeks_52": _check(True, True),
        "wic_draw_months_changed": _check(wic_changed, not wic_changed),
        "parts_sum_to_net_income_max_error": _check(parts_error, parts_error <= MEASURE_TOLERANCE),
        "ptc_once_measure_vs_decomposition_max_error": _check(measure_error,
                                                              measure_error <= MEASURE_TOLERANCE),
    }
    if fresh:
        identities["fresh_simulation_max_difference"] = _check(fresh_error,
                                                               fresh_error <= MEASURE_TOLERANCE)
    record = {
        "status": "complete",
        "rank": k,
        "scope": scope_tag(scope),
        "counts": {
            "sample_candidates_tested": int(sel.sum()),
            "sample_households_touched": int(touched.sum()),
            "sample_candidates_tested_by_state": sample_counts_by_state(sel, state),
            "weighted_candidates_tested": weighted_tested,
            "weighted_members_of_touched_households": weighted_members,
            "sample_tested_below_threshold": below,
        },
        "identities": identities,
        "measures": {
            "d_net_single_ptc": "change in household_net_income + marketplace_net_premium with health "
                                "coverage at government cost (the pilot's expanded_job_resources; "
                                "premium tax credit counted once)",
            "d_net_without_health": "sum of the changes in every part of net income except "
                                    "gov.household.household_health_benefits and household_health_costs",
            "d_net": "change in household_net_income as modelled (credit counted twice for "
                     "premium-paying enrollees)",
        },
        "component_columns": [f"d_{v}" for v in names],
        "health_columns": sorted(health),
        "timing_seconds": timing,
    }
    return rows, record


def write_pair(rows: pd.DataFrame, record: dict, csv_rel: str, extra: dict) -> tuple[bytes, bytes]:
    """Serialize a validated pair: CSV bytes, then the JSON that names and hashes it."""
    buffer = io.StringIO()
    rows.to_csv(buffer, index=False)
    csv_bytes = csv_gzip(buffer.getvalue())
    record = dict(record, **extra)
    record["rows"] = {
        "file": csv_rel,
        "sha256": sha256(csv_bytes),
        "count": len(rows),
        "columns": list(rows.columns),
        "record_level": "git-ignored; never commit",
    }
    json_bytes = (json.dumps(record, indent=1, default=_json_scalar) + "\n").encode()
    validate_pair(json_bytes, csv_bytes)
    return json_bytes, csv_bytes


def _json_scalar(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def provenance(expected_wages_sha256: str | None = None) -> dict:
    from scripts.expanded_historical import historical_provenance

    table = national_wage_table()
    if expected_wages_sha256 and table["wages_json_sha256"] != expected_wages_sha256:
        raise RuntimeError("the container's wages.json differs from the launching checkout's")
    return {
        "year": YEAR,
        "parts": PARTS,
        "seed": SEED,
        "historical": historical_provenance(),
        "code": code_record(),
        "wages_json_sha256": table["wages_json_sha256"],
        "rates_used": table["rates"],
        "wage_table": wage_table_fingerprint(table),
        "unresolved_wages": table["unresolved"],
        "python": platform.python_version(),
        "numpy": metadata.version("numpy"),
    }, table
