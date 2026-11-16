"""Inputs and result files of the combined raise-and-job union. Standard library only.

The Modal client's own Python imports this module, so it uses no numpy or pandas.

Inputs come from three places, each named in the manifest by a repo-relative path
and a SHA-256, never by a local absolute path:

- ``worktree``: the raise experiment's metadata records, tracked in this checkout
  (results/earnings_changes/parts/), and the raise union's committed JSON;
- ``raise_rows``: the raise experiment's per-person rows (git-ignored), checked
  against the SHA-256 the committed raise union recorded for each file;
- ``job_entry``: the national job-entry results (git-ignored records, rows and
  plans under results/job_entry/), from any checkout that holds them.

Job coverage comes from the job-entry records and plans, never from wages.json. A
wage scope (``resolved``, or a later ``states-MD-NY``) counts only when every part
has its plan and a validated record for every planned rank. A jurisdiction counts
as covered only when its tested rows equal the plans' count of its candidates in
all four parts; every other jurisdiction with candidates is deferred and its rows,
if any, are left out. A complete later scope is picked up with no code change.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.job_entry_outputs import (
    BASE as JOB_BASE,
    PARTS,
    SEED,
    YEAR,
    install_bytes,
    part_stem,
    sha256,
    validate_pair,
)

RAISE_KEYS = ("raise_1000", "raise_2000", "raise_5000")
RAISE_UNION_JSON = "results/expanded_raise_union_2017.json"
OUT_BASE = "results/combined_union"
FINAL_JSON = "results/expanded_combined_union_2017.json"
STATUS_PARTIAL = "preliminary_partial_jurisdictions"
STATUS_ALL = "all_jurisdictions_unreviewed"
# The code each part result records and the container checks against its own copy.
CODE_FILES = (
    "scripts/expanded_combined_union.py",
    "scripts/combined_union_inputs.py",
    "scripts/modal_combined_union.py",
    "scripts/expanded_raise_union.py",
    "scripts/expanded_historical.py",
    "scripts/driver_intervals.py",
    "scripts/job_entry_outputs.py",
    "scripts/modal-requirements.txt",
)


class IncompleteScope(ValueError):
    """A wage scope that lacks a plan or a validated rank record in some part."""


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


def uncommitted(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *CODE_FILES, "cliffs2017"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def code_record(root: Path) -> dict:
    """The launching commit and the hashes of the code it holds; refuses uncommitted code."""
    dirty = uncommitted(root)
    if dirty:
        raise RuntimeError(f"commit these first, so the recorded commit holds the code:\n{dirty}")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return {"commit": commit, "sha256": code_hashes(root)}


def verify_code(code: dict, root: Path) -> None:
    """Stop unless this copy of the code is the one the launching commit holds."""
    ours = code_hashes(root)
    if ours != code["sha256"]:
        changed = sorted(k for k in set(ours) | set(code["sha256"]) if ours.get(k) != code["sha256"].get(k))
        raise RuntimeError(f"this copy of the code differs from commit {code['commit'][:7]}: {changed}")


def raise_metadata_rel(part: int, key: str) -> str:
    return f"results/earnings_changes/parts/changes_{YEAR}_p{PARTS}_{part}_s{SEED}/{key}.json"


def raise_inputs(root: Path, rows_root: Path, part: int, recorded: list[dict]) -> tuple[list[dict], dict]:
    """The raise metadata and rows of one part, each checked against the raise union's record."""
    entries, files = [], {}
    for key in RAISE_KEYS:
        meta_rel = raise_metadata_rel(part, key)
        meta = (Path(root) / meta_rel).read_bytes()
        rows_rel = json.loads(meta)["per_person_file"]
        rows = (Path(rows_root) / rows_rel).read_bytes()
        match = [r for r in recorded if r["metadata_file"].endswith("/" + meta_rel)]
        if len(match) != 1:
            raise ValueError(f"the raise union records {len(match)} inputs for {meta_rel}")
        if not match[0]["rows_file"].endswith("/" + rows_rel):
            raise ValueError(f"the raise union read other rows for {meta_rel}")
        if sha256(meta) != match[0]["metadata_sha256"] or sha256(rows) != match[0]["rows_sha256"]:
            raise ValueError(f"{meta_rel} or its rows differ from the files the raise union read")
        entries.append({"kind": "raise_metadata", "source": "worktree", "part": part, "key": key,
                        "name": meta_rel, "sha256": sha256(meta)})
        entries.append({"kind": "raise_rows", "source": "raise_rows", "part": part, "key": key,
                        "name": rows_rel, "sha256": sha256(rows)})
        files[meta_rel], files[rows_rel] = meta, rows
    return entries, files


