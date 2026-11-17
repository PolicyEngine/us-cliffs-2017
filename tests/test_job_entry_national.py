"""National wage conventions and the result files of the national job-entry test."""

import copy
import gzip
import json
from fractions import Fraction

import pytest
from job_entry_pairs import make_pair, people
from microdf import MicroSeries

from scripts.expanded_job_entry import PILOT_WAGES
from scripts.expanded_job_entry_national import (
    sample_counts_by_state,
    scoped_hourly_wages,
)
from scripts.job_entry_outputs import (
    csv_gzip,
    install_bytes,
    install_pair,
    local_record,
    result_csv,
    result_json,
    scope_states,
    scope_tag,
    sha256,
    validate_pair,
)
from scripts.job_entry_wages import (
    UnresolvedWage,
    jurisdiction_rate,
    load_wages,
    national_wage_table,
    require_complete,
)

FLAT = {
    "AK": 9.80, "AL": 7.25, "AZ": 10.00, "CO": 9.30, "CT": 10.10, "DE": 8.25, "FL": 8.10,
    "GA": 7.25, "HI": 9.25, "IA": 7.25, "ID": 7.25, "IN": 7.25, "KS": 7.25, "KY": 7.25,
    "LA": 7.25, "MA": 11.00, "MO": 7.70, "MS": 7.25, "NC": 7.25, "ND": 7.25, "NH": 7.25,
    "NJ": 8.44, "NM": 7.50, "OK": 7.25, "PA": 7.25, "RI": 9.60, "SC": 7.25, "SD": 8.65,
    "TN": 7.25, "TX": 7.25, "UT": 7.25, "VA": 7.25, "WA": 11.00, "WI": 7.25, "WY": 7.25,
}
LARGE_EMPLOYER = {
    "AR": 8.50, "CA": 10.50, "IL": 8.25, "MI": 8.90, "MN": 9.50, "MT": 8.15, "NE": 9.00,
    "OH": 8.15, "VT": 10.00, "WV": 8.75,
}
# Days in 2017: 1 Jan-30 Jun is 181, 1 Jul-31 Dec is 184; Maine's 7 January start
# leaves 6 days at $7.50 and 359 at $9.00; New York's rest-of-state rate changes on
# 31 December, leaving 364 days at $9.70 and 1 at $10.40.
WITHIN_YEAR = {
    "DC": (Fraction("11.50") * 181 + Fraction("12.50") * 184) / 365,
    "MD": (Fraction("8.75") * 181 + Fraction("9.25") * 184) / 365,
    "ME": (Fraction("7.50") * 6 + Fraction("9.00") * 359) / 365,
    "NY": (Fraction("9.70") * 364 + Fraction("10.40") * 1) / 365,
    "OR": (Fraction("9.75") * 181 + Fraction("10.25") * 184) / 365,
}
# Each dated path as (from, to, hourly, days), from the sourced effective dates:
# Maryland 1 July 2017 (Ch. 262 of 2014), Maine 7 January 2017 (IB 2015, c. 2),
# New York 31 December 2017 (NY DOL history).
PATHS = {
    "MD": [("2017-01-01", "2017-06-30", 8.75, 181), ("2017-07-01", "2017-12-31", 9.25, 184)],
    "ME": [("2017-01-01", "2017-01-06", 7.50, 6), ("2017-01-07", "2017-12-31", 9.00, 359)],
    "NY": [("2017-01-01", "2017-12-30", 9.70, 364), ("2017-12-31", "2017-12-31", 10.40, 1)],
}


@pytest.fixture(scope="module")
def table():
    return national_wage_table()


@pytest.fixture()
def wages():
    return copy.deepcopy(load_wages()[0]["states"])


def test_every_jurisdiction_has_a_rate(table):
    assert table["unresolved"] == {}
    assert len(table["rates"]) == 51
    assert require_complete(table) == table["rates"]


def test_a_missing_later_rate_leaves_the_state_unresolved():
    data = copy.deepcopy(load_wages()[0])
    data["states"]["MD"]["variants"] = []
    data["states"]["NY"]["variants"] = [
        v for v in data["states"]["NY"]["variants"] if v.get("starts") != "2017-12-31"
    ]
    stripped = national_wage_table(data, "stripped")
    assert set(stripped["unresolved"]) == {"MD", "NY"}
    assert "later rate is absent" in stripped["unresolved"]["MD"]
    assert "2017-12-31" in stripped["unresolved"]["NY"]
    assert len(stripped["rates"]) == 49
    with pytest.raises(UnresolvedWage, match="MD"):
        require_complete(stripped)


