"""Inputs, paths and safe installation for the coverage split. Standard library only.

The Modal client's own Python imports this module, so it uses no numpy or pandas.

The frozen inputs are exactly those of the 51-jurisdiction combined union, run
``1c0cc9ddcfd7d876``: its manifest names every raise and job row file with a
SHA-256, and this module reads each from the checkout that holds it and checks
the hash. The union's four part records give the strict totals the split must
reproduce.

A scenario result is one test of one household part: the job test at one
candidate rank (both wage scopes, every jurisdiction), or one raise at one
adult rank. It is a JSON record and two gzipped CSVs: the tested adults (the
rerun's household change beside the saved one) and the members of every
household the scenario leaves strict or whose health value moves (coverage and
value before and after). The record names both CSVs, which carry a unique run
id, hashes them, and records the reproduction check. Only a pair that validates
is published to the volume or installed locally, never over an existing file
(scripts/job_entry_outputs.install_bytes).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.job_entry_outputs import install_bytes, sha256

YEAR = 2017
PARTS = 4
SEED = 0
BASE = "results/coverage_split"
FINAL_JSON = "results/coverage_split_2017.json"
UNION_TAG = "1c0cc9ddcfd7d876"
UNION_MANIFEST = f"results/combined_union/manifests/{UNION_TAG}.json"
RAISE_KEYS = {"raise_1000": 1000.0, "raise_2000": 2000.0, "raise_5000": 5000.0}
RAISE_RANKS = (1, 2)
SETS = {
    "job": ("job",),
    "raise_union": tuple(RAISE_KEYS),
    "combined": (*RAISE_KEYS, "job"),
    "combined_1000": ("raise_1000", "job"),
}
REPRODUCTION_TOLERANCE = 0.01
# The code each result records; a launch refuses uncommitted copies and a container
# stops unless its copy hashes the same.
CODE_FILES = (
    "scripts/coverage_split.py",
    "scripts/coverage_split_outputs.py",
    "scripts/modal_coverage_split.py",
    "scripts/expanded_job_entry.py",
    "scripts/expanded_job_entry_national.py",
    "scripts/expanded_historical.py",
    "scripts/expanded_raise_union.py",
    "scripts/expanded_combined_union.py",
    "scripts/combined_union_inputs.py",
    "scripts/job_entry_outputs.py",
    "scripts/job_entry_wages.py",
    "scripts/modal-requirements.txt",
    "results/medicaid/totals_2017_p4_s0.json",
)


# ---------------------------------------------------------------------------
# Code provenance


def cliffs2017_digest(root: Path) -> str:
    """cliffs2017.run.code_version()'s hash of cliffs2017/, without importing it."""
    digest = hashlib.sha256()
    for path in sorted((Path(root) / "cliffs2017").rglob("*")):
        if path.is_file() and path.suffix in (".py", ".csv"):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def code_hashes(root: Path) -> dict:
    hashes = {rel: sha256((Path(root) / rel).read_bytes()) for rel in CODE_FILES}
    hashes["cliffs2017/"] = cliffs2017_digest(root)
    return hashes


def code_record(root: Path) -> dict:
    """The launching commit and its code hashes; refuses uncommitted code."""
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *CODE_FILES, "cliffs2017"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
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


# ---------------------------------------------------------------------------
# Frozen inputs


def union_manifest(union_root: Path) -> dict:
    manifest = json.loads((Path(union_root) / UNION_MANIFEST).read_bytes())
    if not manifest["digest"].startswith(UNION_TAG):
        raise ValueError("the union manifest is not run 1c0cc9dd")
    keyed = {k: manifest[k] for k in ("year", "parts", "seed", "code", "inputs", "coverage")}
    if sha256(json.dumps(keyed, sort_keys=True).encode()) != manifest["digest"]:
        raise ValueError("the union manifest does not match its digest")
    return manifest


def union_part_record(union_root: Path, part: int) -> dict:
    path = Path(union_root) / f"results/combined_union/parts/{UNION_TAG}/part_{part}.json"
    record = json.loads(path.read_bytes())
    if record.get("part") != part or not record.get("digest", "").startswith(UNION_TAG):
        raise ValueError(f"{path} is not part {part} of run {UNION_TAG}")
    return record


def _read_checked(root: Path, name: str, expected: str) -> bytes:
    data = (Path(root) / name).read_bytes()
    if sha256(data) != expected:
        raise ValueError(f"{name} differs from the union manifest's SHA-256")
    return data


