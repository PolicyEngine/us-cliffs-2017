"""Paths, validation, resume checks and safe installation for the national job-entry results.

One result is one candidate rank of one household part under one wage scope: a
JSON record and a gzipped CSV of person rows. The JSON is the completion marker.
It names its CSV, which carries a unique run id, and records the CSV's SHA-256,
columns and row count, and the outcome of every identity check. Only a pair that
passes ``validate_pair`` is published to the Modal volume or installed in the
checkout; a CSV that no valid JSON names is ignored.

``validate_pair`` is strict: the record must carry every named identity check,
each passing and with a value inside its rule; the rows must have the complete
column schema, one rank, unique people and households, rates and gross pay
matching the record's wage table, and finite measures. ``validate_results``
checks a whole set of results against their plans: every planned rank present,
counts and states as planned, no person in two ranks or scopes, each
household's candidates ranked 1..n, and each jurisdiction tested by one scope.

A result is reused only through ``existing_result``, the one check behind both
the volume skip and the local skip. It reuses a record only when its resume
fingerprint matches the launch's: the code of the job-entry modules, the dataset,
the package pins, the request (part, rank, scope), the planned candidate count
and the resolved wage table. The wage table enters as each jurisdiction's dated
path and effective rate, so an edit to wages.json's metadata alone leaves
results valid. A mismatch stops the run and names every difference; nothing is
overwritten.

Installing never overwrites. Each file is written under a unique temporary
name in its target directory and hard-linked into place, which fails if the
target exists; the temporary name is then removed. The volume side uses
Modal's batch upload with overwriting disallowed, so both files of a pair go in
one request and an existing record stays. ``settle`` collects every failed
container, missing rank and install conflict of a launch, and
``require_success`` turns any of them into a nonzero exit that names each one.

Standard library only, so the Modal client's own Python can import it.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.job_entry_wages import HOURS_PER_YEAR, JURISDICTIONS  # noqa: E402

YEAR = 2017
PARTS = 4
SEED = 0
BASE = "results/job_entry"
SCOPE_ALL_RESOLVED = "resolved"
# The files whose committed state each result records; a launch refuses uncommitted ones.
CODE_FILES = (
    "scripts/expanded_job_entry_national.py",
    "scripts/expanded_job_entry.py",
    "scripts/expanded_historical.py",
    "scripts/job_entry_wages.py",
    "scripts/job_entry_outputs.py",
    "scripts/modal_job_entry.py",
    "research/minimum-wages-2017/wages.json",
)
# The code a result's resume fingerprint holds: the job-entry modules and cliffs2017/.
# wages.json is left out here; the resolved wage table stands for it.
JOB_ENTRY_MODULES = tuple(rel for rel in CODE_FILES if rel.endswith(".py"))
REQUIREMENTS = "scripts/modal-requirements.txt"
MEDICAID_TOTALS = f"results/medicaid/totals_{YEAR}_p{PARTS}_s{SEED}.json"
SOURCE_DATASET = "policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260909"
RESUME_FIELDS = ("code", "dataset", "packages", "wage_table", "request", "planned_candidates")
PLAN_RESUME_FIELDS = ("code", "dataset", "packages", "wage_table", "request")

# Every national record carries these checks (expanded_job_entry_national.run_rank),
# each with the rule its value must meet; a smoke record adds the fresh simulation.
GROSS_TOLERANCE = 0.02
MEASURE_TOLERANCE = 1.0
IDENTITY_RULES = {
    "zero_change_max_household_change": lambda v: _number(v) and v == 0,
    "untouched_household_max_change": lambda v: _number(v) and v == 0,
    "entrant_earnings_max_error_vs_rate_x_2080": lambda v: _number(v) and 0 <= v <= GROSS_TOLERANCE,
    "non_entrant_earnings_max_change": lambda v: _number(v) and v == 0,
    "entrant_hours_40_weeks_52": lambda v: v is True,
    "wic_draw_months_changed": lambda v: v == [],
    "parts_sum_to_net_income_max_error": lambda v: _number(v) and 0 <= v <= MEASURE_TOLERANCE,
    "ptc_once_measure_vs_decomposition_max_error": lambda v: _number(v) and 0 <= v <= MEASURE_TOLERANCE,
}
FRESH_CHECK = "fresh_simulation_max_difference"
FRESH_RULE = lambda v: _number(v) and 0 <= v <= MEASURE_TOLERANCE  # noqa: E731
# The row schema: identity columns, then measures, then the record's component columns.
ID_COLUMNS = ("person_index", "person_id", "household_id", "state_code", "rank", "hourly_wage", "gross_pay")
MEASURE_COLUMNS = ("d_net_single_ptc", "d_net_without_health", "d_net")
RATE_TOLERANCE = 1e-9
PAY_TOLERANCE = 1e-6


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scope_tag(scope: str) -> str:
    """A file-safe name: ``resolved``, or ``states-MD-NY`` for ``states:MD,NY``."""
    if scope == SCOPE_ALL_RESOLVED:
        return scope
    if scope.startswith("states-"):
        scope = "states:" + scope[len("states-"):].replace("-", ",")
    if scope.startswith("states:"):
        codes = sorted(c.strip().upper() for c in scope[len("states:"):].split(",") if c.strip())
        if codes and all(len(c) == 2 and c.isalpha() for c in codes):
            return "states-" + "-".join(codes)
    raise ValueError(f"scope must be 'resolved' or 'states:XX,YY', not {scope!r}")


def scope_states(scope: str) -> list[str] | None:
    """The explicit states of a ``states:`` scope, or None for every resolved state."""
    tag = scope_tag(scope)
    return None if tag == SCOPE_ALL_RESOLVED else tag.split("-")[1:]


def part_stem(part: int, *, year: int = YEAR, parts: int = PARTS, seed: int = SEED) -> str:
    return f"job_entry_{year}_p{parts}_{part}_s{seed}"


def smoke_stem(part: int, households: int, sample_seed: int) -> str:
    return f"smoke_{part_stem(part)}_h{households}_seed{sample_seed}"


def result_json(stem: str, scope: str, rank: int) -> str:
    """The completion record's fixed path: one per (stem, scope, rank)."""
    return f"{BASE}/parts/{stem}/{scope_tag(scope)}/rank_{rank:02d}.json"