def test_flat_and_large_employer_rates(table):
    for code, rate in {**FLAT, **LARGE_EMPLOYER, "NV": 8.25}.items():
        assert table["rates"][code] == rate, code
    for code in LARGE_EMPLOYER:
        assert table["rows"][code]["rule"] == "large-employer rate"
    assert table["rows"]["NV"]["rule"] == "employer offers no health coverage"


def test_within_year_rates_are_weighted_by_day(table):
    for code, exact in WITHIN_YEAR.items():
        row = table["rows"][code]
        assert Fraction(row["hourly_exact"]) == exact, code
        assert sum(piece["days"] for piece in row["path"]) == 365
        assert row["gross_pay"] == float(exact * 2080)
    assert table["rows"]["OR"]["rule"].startswith("standard region (standard)")
    assert table["rows"]["NY"]["rule"].startswith("standard region (rest of state)")
    assert table["rows"]["MD"]["rule"].startswith("statewide")
    for code, path in PATHS.items():
        got = [(p["from"], p["to"], p["hourly"], p["days"]) for p in table["rows"][code]["path"]]
        assert got == path, code
        assert table["rows"][code]["accepted_unverified"] is None, code
    assert table["rows"]["MD"]["hourly"] == pytest.approx(9.00205, abs=5e-6)
    assert table["rows"]["NY"]["hourly"] == pytest.approx(9.70192, abs=5e-6)
    # The codified "starting January 1, 2017" text would give Maine $9.00 instead.
    assert 9.00 * 2080 - table["rows"]["ME"]["gross_pay"] == pytest.approx(51.29, abs=0.01)


def test_maine_needs_its_verified_flag(wages):
    with pytest.raises(UnresolvedWage, match="unverified"):
        jurisdiction_rate("ME", dict(wages["ME"], verified=False))


def test_gross_pay_and_pilot_agreement(table):
    for code, row in table["rows"].items():
        assert row["gross_pay"] == pytest.approx(row["hourly"] * 2080, abs=1e-9)
        assert row["hourly"] >= 7.25
    for code, rate in PILOT_WAGES.items():
        assert table["rates"][code] == rate
    assert {c for c, r in table["rows"].items() if r["federal_floor_binds"]} == {
        "AL", "GA", "LA", "MS", "OK", "SC", "TN", "WY"
    }


def test_missing_or_contradictory_rates_get_no_default(wages):
    flat = dict(wages["AK"], reference_hourly=None)
    with pytest.raises(UnresolvedWage, match="no reference_hourly"):
        jurisdiction_rate("AK", flat)
    with pytest.raises(UnresolvedWage, match="unverified"):
        jurisdiction_rate("AK", dict(wages["AK"], verified=False))
    with pytest.raises(UnresolvedWage, match="contradicts amount"):
        jurisdiction_rate("AK", dict(wages["AK"], amount=9.75))
    gap = copy.deepcopy(wages["DC"])
    gap["variants"][1]["starts"] = "2017-07-02"
    with pytest.raises(UnresolvedWage, match="2017-07-01"):
        jurisdiction_rate("DC", gap)
    overlap = copy.deepcopy(wages["DC"])
    overlap["variants"][1]["starts"] = "2017-06-30"
    with pytest.raises(UnresolvedWage, match="overlapping"):
        jurisdiction_rate("DC", overlap)
    tiered = copy.deepcopy(wages["CA"])
    with pytest.raises(UnresolvedWage, match="no convention"):
        jurisdiction_rate("ZZ", dict(tiered, verified=True))
    small = copy.deepcopy(wages["CA"])
    small["variants"] = [v for v in small["variants"] if v["employer_size"] != "26or more employees"]
    with pytest.raises(UnresolvedWage, match="large-employer"):
        jurisdiction_rate("CA", small)


def test_federal_floor_applies_to_each_dated_rate(wages):
    low = copy.deepcopy(wages["DC"])
    low["amount"] = low["reference_hourly"] = 5.15
    low["variants"][0]["hourly"] = 5.15
    row = jurisdiction_rate("DC", low)
    assert Fraction(row["hourly_exact"]) == (Fraction("7.25") * 181 + Fraction("12.50") * 184) / 365
    assert row["federal_floor_binds"]


def test_scoped_wages_keep_microseries_and_mark_deferred_states():
    state = MicroSeries(["CO", "MD", "WA", "NY"], weights=[2, 3, 4, 5])
    hourly, covered = scoped_hourly_wages(state, {"CO": 9.30, "WA": 11.00})
    assert isinstance(hourly, MicroSeries) and isinstance(covered, MicroSeries)
    assert hourly.tolist() == [9.30, 0.0, 11.00, 0.0]
    assert covered.tolist() == [True, False, True, False]
    assert covered.sum() == 6  # weighted through MicroSeries
    with pytest.raises(ValueError, match="outside the 51"):
        scoped_hourly_wages(MicroSeries(["PR"], weights=[1]), {"CO": 9.30})
    assert sample_counts_by_state(~covered, state) == {"MD": 1, "NY": 1}


