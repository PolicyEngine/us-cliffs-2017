"""Runner guards for the national job-entry test: stale resumes, failure exits, strict pairs.

Each guard has a test that fails when the guard is removed (EXPANDED_JOB_ENTRY.md,
"Runner guards"). Pairs come from tests/job_entry_pairs.py, which builds them the
way the runner does and passes strict validation unless a test breaks one thing.
"""

import base64
import copy
import json
import math

import pytest
from job_entry_pairs import (
    RATES,
    TABLE,
    WAGE_TABLE,
    environment,
    expectation,
    install,
    make_pair,
    people,
    write_plan,
)

from scripts.job_entry_model_fixture import (
    employee_payroll_tax,
    federal_income_tax_before_credits,
    unreviewed_inputs,
)
from scripts.job_entry_outputs import (
    StaleResult,
    existing_plan,
    finish_launch,
    install_pair,
    plan_expectation,
    ranks_to_run,
    read_local,
    require_success,
    reusable_pair,
    settle,
    validate_pair,
    validate_results,
    wage_table_fingerprint,
)
from scripts.job_entry_wages import load_wages, national_wage_table


def reader(files: dict):
    return lambda rel: files.get(rel)


# ---------------------------------------------------------------------------
# [P1] Stale resume: both skips reuse a result only under the launch's fingerprint.


def _changed_wage_table(rate=None, path_date=None):
    data = copy.deepcopy(load_wages()[0])
    if rate is not None:
        data["states"]["WA"]["amount"] = data["states"]["WA"]["reference_hourly"] = rate
    if path_date is not None:
        data["states"]["DC"]["variants"][0]["ends"] = path_date[0]
        data["states"]["DC"]["variants"][1]["starts"] = path_date[1]
    return wage_table_fingerprint(national_wage_table(data, "edited"))


MISMATCHES = {
    "code module": lambda: expectation(env=environment(**{"code.files": {"scripts/job_entry_outputs.py": "other"}})),
    "cliffs2017 code": lambda: expectation(env=environment(**{"code.cliffs2017": "other"})),
    "dataset file": lambda: expectation(env=environment(**{"dataset.file_sha256": "other"})),
    "medicaid totals": lambda: expectation(env=environment(**{"dataset.medicaid_totals_sha256": "other"})),
    "dataset revision": lambda: expectation(env=environment(**{"dataset.source": "repo/file.h5@other"})),
    "requirements pins": lambda: expectation(env=environment(**{"packages.requirements_sha256": "other"})),
    "installed version": lambda: expectation(env=environment(**{"packages.versions": {"policyengine-us": "9"}})),
    "python": lambda: expectation(env=environment(**{"packages.python": "3.12.0"})),
    "requested part": lambda: dict(expectation(), request=expectation(part=1)["request"]),
    "requested rank": lambda: dict(expectation(), request=expectation(rank=2)["request"]),
    "requested scope": lambda: dict(expectation(), request=expectation(scope="states:MD,NY")["request"]),
    "planned count": lambda: expectation(planned=3),
    "wage rate": lambda: expectation(wage_table=_changed_wage_table(rate=11.5)),
    "wage path": lambda: expectation(wage_table=_changed_wage_table(path_date=("2017-05-31", "2017-06-01"))),
}


def test_a_matching_fingerprint_is_reused_from_the_volume_and_locally(tmp_path):
    json_bytes, csv_bytes, json_rel = pair = make_pair()
    record = json.loads(json_bytes)
    files = {json_rel: json_bytes, record["rows"]["file"]: csv_bytes}
    assert reusable_pair(reader(files), json_rel, expectation(), "volume") == (json_bytes, csv_bytes)
    assert reusable_pair(reader(files), "results/job_entry/absent.json", expectation(), "volume") is None
    assert install(tmp_path, pair).startswith("wrote")
    plans = {0: write_plan(tmp_path, 0, "resolved", {1: 2, 2: 1}, {"CO": 2, "WA": 1})}
    jobs = ranks_to_run(plans, "resolved", environment(), WAGE_TABLE, read_local(tmp_path), log=lambda m: None)
    assert [(part, rank) for part, rank, _ in jobs] == [(0, 2)]
    assert jobs[0][2] == expectation(rank=2, planned=1)


