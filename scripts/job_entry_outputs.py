"""Paths and safe installation for the national job-entry results.

One result is one candidate rank of one household part under one wage scope: a
JSON record and a gzipped CSV of person rows. The JSON is the completion marker.
It names its CSV, which carries a unique run id, and records the CSV's SHA-256,
columns and row count, and that every identity check passed. Only a pair that
validates is published to the Modal volume or installed in the checkout; a CSV
that no valid JSON names is ignored.

Installing never overwrites. Each file is written under a unique temporary
name in its target directory and hard-linked into place, which fails if the
target exists; the temporary name is then removed. The volume side uses
Modal's batch upload with overwriting disallowed, so both files of a pair go in
one request and an existing record stays.

Standard library only, so the Modal client's own Python can import it.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import tempfile
import uuid
from pathlib import Path

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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scope_tag(scope: str) -> str:
    """A file-safe name: ``resolved``, or ``states-MD-NY`` for ``states:MD,NY``."""
    if scope == SCOPE_ALL_RESOLVED:
        return scope
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


def validate_pair(json_bytes: bytes, csv_bytes: bytes, expect: dict | None = None) -> dict:
    """The record, if the JSON is complete, passed, and describes exactly this CSV."""
    record = json.loads(json_bytes)
    if record.get("status") != "complete":
        raise ValueError(f"record status is {record.get('status')!r}, not 'complete'")
    checks = record.get("identities") or {}
    if not checks or not all(check.get("pass") is True for check in checks.values()):
        raise ValueError("record lacks passing identity checks")
    rows = record["rows"]
    if sha256(csv_bytes) != rows["sha256"]:
        raise ValueError("CSV bytes differ from the record's SHA-256")
    reader = csv.reader(io.StringIO(gzip.decompress(csv_bytes).decode()))
    header = next(reader, None)
    if header != rows["columns"]:
        raise ValueError("CSV columns differ from the record")
    count = sum(1 for _ in reader)
    if count != rows["count"] or count != record["counts"]["sample_candidates_tested"]:
        raise ValueError("CSV row count differs from the record's tested candidates")
    if count == 0:
        raise ValueError("a rank result must test at least one candidate")
    for key, value in (expect or {}).items():
        if record.get(key) != value:
            raise ValueError(f"record {key} is {record.get(key)!r}, not {value!r}")
    return record


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
        return f"kept the local {json_rel}; another run's record differs"
    return f"{json_state} {json_rel}"


def local_record(root: Path, json_rel: str) -> dict | None:
    """The installed record when it and its CSV validate, else None."""
    path = Path(root) / json_rel
    if not path.exists():
        return None
    json_bytes = path.read_bytes()
    try:
        csv_rel = json.loads(json_bytes)["rows"]["file"]
        return validate_pair(json_bytes, (Path(root) / csv_rel).read_bytes())
    except (OSError, KeyError, ValueError):
        return None