def part_inputs(manifest: dict, part: int, job_root: Path, raise_rows_root: Path) -> dict:
    """The raise rows and job records/rows of one part, each checked against the manifest.

    Returns {"raise": {key: bytes}, "job": {rank: [(record_bytes, rows_bytes), ...]},
    "names": {name: sha256}}.
    """
    out = {"raise": {}, "job": {}, "names": {}}
    entries = [e for e in manifest["inputs"] if e["part"] == part]
    by_name = {e["name"]: e for e in entries}
    for e in entries:
        if e["kind"] == "raise_rows":
            out["raise"][e["key"]] = _read_checked(raise_rows_root, e["name"], e["sha256"])
            out["names"][e["name"]] = e["sha256"]
        elif e["kind"] == "job_record":
            record_bytes = _read_checked(job_root, e["name"], e["sha256"])
            rows_name = json.loads(record_bytes)["rows"]["file"]
            rows_entry = by_name[rows_name]
            rows_bytes = _read_checked(job_root, rows_name, rows_entry["sha256"])
            out["job"].setdefault(e["rank"], []).append((record_bytes, rows_bytes))
            out["names"][e["name"]] = e["sha256"]
            out["names"][rows_name] = rows_entry["sha256"]
    if sorted(out["raise"]) != sorted(RAISE_KEYS):
        raise ValueError(f"part {part}: the manifest lacks a raise")
    return out


def job_rates(manifest: dict, job_root: Path) -> dict:
    """Every jurisdiction's hourly rate, merged across the job records; stops on a disagreement."""
    rates = {}
    for e in manifest["inputs"]:
        if e["kind"] != "job_record":
            continue
        record = json.loads(_read_checked(job_root, e["name"], e["sha256"]))
        for state in record["counts"]["sample_candidates_tested_by_state"]:
            rate = record["provenance"]["rates_used"][state]
            if rates.setdefault(state, rate) != rate:
                raise ValueError(f"job records disagree on {state}'s rate")
    return dict(sorted(rates.items()))


# ---------------------------------------------------------------------------
# Result paths


def stem(part: int, smoke: int = 0, smoke_seed: int = 17) -> str:
    base = f"p{PARTS}_{part}_s{SEED}"
    return f"smoke_{base}_h{smoke}_seed{smoke_seed}" if smoke else base


def scenario_label(test: str, rank: int) -> str:
    """``job_rank_01`` or ``raise_1000_rank_02``."""
    if test != "job" and test not in RAISE_KEYS:
        raise ValueError(f"unknown test {test!r}")
    return f"{test}_rank_{rank:02d}"


def scenario_json(part: int, test: str, rank: int, smoke: int = 0) -> str:
    return f"{BASE}/scenarios/{stem(part, smoke)}/{scenario_label(test, rank)}.json"


def scenario_rows(part: int, test: str, rank: int, run_id: str, kind: str, smoke: int = 0) -> str:
    if not run_id.isalnum() or kind not in ("tested", "persons"):
        raise ValueError("bad run id or row kind")
    return f"{BASE}/rows/{stem(part, smoke)}_{scenario_label(test, rank)}_{run_id}_{kind}.csv.gz"


def aggregate_json(part: int, tag: str) -> str:
    return f"{BASE}/aggregate/{tag}/part_{part}.json"


def classified_json(part: int) -> str:
    return f"{BASE}/classified/part_{part}.json"


def validate_scenario(json_bytes: bytes, tested_bytes: bytes, persons_bytes: bytes,
                      expect: dict | None = None) -> dict:
    """The record, if it is complete, reproduced the saved rows, and names exactly these files."""
    record = json.loads(json_bytes)
    if record.get("status") != "complete":
        raise ValueError(f"record status is {record.get('status')!r}")
    repro = record.get("reproduction") or {}
    if repro.get("pass") is not True:
        raise ValueError("record lacks a passing reproduction check")
    if repro.get("max_abs_difference_d_with", 1.0) > REPRODUCTION_TOLERANCE:
        raise ValueError("record's reproduction exceeds the tolerance")
    for kind, data in (("tested", tested_bytes), ("persons", persons_bytes)):
        if sha256(data) != record["rows"][kind]["sha256"]:
            raise ValueError(f"{kind} rows differ from the record's SHA-256")
    for key, value in (expect or {}).items():
        if record.get(key) != value:
            raise ValueError(f"record {key} is {record.get(key)!r}, not {value!r}")
    return record


def install_scenario(root: Path, json_rel: str, json_bytes: bytes, tested_bytes: bytes,
                     persons_bytes: bytes, expect: dict | None = None) -> str:
    record = validate_scenario(json_bytes, tested_bytes, persons_bytes, expect)
    for kind, data in (("tested", tested_bytes), ("persons", persons_bytes)):
        state = install_bytes(root, record["rows"][kind]["file"], data)
        if state == "differs":
            return f"conflict: {record['rows'][kind]['file']} differs locally; {json_rel} not installed"
    state = install_bytes(root, json_rel, json_bytes)
    if state == "differs":
        return f"kept the local {json_rel}; another run's record differs"
    return f"{state} {json_rel}"


def local_scenario(root: Path, json_rel: str) -> dict | None:
    path = Path(root) / json_rel
    if not path.exists():
        return None
    data = path.read_bytes()
    try:
        record = json.loads(data)
        return validate_scenario(data, (Path(root) / record["rows"]["tested"]["file"]).read_bytes(),
                                 (Path(root) / record["rows"]["persons"]["file"]).read_bytes())
    except (OSError, KeyError, ValueError):
        return None