@pytest.mark.parametrize("field", sorted(MISMATCHES))
def test_a_mismatched_fingerprint_stops_both_skips(tmp_path, field):
    json_bytes, csv_bytes, json_rel = pair = make_pair()
    files = {json_rel: json_bytes, json.loads(json_bytes)["rows"]["file"]: csv_bytes}
    expected = MISMATCHES[field]()
    with pytest.raises(StaleResult, match="written under other inputs|invalid pair"):
        reusable_pair(reader(files), json_rel, expected, "volume")
    install(tmp_path, pair)
    request = expected["request"]
    if (request["part"], request["rank"], request["scope"]) != (0, 1, "resolved"):
        return  # the local skip looks up the request's own path; covered by the volume case above
    plans = {0: write_plan(tmp_path, 0, "resolved", {1: expected["planned_candidates"]}, {"CO": 1, "WA": 1})}
    env = {k: expected[k] for k in ("code", "dataset", "packages")}
    with pytest.raises(StaleResult, match="written under other inputs"):
        ranks_to_run(plans, "resolved", env, expected["wage_table"], read_local(tmp_path), log=lambda m: None)


def test_a_record_without_a_fingerprint_or_rows_is_never_resumed():
    json_bytes, csv_bytes, json_rel = make_pair()
    old = json.loads(json_bytes)
    del old["provenance"]["resume"]
    rows_rel = old["rows"]["file"]
    with pytest.raises(StaleResult, match="no resume fingerprint"):
        reusable_pair(reader({json_rel: json.dumps(old).encode(), rows_rel: csv_bytes}), json_rel, expectation(), "v")
    with pytest.raises(StaleResult, match="rows .* are missing"):
        reusable_pair(reader({json_rel: json_bytes}), json_rel, expectation(), "v")
    with pytest.raises(StaleResult, match="unreadable"):
        reusable_pair(reader({json_rel: b"{not json"}), json_rel, expectation(), "v")


def test_a_plan_is_reused_only_under_the_same_fingerprint():
    expected = plan_expectation(environment(), WAGE_TABLE, 0, "resolved")
    plan = {"part": 0, "scope": "resolved", "plan": {}, "provenance": {"resume": expected}}
    assert existing_plan(json.dumps(plan).encode(), expected, "p") == plan
    other = plan_expectation(environment(), _changed_wage_table(rate=11.5), 0, "resolved")
    with pytest.raises(StaleResult, match="planned under other inputs"):
        existing_plan(json.dumps(plan).encode(), other, "p")


def test_the_wage_fingerprint_follows_resolved_rates_not_wages_json_bytes():
    data = copy.deepcopy(load_wages()[0])
    data["metadata"]["date_convention"] = "edited"
    data["metadata"]["updates"].append("a note")
    data["states"]["ME"]["notes"] = ["a different note"]
    assert wage_table_fingerprint(national_wage_table(data, "other-bytes")) == WAGE_TABLE
    assert _changed_wage_table(rate=11.5)["sha256"] != WAGE_TABLE["sha256"]
    assert _changed_wage_table(path_date=("2017-05-31", "2017-06-01"))["sha256"] != WAGE_TABLE["sha256"]
    assert WAGE_TABLE["jurisdictions"] == 51 and WAGE_TABLE["unresolved"] == []


def test_an_expectation_survives_a_json_round_trip():
    expected = expectation()
    assert json.loads(json.dumps(expected)) == expected


# ---------------------------------------------------------------------------
# [P2] Failure exits: every failed rank and install conflict is named in a nonzero exit.


def _packet(pair, part=0, rank=1, status="written"):
    json_bytes, csv_bytes, json_rel = pair
    return dict(status=status, part=part, rank=rank, scope="resolved", json_rel=json_rel,
                json=base64.b64encode(json_bytes).decode(), csv=base64.b64encode(csv_bytes).decode())


def test_failed_containers_conflicts_and_missing_ranks_are_each_named():
    jobs = [(0, 1), (0, 2), (1, 1), (1, 2)]
    good = _packet(make_pair())
    conflict = _packet(make_pair(part=1, run_id="run9"), part=1)
    results = [good, RuntimeError("part 0 rank 2 scope resolved: boom"), conflict]

    def fake_install(packet):
        if packet["part"] == 1:
            return "conflict: kept the local results/x.json; another run's record differs"
        return "wrote " + packet["json_rel"]

    problems = settle(jobs, results, fake_install, log=lambda m: None)
    assert any("boom" in p for p in problems)
    assert any(p.startswith("part 1 rank 1 resolved: conflict") for p in problems)
    assert "part 1 rank 2: no complete pair installed" in problems
    assert "part 0 rank 2: no complete pair installed" in problems
    assert not any(p.startswith("part 0 rank 1") for p in problems)