def job_plan_rel(part: int, tag: str) -> str:
    return f"{JOB_BASE}/plan/{part_stem(part)}_{tag}.json"


def job_record_rel(part: int, tag: str, rank: int) -> str:
    return f"{JOB_BASE}/parts/{part_stem(part)}/{tag}/rank_{rank:02d}.json"


def job_scopes(job_root: Path) -> list[str]:
    """Every wage scope a national part directory holds (smoke stems are other directories)."""
    tags = set()
    for part in range(PARTS):
        folder = Path(job_root) / JOB_BASE / "parts" / part_stem(part)
        if folder.is_dir():
            tags.update(d.name for d in folder.iterdir() if d.is_dir())
    return sorted(tags)


def _by_state_total(plan: dict) -> dict:
    total = dict(plan["sample_candidates_in_scope_by_state"])
    for state, n in plan["sample_candidates_outside_scope_by_state"].items():
        total[state] = total.get(state, 0) + n
    return total


def complete_scope(job_root: Path, tag: str) -> dict:
    """A scope's validated pairs, per-state tested counts and rates, or IncompleteScope."""
    root = Path(job_root)
    parts, rates, wages = {}, None, set()
    for part in range(PARTS):
        plan_path = root / job_plan_rel(part, tag)
        if not plan_path.exists():
            raise IncompleteScope(f"{tag}: part {part} has no plan")
        plan_record = json.loads(plan_path.read_bytes())
        if plan_record.get("scope") != tag or plan_record.get("part") != part:
            raise ValueError(f"{plan_path.name} describes another scope or part")
        plan = plan_record["plan"]
        wages.add(plan_record["provenance"]["wages_json_sha256"])
        planned = {int(k): n for k, n in plan["sample_candidates_by_rank"].items() if n}
        folder = root / JOB_BASE / "parts" / part_stem(part) / tag
        present = {int(p.stem.split("_")[1]) for p in folder.glob("rank_*.json")} if folder.is_dir() else set()
        if present - set(planned):
            raise ValueError(f"{tag} part {part}: records for unplanned ranks {sorted(present - set(planned))}")
        entries, files, tested_by_state = [], {}, {}
        for rank, n in sorted(planned.items()):
            json_rel = job_record_rel(part, tag, rank)
            if rank not in present:
                raise IncompleteScope(f"{tag}: part {part} lacks rank {rank}")
            json_bytes = (root / json_rel).read_bytes()
            csv_rel = json.loads(json_bytes)["rows"]["file"]
            csv_path = root / csv_rel
            if not csv_path.exists():
                raise IncompleteScope(f"{tag}: part {part} rank {rank} lacks its rows")
            csv_bytes = csv_path.read_bytes()
            record = validate_pair(json_bytes, csv_bytes, dict(part=part, rank=rank, scope=tag))
            if record.get("smoke") is not False:
                raise ValueError(f"{json_rel} is not a national record")
            if record["counts"]["sample_candidates_tested"] != n:
                raise ValueError(f"{json_rel} tested {record['counts']['sample_candidates_tested']}, plan {n}")
            if record["provenance"]["code"]["uncommitted"] != "":
                raise ValueError(f"{json_rel} ran uncommitted code")
            wages.add(record["provenance"]["wages_json_sha256"])
            used = record["provenance"]["rates_used"]
            if rates is not None and used != rates:
                raise ValueError(f"{tag}: records ran different wage rates")
            rates = used
            for state, k in record["counts"]["sample_candidates_tested_by_state"].items():
                tested_by_state[state] = tested_by_state.get(state, 0) + k
            entries.append({"kind": "job_record", "source": "job_entry", "part": part, "scope": tag,
                            "rank": rank, "name": json_rel, "sha256": sha256(json_bytes)})
            entries.append({"kind": "job_rows", "source": "job_entry", "part": part, "scope": tag,
                            "rank": rank, "name": csv_rel, "sha256": sha256(csv_bytes)})
            files[json_rel], files[csv_rel] = json_bytes, csv_bytes
        if tested_by_state != plan["sample_candidates_in_scope_by_state"]:
            raise ValueError(f"{tag} part {part}: tested states differ from the plan")
        parts[part] = {"entries": entries, "files": files, "tested_by_state": tested_by_state,
                       "universe_by_state": _by_state_total(plan)}
    if len(wages) != 1:
        raise ValueError(f"{tag}: plans and records read different wages.json files")
    return {"parts": parts, "rates": rates, "wages_json_sha256": wages.pop()}