def result_csv(stem: str, scope: str, rank: int, run_id: str) -> str:
    """Person rows, git-ignored under per_person/, named by the run that wrote them."""
    if not run_id.isalnum():
        raise ValueError("run id must be alphanumeric")
    return f"{BASE}/per_person/{stem}_{scope_tag(scope)}_rank_{rank:02d}_{run_id}.csv.gz"


def plan_json(part: int, scope: str) -> str:
    return f"{BASE}/plan/{part_stem(part)}_{scope_tag(scope)}.json"


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


def csv_gzip(text: str) -> bytes:
    """Deterministic gzip: no file name or timestamp in the header."""
    return gzip.compress(text.encode(), mtime=0)


# ---------------------------------------------------------------------------
# Fingerprints


def cliffs2017_digest(root: Path) -> str:
    """cliffs2017.run.code_version()'s hash of cliffs2017/, without importing it."""
    digest = hashlib.sha256()
    for path in sorted((Path(root) / "cliffs2017").rglob("*")):
        if path.is_file() and path.suffix in (".py", ".csv"):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def code_fingerprint(root: Path) -> dict:
    """The job-entry modules' SHA-256 and cliffs2017/'s digest (wages.json excluded)."""
    root = Path(root)
    return {"files": {rel: sha256((root / rel).read_bytes()) for rel in JOB_ENTRY_MODULES},
            "cliffs2017": cliffs2017_digest(root)}