def test_a_launch_with_any_problem_exits_nonzero_naming_each(tmp_path):
    jobs = [(0, 1), (0, 2)]
    results = [_packet(make_pair()), RuntimeError("part 0 rank 2 scope resolved: boom")]
    write_plan(tmp_path, 0, "resolved", {1: 2, 2: 1}, {"CO": 2, "WA": 1})

    def real_install(packet):
        return install_pair(tmp_path, packet["json_rel"], base64.b64decode(packet["json"]),
                            base64.b64decode(packet["csv"]))

    with pytest.raises(SystemExit) as stop:
        finish_launch(jobs, results, real_install, tmp_path, [0], log=lambda m: None)
    message = str(stop.value.code)
    assert "boom" in message and "part 0 rank 2: no complete pair installed" in message
    assert "rank 2: missing" in message  # strict validation finds the gap too


def test_require_success_exits_nonzero_only_with_problems():
    require_success([])
    with pytest.raises(SystemExit) as stop:
        require_success(["part 3 rank 4: boom", "part 1 rank 1 resolved: conflict"])
    assert stop.value.code not in (0, None)
    assert "part 3 rank 4: boom" in str(stop.value.code) and "part 1 rank 1" in str(stop.value.code)


# ---------------------------------------------------------------------------
# [P3] Strict pair validation.


def _drop_identity(record):
    del record["identities"]["wic_draw_months_changed"]


def test_every_named_identity_check_is_required():
    with pytest.raises(ValueError, match="lacks identity checks"):
        validate_pair(*make_pair(mutate_record=_drop_identity)[:2])
    with pytest.raises(ValueError, match="unknown identity checks"):
        validate_pair(*make_pair(mutate_record=lambda r: r["identities"].update(made_up={"pass": True}))[:2])

    def out_of_rule(record):
        record["identities"]["zero_change_max_household_change"] = {"value": 0.5, "pass": True}

    with pytest.raises(ValueError, match="did not pass"):
        validate_pair(*make_pair(mutate_record=out_of_rule)[:2])
    # A smoke record also needs the fresh-simulation check.
    json_bytes, csv_bytes, _ = make_pair(smoke=True)
    smoke = json.loads(json_bytes)
    del smoke["identities"]["fresh_simulation_max_difference"]
    with pytest.raises(ValueError, match="lacks identity checks"):
        validate_pair(json.dumps(smoke).encode(), csv_bytes)


def test_the_complete_column_schema_is_required():
    with pytest.raises(ValueError, match="complete row schema"):
        validate_pair(*make_pair(mutate_rows=lambda f: f.drop(columns="d_net_without_health"))[:2])
    with pytest.raises(ValueError, match="component columns"):
        validate_pair(*make_pair(mutate_record=lambda r: r.update(component_columns=[]))[:2])


@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.0])
def test_ranks_must_be_positive_integers(bad):
    def set_rank(frame):
        frame["rank"] = 0 if bad is True else bad

    with pytest.raises(ValueError, match="not a positive integer"):
        validate_pair(*make_pair(mutate_record=lambda r: r.update(rank=bad), mutate_rows=set_rank)[:2])
    with pytest.raises(ValueError, match="rank 2 in a rank-1 record"):
        validate_pair(*make_pair(mutate_rows=lambda f: f.assign(rank=2))[:2])


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
@pytest.mark.parametrize("column", ["d_net_single_ptc", "d_net_without_health", "d_household_market_income"])
def test_measures_must_be_finite(column, value):
    def poison(frame):
        frame.loc[0, column] = value

    with pytest.raises(ValueError, match="non-finite"):
        validate_pair(*make_pair(mutate_rows=poison)[:2])


def test_duplicate_people_and_households_are_rejected():
    dup_id = people(3)
    dup_id[2]["person_id"] = dup_id[0]["person_id"]
    with pytest.raises(ValueError, match="person_id 1000 appears twice"):
        make_pair(tested=dup_id)
    dup_index = people(3)
    dup_index[2]["person_index"] = dup_index[0]["person_index"]
    with pytest.raises(ValueError, match="person_index 0 appears twice"):
        make_pair(tested=dup_index)
    dup_household = people(3)
    dup_household[2]["household_id"] = dup_household[0]["household_id"]
    with pytest.raises(ValueError, match="two tested adults at rank 1"):
        make_pair(tested=dup_household)