def job_coverage(job_root: Path, scopes: list[str] | None = None) -> tuple[dict, dict]:
    """Coverage and, per part, the included job entries and file bytes.

    ``scopes`` limits the union to the named wage scopes (every complete one by default);
    a scope left out is listed as not selected and its jurisdictions stay deferred.
    """
    included, excluded = {}, {}
    universe: dict[int, dict] = {}
    for tag in job_scopes(job_root):
        for part in range(PARTS):
            plan_path = Path(job_root) / job_plan_rel(part, tag)
            if plan_path.exists():
                total = _by_state_total(json.loads(plan_path.read_bytes())["plan"])
                if universe.setdefault(part, total) != total:
                    raise ValueError(f"part {part}: plans disagree on the candidates by state")
        if scopes is not None and tag not in scopes:
            excluded[tag] = f"{tag}: not selected for this run"
            continue
        try:
            included[tag] = complete_scope(job_root, tag)
        except IncompleteScope as error:
            excluded[tag] = str(error)
    if sorted(universe) != list(range(PARTS)):
        raise ValueError("job-entry plans do not cover every part")
    covered, rates = {}, {}
    for tag, scope in included.items():
        for state, rate in scope["rates"].items():
            if rates.setdefault(state, rate) != rate:
                raise ValueError(f"wage scopes disagree on {state}'s rate")
        for part, info in scope["parts"].items():
            for state, n in info["tested_by_state"].items():
                if covered.setdefault(state, tag) != tag:
                    raise ValueError(f"{state} is tested by two scopes")
                if n != universe[part].get(state, 0):
                    raise ValueError(f"{tag} part {part}: {state} tested {n} of {universe[part].get(state, 0)}")
    states = sorted({s for part in universe.values() for s, n in part.items() if n})
    deferred = {s: sum(universe[p].get(s, 0) for p in universe) for s in states if s not in covered}
    # A covered state must be complete in every part, including parts where its scope's plan
    # found no candidates for it.
    for state, scope_tag in covered.items():
        for part in range(PARTS):
            tested = included[scope_tag]["parts"][part]["tested_by_state"].get(state, 0)
            if tested != universe[part].get(state, 0):
                raise ValueError(f"{state} part {part}: {tested} tested of {universe[part].get(state, 0)}")
    coverage = {
        "scopes_selected": None if scopes is None else sorted(scopes),
        "scopes_included": sorted(included),
        "scopes_excluded": excluded,
        "jurisdictions_covered": sorted(covered),
        "jurisdictions_deferred": deferred,
        "sample_candidates_tested": sum(n for s in included.values() for i in s["parts"].values()
                                        for n in i["tested_by_state"].values()),
        "sample_candidates_deferred": sum(deferred.values()),
        "wages_json_sha256_by_scope": {t: s["wages_json_sha256"] for t, s in included.items()},
        "rates_used": dict(sorted(rates.items())),
        "expected_rows_by_part": {
            str(part): {s: n for s, n in sorted(universe[part].items()) if s in covered and n}
            for part in range(PARTS)
        },
        "status": STATUS_PARTIAL if deferred else STATUS_ALL,
    }
    by_part = {}
    for part in range(PARTS):
        entries, files = [], {}
        for tag in sorted(included):
            info = included[tag]["parts"][part]
            entries += info["entries"]
            files.update(info["files"])
        by_part[part] = {"entries": entries, "files": files}
    return coverage, by_part