def wage_table_fingerprint(table: dict) -> dict:
    """The resolved wage table: each jurisdiction's dated path and exact effective rate.

    The raw wages.json bytes are not used, so an edit to its metadata, notes or
    sources alone leaves the fingerprint, and every result, unchanged.
    """
    resolved = {
        code: {"path": [[p["from"], p["to"], p["hourly"]] for p in row["path"]],
               "hourly_exact": row["hourly_exact"]}
        for code, row in sorted(table["rows"].items())
    }
    unresolved = sorted(table["unresolved"])
    canonical = json.dumps({"resolved": resolved, "unresolved": unresolved}, sort_keys=True)
    return {"sha256": sha256(canonical.encode()), "jurisdictions": len(resolved), "unresolved": unresolved,
            "rates": {code: table["rates"][code] for code in sorted(table["rates"])}}


def local_environment(root: Path) -> dict:
    """What a checkout fixes about a result: its code, package pins and the Medicaid totals.

    A container's ``expanded_job_entry_national.environment()`` adds the dataset
    file's SHA-256, the installed versions and the Python version.
    """
    root = Path(root)
    return {
        "code": code_fingerprint(root),
        "dataset": {"source": SOURCE_DATASET, "year": YEAR, "parts": PARTS, "seed": SEED,
                    "medicaid_totals_sha256": sha256((root / MEDICAID_TOTALS).read_bytes())},
        "packages": {"requirements_sha256": sha256((root / REQUIREMENTS).read_bytes())},
    }


def environment_differences(local: dict, container: dict) -> list[str]:
    """Where a container's environment disagrees with what the launching checkout fixes."""
    problems = []
    for section, values in local.items():
        theirs = container.get(section) or {}
        for key, value in values.items():
            if theirs.get(key) != value:
                problems.append(f"{section}.{key}")
    return problems


def request_identity(part: int, rank: int, scope: str, smoke_households: int = 0,
                     smoke_seed: int | None = None) -> dict:
    return {"part": int(part), "rank": int(rank), "scope": scope_tag(scope),
            "smoke_households": int(smoke_households),
            "smoke_seed": int(smoke_seed) if smoke_households else None}


def resume_expectation(environment: dict, wage_table: dict, request: dict, planned: int | None) -> dict:
    """The fingerprint a reusable rank result must carry."""
    return {"code": environment["code"], "dataset": environment["dataset"], "packages": environment["packages"],
            "wage_table": wage_table, "request": request,
            "planned_candidates": None if planned is None else int(planned)}


def plan_expectation(environment: dict, wage_table: dict, part: int, scope: str) -> dict:
    """The fingerprint a reusable plan must carry."""
    return {"code": environment["code"], "dataset": environment["dataset"], "packages": environment["packages"],
            "wage_table": wage_table, "request": {"part": int(part), "scope": scope_tag(scope)}}


def _brief(value) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= 120 else f"{text[:60]}... (sha256 {sha256(text.encode())[:12]})"


def differences(stored, expected, prefix: str) -> list[str]:
    """Each leaf where two fingerprints differ, named by its dotted path."""
    if isinstance(stored, dict) and isinstance(expected, dict):
        out = []
        for key in sorted(set(stored) | set(expected)):
            out += differences(stored.get(key), expected.get(key), f"{prefix}.{key}")
        return out
    if stored != expected:
        return [f"{prefix}: recorded {_brief(stored)}, expected {_brief(expected)}"]
    return []


def resume_mismatches(record: dict, expected: dict) -> list[str]:
    """Every way a record's provenance differs from the launch's expectation; empty if reusable."""
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    stored = provenance.get("resume")
    if not isinstance(stored, dict):
        return ["the record carries no resume fingerprint (written before resume checks)"]
    problems = []
    for key in RESUME_FIELDS:
        problems += differences(stored.get(key), expected.get(key), key)
    # The fingerprint must also describe the record itself.
    request = expected["request"]
    for key in ("part", "rank", "scope"):
        if record.get(key) != request[key]:
            problems.append(f"record {key} is {record.get(key)!r}, requested {request[key]!r}")
    if bool(record.get("smoke")) != bool(request["smoke_households"]):
        problems.append("record smoke flag differs from the request")
    planned = expected["planned_candidates"]
    tested = (record.get("counts") or {}).get("sample_candidates_tested")
    if planned is not None and tested != planned:
        problems.append(f"record tested {tested} candidates, the plan counts {planned}")
    hashes = (provenance.get("code") or {}).get("sha256") or {}
    for rel, digest in expected["code"]["files"].items():
        if hashes.get(rel) != digest:
            problems.append(f"record code hash for {rel} differs")
    if provenance.get("rates_used") != expected["wage_table"]["rates"]:
        problems.append("record rates_used differ from the resolved wage table")
    return problems