def test_rates_and_pay_must_match_the_record():
    with pytest.raises(ValueError, match="hourly wage differs"):
        validate_pair(*make_pair(mutate_rows=lambda f: f.assign(hourly_wage=f.hourly_wage + 0.01))[:2])
    with pytest.raises(ValueError, match="gross pay differs"):
        validate_pair(*make_pair(mutate_rows=lambda f: f.assign(gross_pay=f.gross_pay + 1))[:2])


def _two_ranks(root, rank2_people, plan_states=None):
    rank1 = people(2)
    install(root, make_pair(tested=rank1))
    install(root, make_pair(rank=2, tested=rank2_people, run_id="run2"))
    states = plan_states or {}
    if not states:
        for p in rank1 + rank2_people:
            states[p["state_code"]] = states.get(p["state_code"], 0) + 1
    write_plan(root, 0, "resolved", {1: 2, 2: len(rank2_people)}, states)


def test_a_person_in_two_ranks_is_rejected(tmp_path):
    again = [dict(people(2)[0])]  # the same adult and household again, at rank 2
    _two_ranks(tmp_path, again)
    with pytest.raises(ValueError, match="person_id 1000 in resolved rank 1 and resolved rank 2"):
        validate_results(tmp_path, parts=[0])


def test_a_person_in_two_scopes_is_rejected(tmp_path):
    tested = people(1, states=("MD",))
    install(tmp_path, make_pair(tested=tested))
    install(tmp_path, make_pair(scope="states:MD,NY", tested=tested, run_id="run3"))
    write_plan(tmp_path, 0, "resolved", {1: 1}, {"MD": 1})
    write_plan(tmp_path, 0, "states:MD,NY", {1: 1}, {"MD": 1})
    with pytest.raises(ValueError) as error:
        validate_results(tmp_path, parts=[0])
    assert "person_id 1000 in resolved rank 1 and states-MD-NY rank 1" in str(error.value)
    assert "MD tested by scopes" in str(error.value)


def test_results_must_be_complete_against_the_plan(tmp_path):
    install(tmp_path, make_pair(tested=people(2)))
    write_plan(tmp_path, 0, "resolved", {1: 3, 2: 1}, {"CO": 2, "WA": 2})
    with pytest.raises(ValueError) as error:
        validate_results(tmp_path, parts=[0])
    text = str(error.value)
    assert "rank 1: tested 2, planned 3" in text
    assert "rank 2: missing" in text
    assert "tested states differ from the plan" in text


def test_a_household_s_ranks_must_run_one_to_n(tmp_path):
    later = people(1, start=5)
    later[0]["household_id"] = 999  # a rank-2 adult whose household has no rank-1 adult
    _two_ranks(tmp_path, later)
    with pytest.raises(ValueError, match="household 999 has candidate ranks"):
        validate_results(tmp_path, parts=[0])


def test_a_complete_set_validates(tmp_path):
    _two_ranks(tmp_path, [dict(people(1, start=0)[0], person_index=7, person_id=1007)])
    summary = validate_results(tmp_path, parts=[0])
    assert summary["parts"][0]["resolved"] == {"ranks": [1, 2], "sample_candidates_tested": 3}


# ---------------------------------------------------------------------------
# The model-backed fixture's hand values.


def test_hand_values_for_the_model_fixture():
    # Texas full-time at $7.25: $15,080 less $10,400 is $4,680 taxable at 10%.
    assert federal_income_tax_before_credits(7.25 * 2080) == pytest.approx(468.0)
    # Washington at $11: $12,480 taxable, $932.50 on the first $9,325 and 15% above.
    assert federal_income_tax_before_credits(11.0 * 2080) == pytest.approx(932.5 + 0.15 * 3155)
    assert federal_income_tax_before_credits(9000) == 0
    assert employee_payroll_tax(15080) == pytest.approx(1153.62)
    assert min(RATES.values()) * 2080 > 15010  # every full-time job ends a childless EITC
    assert unreviewed_inputs(["weeks_worked", "tip_income", "age", "new_work_hours_input"]) == ["new_work_hours_input"]
    assert TABLE["unresolved"] == {}
