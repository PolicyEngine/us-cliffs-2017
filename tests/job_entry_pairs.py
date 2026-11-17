"""Synthetic national job-entry results that pass strict validation, for tests.

A pair is built the way the runner builds one (expanded_job_entry_national.write_pair)
with every named identity check, the full row schema, real state codes and the
resolved wage table's rates, and a resume fingerprint. Tests then break one thing.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd

from scripts.expanded_job_entry_national import write_pair
from scripts.job_entry_outputs import (
    HOURS_PER_YEAR,
    IDENTITY_RULES,
    JOB_ENTRY_MODULES,
    install_bytes,
    install_pair,
    part_stem,
    plan_json,
    request_identity,
    result_csv,
    result_json,
    resume_expectation,
    scope_tag,
    wage_table_fingerprint,
)
from scripts.job_entry_wages import national_wage_table

TABLE = national_wage_table()
WAGE_TABLE = wage_table_fingerprint(TABLE)
RATES = TABLE["rates"]
COMPONENTS = ["d_household_market_income", "d_household_tax_before_refundable_credits"]
IDENTITY_VALUES = {
    "zero_change_max_household_change": 0.0,
    "untouched_household_max_change": 0.0,
    "entrant_earnings_max_error_vs_rate_x_2080": 0.0008,
    "non_entrant_earnings_max_change": 0.0,
    "entrant_hours_40_weeks_52": True,
    "wic_draw_months_changed": [],
    "parts_sum_to_net_income_max_error": 0.05,
    "ptc_once_measure_vs_decomposition_max_error": 0.01,
}
assert set(IDENTITY_VALUES) == set(IDENTITY_RULES)


def environment(**changes) -> dict:
    """A container environment as expanded_job_entry_national.environment() reports it."""
    env = {
        "code": {"files": {rel: f"sha-{rel}" for rel in JOB_ENTRY_MODULES}, "cliffs2017": "cliffs-digest"},
        "dataset": {"source": "repo/file.h5@rev", "year": 2017, "parts": 4, "seed": 0,
                    "medicaid_totals_sha256": "medicaid", "file_sha256": "h5"},
        "packages": {"requirements_sha256": "req", "versions": {"policyengine-us": "2.116.0"}, "python": "3.13.5"},
    }
    for path, value in changes.items():
        section, key = path.split(".", 1)
        env[section][key] = value
    return env


def expectation(part=0, rank=1, scope="resolved", planned=2, env=None, wage_table=None) -> dict:
    return resume_expectation(env or environment(), wage_table or WAGE_TABLE,
                              request_identity(part, rank, scope), planned)


def people(n=2, start=0, states=("CO", "WA", "MD", "NY", "ME", "DC")) -> list[dict]:
    """n tested adults in distinct households, person index/id from ``start``."""
    return [{"person_index": start + i, "person_id": 1000 + start + i, "household_id": 500 + start + i,
             "state_code": states[i % len(states)]} for i in range(n)]


def make_pair(part=0, rank=1, scope="resolved", tested=None, run_id="run1", smoke=False, expected=None,
              mutate_rows=None, mutate_record=None):
    """(json_bytes, csv_bytes, json_rel) for one rank result that passes validate_pair.

    ``mutate_rows(frame)`` and ``mutate_record(record)`` change the pair before it is
    serialized; write_pair's own validation is then skipped by building the bytes here.
    """
    tested = people() if tested is None else tested
    rows = pd.DataFrame(tested)
    rows["rank"] = rank
    rows["hourly_wage"] = [RATES[s] for s in rows.state_code]
    rows["gross_pay"] = [RATES[s] * HOURS_PER_YEAR for s in rows.state_code]
    rows["d_net_single_ptc"] = 0.4 * rows.gross_pay
    rows["d_net_without_health"] = 0.6 * rows.gross_pay
    rows["d_net"] = 0.3 * rows.gross_pay
    rows["d_household_market_income"] = rows.gross_pay
    rows["d_household_tax_before_refundable_credits"] = -0.1 * rows.gross_pay
    by_state = rows.state_code.value_counts().to_dict()
    record = {
        "status": "complete",
        "rank": rank,
        "scope": scope_tag(scope),
        "counts": {"sample_candidates_tested": len(rows), "sample_households_touched": rows.household_id.nunique(),
                   "sample_candidates_tested_by_state": {k: int(v) for k, v in sorted(by_state.items())}},
        "identities": {k: {"value": v, "pass": True} for k, v in IDENTITY_VALUES.items()},
        "component_columns": list(COMPONENTS),
    }
    if smoke:
        record["identities"]["fresh_simulation_max_difference"] = {"value": 0.0, "pass": True}
    expected = expected or expectation(part, rank, scope, len(rows))
    provenance = {"rates_used": dict(RATES), "wages_json_sha256": TABLE["wages_json_sha256"],
                  "code": {"commit": "c0ffee", "uncommitted": "", "sha256": dict(expected["code"]["files"])},
                  "wage_table": expected["wage_table"], "resume": copy.deepcopy(expected)}
    stem = part_stem(part)
    csv_rel = result_csv(stem, scope, rank, run_id)
    extra = {"part": part, "smoke": smoke, "run_id": run_id, "provenance": provenance}
    if mutate_rows is None and mutate_record is None:
        json_bytes, csv_bytes = write_pair(rows, record, csv_rel, extra)
    else:
        from scripts.job_entry_outputs import csv_gzip, sha256

        if mutate_rows:
            changed = mutate_rows(rows)
            rows = rows if changed is None else changed
        csv_bytes = csv_gzip(rows.to_csv(index=False, na_rep="nan"))
        record = dict(record, **extra)
        record["rows"] = {"file": csv_rel, "sha256": sha256(csv_bytes), "count": len(rows),
                          "columns": list(rows.columns)}
        if mutate_record:
            mutate_record(record)
        json_bytes = json.dumps(record).encode()
    return json_bytes, csv_bytes, result_json(stem, scope, rank)


def write_plan(root: Path, part: int, scope: str, by_rank: dict, in_scope: dict, outside: dict | None = None):
    """A plan file as plan_part writes it."""
    plan = {"part": part, "scope": scope_tag(scope),
            "plan": {"sample_candidates_by_rank": {str(k): n for k, n in by_rank.items()},
                     "sample_candidates_in_scope_by_state": in_scope,
                     "sample_candidates_outside_scope_by_state": outside or {}},
            "provenance": {"wages_json_sha256": TABLE["wages_json_sha256"]}}
    install_bytes(root, plan_json(part, scope), (json.dumps(plan) + "\n").encode())
    return plan


def install(root: Path, pair) -> str:
    json_bytes, csv_bytes, json_rel = pair
    return install_pair(root, json_rel, json_bytes, csv_bytes)