def manifest_digest(manifest: dict) -> str:
    keyed = {k: manifest[k] for k in ("year", "parts", "seed", "code", "inputs", "coverage")}
    return sha256(json.dumps(keyed, sort_keys=True).encode())


def build_manifest(root: Path, job_root: Path, rows_root: Path, code: dict,
                   scopes: list[str] | None = None) -> tuple[dict, dict]:
    """The manifest of every input, and each part's file bytes keyed by manifest name."""
    raise_json = (Path(root) / RAISE_UNION_JSON).read_bytes()
    recorded = json.loads(raise_json)["inputs"]
    coverage, job = job_coverage(job_root, scopes)
    inputs = [{"kind": "raise_union_json", "source": "worktree", "part": None,
               "name": RAISE_UNION_JSON, "sha256": sha256(raise_json)}]
    files = {}
    for part in range(PARTS):
        entries, raise_files = raise_inputs(root, rows_root, part, recorded)
        inputs += entries + job[part]["entries"]
        files[part] = {RAISE_UNION_JSON: raise_json, **raise_files, **job[part]["files"]}
    manifest = {"year": YEAR, "parts": PARTS, "seed": SEED, "code": code, "inputs": inputs,
                "coverage": coverage}
    manifest["digest"] = manifest_digest(manifest)
    return manifest, files


def check_files(manifest: dict, part: int, files: dict) -> None:
    """Stop unless ``files`` holds exactly this part's manifest inputs, byte for byte."""
    wanted = {e["name"]: e["sha256"] for e in manifest["inputs"] if e["part"] in (None, part)}
    if set(files) != set(wanted):
        raise ValueError(f"part {part}: shipped files differ from the manifest")
    for name, data in files.items():
        if sha256(data) != wanted[name]:
            raise ValueError(f"part {part}: {name} differs from its manifest hash")
    if manifest_digest(manifest) != manifest["digest"]:
        raise ValueError("the manifest does not match its digest")


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


def launches_rel(digest: str) -> str:
    return f"{OUT_BASE}/launches/{tag(digest)}.jsonl"


def validate_part_pair(json_bytes: bytes, npz_bytes: bytes, expect: dict | None = None) -> dict:
    """The part record, if it is complete, every invariant passed and it names exactly these totals."""
    record = json.loads(json_bytes)
    if record.get("status") != "complete":
        raise ValueError(f"part record status is {record.get('status')!r}")
    checks = record.get("invariants") or {}
    if not checks or not all(c.get("pass") is True for c in checks.values()):
        raise ValueError("part record lacks passing invariants")
    if sha256(npz_bytes) != record["per_source"]["sha256"]:
        raise ValueError("per-source totals differ from the record's SHA-256")
    for key, value in (expect or {}).items():
        if record.get(key) != value:
            raise ValueError(f"part record {key} is {record.get(key)!r}, not {value!r}")
    return record


def install_part_pair(root: Path, json_rel: str, json_bytes: bytes, npz_bytes: bytes,
                      expect: dict | None = None) -> str:
    """Install a validated pair, totals first and record last, never overwriting."""
    record = validate_part_pair(json_bytes, npz_bytes, expect)
    npz_state = install_bytes(root, record["per_source"]["file"], npz_bytes)
    if npz_state == "differs":
        return f"conflict: {record['per_source']['file']} differs locally; {json_rel} not installed"
    state = install_bytes(root, json_rel, json_bytes)
    if state == "differs":
        return f"kept the local {json_rel}; another run's record differs"
    return f"{state} {json_rel}"


def local_part(root: Path, digest: str, part: int) -> dict | None:
    """The installed part record when it and its totals validate, else None."""
    path = Path(root) / part_json_rel(digest, part)
    if not path.exists():
        return None
    data = path.read_bytes()
    try:
        npz = (Path(root) / json.loads(data)["per_source"]["file"]).read_bytes()
        return validate_part_pair(data, npz, dict(part=part, digest=digest))
    except (OSError, KeyError, ValueError):
        return None