def plan_mismatches(plan_record: dict, expected: dict) -> list[str]:
    provenance = plan_record.get("provenance") if isinstance(plan_record.get("provenance"), dict) else {}
    stored = provenance.get("resume")
    if not isinstance(stored, dict):
        return ["the plan carries no resume fingerprint (written before resume checks)"]
    problems = []
    for key in PLAN_RESUME_FIELDS:
        problems += differences(stored.get(key), expected.get(key), key)
    request = expected["request"]
    if plan_record.get("part") != request["part"] or plan_record.get("scope") != request["scope"]:
        problems.append(f"plan describes part {plan_record.get('part')!r} scope {plan_record.get('scope')!r}")
    return problems


class StaleResult(RuntimeError):
    """An existing result or plan that may not be reused: damaged, or written under other inputs."""


def existing_result(json_bytes: bytes | None, read_rows, expected: dict, where: str) -> dict | None:
    """The record at a rank's fixed path when it may be reused; None when there is none.

    The one check behind the volume skip and the local skip. ``read_rows(rel)``
    returns the bytes of a rows file or None. A record that is unreadable, lacks
    its rows, fails ``validate_pair`` or differs from ``expected`` in any resume
    field raises StaleResult naming each problem: its path is never overwritten,
    so the run stops rather than resume from it or silently redo it.
    """
    if json_bytes is None:
        return None
    try:
        record = json.loads(json_bytes)
        csv_rel = record["rows"]["file"]
    except (ValueError, KeyError, TypeError) as error:
        raise StaleResult(f"{where}: unreadable record ({error!r}); not resuming") from None
    csv_bytes = read_rows(csv_rel)
    if csv_bytes is None:
        raise StaleResult(f"{where}: the record's rows {csv_rel} are missing; not resuming")
    request = expected["request"]
    try:
        validate_pair(json_bytes, csv_bytes, dict(part=request["part"], rank=request["rank"], scope=request["scope"]))
    except (ValueError, KeyError, TypeError) as error:
        raise StaleResult(f"{where}: invalid pair ({error}); not resuming") from None
    problems = resume_mismatches(record, expected)
    if problems:
        raise StaleResult(f"{where} was written under other inputs; not resuming:\n  " + "\n  ".join(problems))
    return record


def existing_plan(json_bytes: bytes | None, expected: dict, where: str) -> dict | None:
    """A plan that may be reused, None when absent; StaleResult when it differs."""
    if json_bytes is None:
        return None
    try:
        plan_record = json.loads(json_bytes)
    except ValueError as error:
        raise StaleResult(f"{where}: unreadable plan ({error!r})") from None
    problems = plan_mismatches(plan_record, expected)
    if problems:
        raise StaleResult(f"{where} was planned under other inputs; not reusing it:\n  " + "\n  ".join(problems))
    return plan_record


def reusable_pair(read, json_rel: str, expected: dict, where: str) -> tuple[bytes, bytes] | None:
    """The bytes of a pair at ``json_rel`` that may be reused, None if absent (the volume skip).

    ``read(rel)`` returns a file's bytes or None. Every check is ``existing_result``'s.
    """
    json_bytes = read(json_rel)
    record = existing_result(json_bytes, read, expected, where)
    if record is None:
        return None
    return json_bytes, read(record["rows"]["file"])