def test_scope_names():
    assert scope_tag("resolved") == "resolved"
    assert scope_tag("states:ny,MD") == "states-MD-NY"
    assert scope_states("states:NY,MD") == ["MD", "NY"]
    assert scope_states("resolved") is None
    with pytest.raises(ValueError):
        scope_tag("everything")
    assert result_json("job_entry_2017_p4_0_s0", "resolved", 1) == (
        "results/job_entry/parts/job_entry_2017_p4_0_s0/resolved/rank_01.json"
    )
    assert "/per_person/" in result_csv("job_entry_2017_p4_0_s0", "resolved", 1, "abc123")
    with pytest.raises(ValueError):
        result_csv("x", "resolved", 1, "../escape")


def _pair(rank=1, count=2, passed=True, run_id="run1"):
    """A strict-valid pair (tests/job_entry_pairs.py); ``passed=False`` fails one identity check."""
    def fail(record):
        record["identities"]["zero_change_max_household_change"]["pass"] = False

    json_bytes, csv_bytes, _ = make_pair(rank=rank, tested=people(count), run_id=run_id,
                                         mutate_record=None if passed else fail)
    return (json_bytes, csv_bytes), json.loads(json_bytes)["rows"]["file"]


def test_pair_validation_rejects_anything_incomplete():
    (json_bytes, csv_bytes), csv_rel = _pair()
    record = validate_pair(json_bytes, csv_bytes, {"part": 0, "rank": 1, "scope": "resolved"})
    assert record["rows"]["file"] == csv_rel
    assert gzip.decompress(csv_bytes).decode().splitlines()[0].startswith(
        "person_index,person_id,household_id,state_code,rank,hourly_wage,gross_pay,d_net_single_ptc")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_pair(json_bytes, csv_gzip("person_index,rank,gross_pay\n0,1,1\n"))
    with pytest.raises(ValueError, match="rank"):
        validate_pair(json_bytes, csv_bytes, {"rank": 2})
    failed = json.loads(json_bytes)
    failed["identities"]["zero_change_max_household_change"]["pass"] = False
    with pytest.raises(ValueError, match="identity"):
        validate_pair(json.dumps(failed).encode(), csv_bytes)
    partial = dict(json.loads(json_bytes), status="running")
    with pytest.raises(ValueError, match="status"):
        validate_pair(json.dumps(partial).encode(), csv_bytes)
    short = json.loads(json_bytes)
    short["rows"]["count"] = 1
    with pytest.raises(ValueError, match="row count"):
        validate_pair(json.dumps(short).encode(), csv_bytes)
    with pytest.raises(ValueError, match="identity"):
        validate_pair(*_pair(passed=False)[0])
    # The review's reproduction: duplicate person rows with one arbitrary passing check.
    loose = json.loads(json_bytes)
    loose["identities"] = {"anything": {"value": 0, "pass": True}}
    with pytest.raises(ValueError, match="lacks identity checks"):
        validate_pair(json.dumps(loose).encode(), csv_bytes)


def test_install_never_overwrites_and_leaves_no_temporary_files(tmp_path):
    assert install_bytes(tmp_path, "a/b.json", b"first") == "wrote"
    assert install_bytes(tmp_path, "a/b.json", b"first") == "same"
    assert install_bytes(tmp_path, "a/b.json", b"second") == "differs"
    assert (tmp_path / "a" / "b.json").read_bytes() == b"first"
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["b.json"]


def test_pairs_install_rows_first_and_refuse_a_conflict(tmp_path):
    (json_bytes, csv_bytes), csv_rel = _pair()
    json_rel = result_json("job_entry_2017_p4_0_s0", "resolved", 1)
    assert local_record(tmp_path, json_rel) is None
    assert install_pair(tmp_path, json_rel, json_bytes, csv_bytes).startswith("wrote")
    assert local_record(tmp_path, json_rel)["rows"]["sha256"] == sha256(csv_bytes)
    # A second, different complete pair for the same rank keeps the first record.
    (other_json, other_csv), _ = _pair(count=3, run_id="run2")
    assert install_pair(tmp_path, json_rel, other_json, other_csv).startswith("conflict: kept the local")
    assert (tmp_path / json_rel).read_bytes() == json_bytes
    # Rows that differ under the same name never let their record in.
    other = tmp_path / "other"
    install_bytes(other, csv_rel, b"not the rows")
    assert install_pair(other, json_rel, json_bytes, csv_bytes).startswith("conflict")
    assert not (other / json_rel).exists()
    # An installed record whose rows are damaged no longer counts as done.
    (tmp_path / csv_rel).write_bytes(b"damaged")
    assert local_record(tmp_path, json_rel) is None