def ranks_to_run(plans: dict, scope: str, environment: dict, wage_table: dict, read,
                 ranks=None, log=print) -> list[tuple[int, int, dict]]:
    """The (part, rank, expectation) of every planned rank a launch must run (the local skip).

    A rank whose record is installed under ``read`` is skipped only when
    ``existing_result`` accepts it against this launch's expectation; any other
    installed record stops the launch with StaleResult.
    """
    wanted = None if ranks is None else {int(r) for r in ranks}
    jobs = []
    for part in sorted(plans):
        by_rank = plans[part]["plan"]["sample_candidates_by_rank"]
        for rank, planned in sorted((int(k), n) for k, n in by_rank.items()):
            if not planned or (wanted is not None and rank not in wanted):
                continue
            rel = result_json(part_stem(part), scope, rank)
            expected = resume_expectation(environment, wage_table, request_identity(part, rank, scope), planned)
            if existing_result(read(rel), read, expected, f"local {rel}") is None:
                jobs.append((part, rank, expected))
            else:
                log(f"part {part} rank {rank}: installed with a matching fingerprint; skipped")
    return jobs


def read_local(root: Path):
    """A reader for ``existing_result``: the bytes of root/rel, or None if absent."""
    def read(rel: str) -> bytes | None:
        path = Path(root) / rel
        return path.read_bytes() if path.is_file() else None
    return read


# ---------------------------------------------------------------------------
# Pair validation


def validate_pair(json_bytes: bytes, csv_bytes: bytes, expect: dict | None = None) -> dict:
    """The record, if it is complete, every named check passed within its rule, and it
    describes exactly this CSV: the full schema, one rank, unique people and
    households, rates and pay from its wage table, and finite measures."""
    record = json.loads(json_bytes)
    if record.get("status") != "complete":
        raise ValueError(f"record status is {record.get('status')!r}, not 'complete'")
    rank = record.get("rank")
    if not _positive_int(rank):
        raise ValueError(f"record rank {rank!r} is not a positive integer")
    checks = record.get("identities")
    if not isinstance(checks, dict):
        raise ValueError("record lacks identity checks")
    rules = dict(IDENTITY_RULES)
    if record.get("smoke"):
        rules[FRESH_CHECK] = FRESH_RULE
    missing = sorted(set(rules) - set(checks))
    if missing:
        raise ValueError(f"record lacks identity checks {missing}")
    extra = sorted(set(checks) - set(rules) - {FRESH_CHECK})
    if extra:
        raise ValueError(f"record has unknown identity checks {extra}")
    for name, check in checks.items():
        rule = rules.get(name, FRESH_RULE)
        if not isinstance(check, dict) or check.get("pass") is not True or not rule(check.get("value")):
            raise ValueError(f"identity check {name} did not pass: {check!r}")
    components = record.get("component_columns")
    if (not isinstance(components, list) or not components or len(set(components)) != len(components)
            or not all(isinstance(c, str) and c.startswith("d_") for c in components)
            or set(components) & set(ID_COLUMNS + MEASURE_COLUMNS)):
        raise ValueError("record lacks a valid list of component columns")
    columns = [*ID_COLUMNS, *MEASURE_COLUMNS, *components]
    rows = record.get("rows")
    if not isinstance(rows, dict) or rows.get("columns") != columns:
        raise ValueError("record columns are not the complete row schema")
    if sha256(csv_bytes) != rows.get("sha256"):
        raise ValueError("CSV bytes differ from the record's SHA-256")
    rates = (record.get("provenance") or {}).get("rates_used")
    if not isinstance(rates, dict) or not rates or not set(rates) <= JURISDICTIONS:
        raise ValueError("record lacks the wage rates it used")
    counts = record.get("counts") or {}
    reader = csv.reader(io.StringIO(gzip.decompress(csv_bytes).decode()))
    if next(reader, None) != columns:
        raise ValueError("CSV columns differ from the record")
    numeric = ("hourly_wage", "gross_pay", *MEASURE_COLUMNS, *components)
    indices, ids, households, by_state = set(), set(), set(), {}
    count = 0
    for line, row in enumerate(reader, start=2):
        if len(row) != len(columns):
            raise ValueError(f"CSV line {line} has {len(row)} fields, not {len(columns)}")
        values = dict(zip(columns, row))
        try:
            index, person, household, row_rank = (int(values[c]) for c in
                                                  ("person_index", "person_id", "household_id", "rank"))
            numbers = {c: float(values[c]) for c in numeric}
        except ValueError:
            raise ValueError(f"CSV line {line}: a value is not a number") from None
        if index < 0:
            raise ValueError(f"CSV line {line}: negative person_index")
        if index in indices:
            raise ValueError(f"CSV line {line}: person_index {index} appears twice")
        if person in ids:
            raise ValueError(f"CSV line {line}: person_id {person} appears twice")
        if household in households:
            raise ValueError(f"CSV line {line}: household {household} has two tested adults at rank {rank}")
        if row_rank != rank:
            raise ValueError(f"CSV line {line}: rank {row_rank} in a rank-{rank} record")
        bad = [c for c, v in numbers.items() if not math.isfinite(v)]
        if bad:
            raise ValueError(f"CSV line {line}: non-finite {bad}")
        state = values["state_code"]
        if state not in rates:
            raise ValueError(f"CSV line {line}: state {state!r} has no rate in the record")
        if abs(numbers["hourly_wage"] - rates[state]) > RATE_TOLERANCE:
            raise ValueError(f"CSV line {line}: hourly wage differs from {state}'s rate")
        if abs(numbers["gross_pay"] - rates[state] * HOURS_PER_YEAR) > PAY_TOLERANCE:
            raise ValueError(f"CSV line {line}: gross pay differs from the rate times {HOURS_PER_YEAR}")
        indices.add(index)
        ids.add(person)
        households.add(household)
        by_state[state] = by_state.get(state, 0) + 1
        count += 1
    if count == 0:
        raise ValueError("a rank result must test at least one candidate")
    if count != rows.get("count") or count != counts.get("sample_candidates_tested"):
        raise ValueError("CSV row count differs from the record's tested candidates")
    if by_state != counts.get("sample_candidates_tested_by_state"):
        raise ValueError("CSV rows by state differ from the record")
    if len(households) != counts.get("sample_households_touched"):
        raise ValueError("CSV households differ from the record's touched households")
    for key, value in (expect or {}).items():
        if record.get(key) != value:
            raise ValueError(f"record {key} is {record.get(key)!r}, not {value!r}")
    return record


def read_rows(csv_bytes: bytes) -> list[dict]:
    """The identity fields of a validated pair's rows (no measures)."""
    reader = csv.DictReader(io.StringIO(gzip.decompress(csv_bytes).decode()))
    return [{"person_index": int(r["person_index"]), "person_id": int(r["person_id"]),
             "household_id": int(r["household_id"]), "state_code": r["state_code"], "rank": int(r["rank"])}
            for r in reader]


def _plan_universe(plan: dict) -> dict:
    total = dict(plan["sample_candidates_in_scope_by_state"])
    for state, n in plan["sample_candidates_outside_scope_by_state"].items():
        total[state] = total.get(state, 0) + n
    return total


def validate_results(root: Path, scopes: list[str] | None = None, parts=None, ranks=None,
                     require_all: bool = False) -> dict:
    """Strictly validate every result of the named scopes (default: every scope found) against the plans.

    For each part and scope: the plan exists; every planned rank (of ``ranks``, default
    all) has a strictly valid pair testing exactly the planned count; no rank is
    unplanned. Across ranks and scopes of a part: no person index or ID twice; each
    household's candidates in one scope, ranked 1..n; each jurisdiction tested by one
    scope, its tested count equal to the plans' candidates. ``require_all`` also
    requires every jurisdiction with candidates to be tested. Raises ValueError
    naming every problem; returns counts by part and scope and the deferred states.
    """
    root = Path(root)
    parts = list(range(PARTS)) if parts is None else [int(p) for p in parts]
    problems, summary, deferred = [], {}, {}
    for part in parts:
        folder = root / BASE / "parts" / part_stem(part)
        tags = sorted(scope_tag(s) for s in scopes) if scopes else sorted(
            d.name for d in folder.iterdir() if d.is_dir()) if folder.is_dir() else []
        if not tags:
            problems.append(f"part {part}: no results")
            continue
        seen_index, seen_id, household_ranks, universe = {}, {}, {}, None
        tested_states: dict[str, dict[str, int]] = {}
        summary[part] = {}
        for tag in tags:
            where = f"part {part} {tag}"
            plan_path = root / plan_json(part, tag)
            if not plan_path.is_file():
                problems.append(f"{where}: no plan")
                continue
            plan_record = json.loads(plan_path.read_bytes())
            if plan_record.get("part") != part or plan_record.get("scope") != tag:
                problems.append(f"{where}: the plan describes another part or scope")
                continue
            plan = plan_record["plan"]
            total = _plan_universe(plan)
            if universe is None:
                universe = total
            elif universe != total:
                problems.append(f"{where}: plans disagree on the candidates by state")
            planned = {int(k): n for k, n in plan["sample_candidates_by_rank"].items() if n}
            present = {int(p.stem.split("_")[1]) for p in (folder / tag).glob("rank_*.json")}
            if present - set(planned):
                problems.append(f"{where}: records for unplanned ranks {sorted(present - set(planned))}")
            wanted = sorted(planned if ranks is None else set(planned) & {int(r) for r in ranks})
            by_state, tested = {}, 0
            for rank in wanted:
                json_rel = result_json(part_stem(part), tag, rank)
                if rank not in present:
                    problems.append(f"{where} rank {rank}: missing")
                    continue
                json_bytes = (root / json_rel).read_bytes()
                try:
                    csv_rel = json.loads(json_bytes)["rows"]["file"]
                    csv_bytes = (root / csv_rel).read_bytes()
                    record = validate_pair(json_bytes, csv_bytes, dict(part=part, rank=rank, scope=tag))
                except (OSError, KeyError, ValueError, TypeError) as error:
                    problems.append(f"{where} rank {rank}: {error}")
                    continue
                if record["counts"]["sample_candidates_tested"] != planned[rank]:
                    problems.append(f"{where} rank {rank}: tested {record['counts']['sample_candidates_tested']}, "
                                    f"planned {planned[rank]}")
                for row in read_rows(csv_bytes):
                    for key, seen in (("person_index", seen_index), ("person_id", seen_id)):
                        other = seen.setdefault(row[key], (tag, rank))
                        if other != (tag, rank):
                            problems.append(f"part {part}: {key} {row[key]} in {other[0]} rank {other[1]} "
                                            f"and {tag} rank {rank}")
                    household_ranks.setdefault(row["household_id"], []).append((tag, rank))
                    by_state[row["state_code"]] = by_state.get(row["state_code"], 0) + 1
                    tested += 1
            if ranks is None and by_state != plan["sample_candidates_in_scope_by_state"]:
                problems.append(f"{where}: tested states differ from the plan")
            for state, n in by_state.items():
                tested_states.setdefault(state, {})[tag] = n
            summary[part][tag] = {"ranks": wanted, "sample_candidates_tested": tested}
        if ranks is None:
            for household, held in household_ranks.items():
                if len({tag for tag, _ in held}) != 1 or sorted(r for _, r in held) != list(range(1, len(held) + 1)):
                    problems.append(f"part {part}: household {household} has candidate ranks {sorted(held)}")
            for state, by_tag in tested_states.items():
                if len(by_tag) != 1:
                    problems.append(f"part {part}: {state} tested by scopes {sorted(by_tag)}")
                elif universe is not None and sum(by_tag.values()) != universe.get(state, 0):
                    problems.append(f"part {part}: {state} tested {sum(by_tag.values())} of {universe.get(state, 0)}")
            for state, n in sorted((universe or {}).items()):
                if n and state not in tested_states:
                    deferred[state] = deferred.get(state, 0) + n
    if require_all and deferred:
        problems.append(f"untested jurisdictions: {deferred}")
    if problems:
        raise ValueError(f"{len(problems)} problems:\n  " + "\n  ".join(problems))
    return {"parts": summary, "deferred": deferred}


# ---------------------------------------------------------------------------
# Installation and run outcome


def install_bytes(root: Path, rel: str, data: bytes) -> str:
    """Write ``data`` at ``root/rel`` unless a file is there: 'wrote', 'same' or 'differs'."""
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        os.chmod(tmp, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
            return "wrote"
        except FileExistsError:
            return "same" if path.read_bytes() == data else "differs"
    finally:
        os.unlink(tmp)


def install_pair(root: Path, json_rel: str, json_bytes: bytes, csv_bytes: bytes,
                 expect: dict | None = None) -> str:
    """Install a validated pair, CSV first and JSON last, never overwriting."""
    record = validate_pair(json_bytes, csv_bytes, expect)
    csv_rel = record["rows"]["file"]
    csv_state = install_bytes(root, csv_rel, csv_bytes)
    if csv_state == "differs":
        return f"conflict: {csv_rel} differs locally; {json_rel} not installed"
    json_state = install_bytes(root, json_rel, json_bytes)
    if json_state == "differs":
        return f"conflict: kept the local {json_rel}; another run's record differs"
    return f"{json_state} {json_rel}"


def installed(state: str) -> bool:
    """Whether an install_pair outcome left this exact pair in place."""
    return state.startswith(("wrote ", "same "))


def local_record(root: Path, json_rel: str) -> dict | None:
    """The installed record when it and its CSV validate, else None (no resume check)."""
    path = Path(root) / json_rel
    if not path.exists():
        return None
    json_bytes = path.read_bytes()
    try:
        csv_rel = json.loads(json_bytes)["rows"]["file"]
        return validate_pair(json_bytes, (Path(root) / csv_rel).read_bytes())
    except (OSError, KeyError, ValueError, TypeError):
        return None


def settle(jobs, results, install, log=print) -> list[str]:
    """Install each returned pair and collect every problem of a launch.

    ``jobs`` are the launched (part, rank, ...) tuples; ``results`` yields each
    container's packet or exception; ``install(packet)`` returns an install_pair
    outcome. Returns one line per failed container, install conflict and rank left
    without an installed pair.
    """
    wanted = {(int(job[0]), int(job[1])) for job in jobs}
    done, problems = set(), []
    for result in results:
        if isinstance(result, BaseException):
            line = f"a container failed: {result!r}"[:2000]
            log(line)
            problems.append(line)
            continue
        key = (int(result["part"]), int(result["rank"]))
        state = install(result)
        log(f"part {key[0]} rank {key[1]} {result['scope']}: {result['status']}; {state}")
        if installed(state):
            done.add(key)
        else:
            problems.append(f"part {key[0]} rank {key[1]} {result['scope']}: {state}")
    for part, rank in sorted(wanted - done):
        problems.append(f"part {part} rank {rank}: no complete pair installed")
    return problems


def require_success(problems: list[str], what: str = "the run") -> None:
    """Exit nonzero, naming each problem, unless there are none."""
    if problems:
        raise SystemExit(f"{what} failed: {len(problems)} problems\n  " + "\n  ".join(problems))


def finish_launch(jobs, results, install, root: Path, parts, ranks=None, log=print) -> dict:
    """Settle a launch, strictly validate what is installed, and exit nonzero on any problem.

    Every failed container, install conflict and rank left without a pair
    (``settle``) and every strict-validation problem (``validate_results``) is
    named in the SystemExit; with none, returns the validation summary.
    """
    problems = settle(jobs, results, install, log)
    summary = None
    try:
        summary = validate_results(root, parts=parts, ranks=ranks)
        log(f"strict validation: {json.dumps(summary, sort_keys=True)}")
    except ValueError as error:
        problems.append(f"strict validation: {error}")
    require_success(problems)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Strictly validate installed job-entry results.")
    parser.add_argument("--root", type=Path, required=True, help="a directory holding results/job_entry/")
    parser.add_argument("--scopes", default="", help="comma-separated scope tags (default: every scope)")
    parser.add_argument("--require-all", action="store_true", help="fail if any jurisdiction is untested")
    args = parser.parse_args(argv)
    scopes = [s for s in args.scopes.split(",") if s] or None
    try:
        summary = validate_results(args.root, scopes, require_all=args.require_all)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
