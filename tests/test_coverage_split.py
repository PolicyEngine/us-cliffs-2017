"""The coverage-split classifier on hand-built households: one fixture per bucket.

No tax or benefit formula runs. Each fixture writes person rows in the scenario
format (``base_``/``alt_`` columns, tax-unit amounts mapped to every member) and
checks the bucket, the household category and the counterfactual.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scripts import coverage_split_outputs as out
from scripts.coverage_split import (
    BUCKETS,
    CATEGORIES,
    add_tallies,
    classify_persons,
    household_category,
    person_values,
    scenario_households,
    set_flags,
    worst,
)

HEALTH = {
    "person": ["medicaid_cost", "msp_cost", "chip", "or_healthier_oregon_cost"],
    "tax_unit": ["assigned_aca_ptc", "ma_connector_care"],
    "costs_tax_unit": ["chip_premium"],
}
PERSON_COLUMNS = {
    "medicaid_enrolled": False, "is_medicaid_eligible": False, "chip_enrolled": False, "is_chip_eligible": False,
    "is_aca_ptc_eligible": False, "medicaid_category": "NONE", "medicaid_group": "NONE", "chip_category": "NONE",
    "medicaid_cost": 0.0, "msp_cost": 0.0, "chip": 0.0, "or_healthier_oregon_cost": 0.0,
    "tu_assigned_aca_ptc": 0.0, "tu_ma_connector_care": 0.0, "tu_chip_premium": 0.0,
    "msp_qmb_months": 0, "msp_slmb_months": 0, "msp_qi_months": 0,
}


def person(index, household, tax_unit, base=None, alt=None, state="CA"):
    """One person row; ``alt`` defaults to ``base``."""
    base = {**PERSON_COLUMNS, **(base or {})}
    alt = {**base, **(alt or {})}
    row = {"person_index": index, "person_id": 100 + index, "household_id": 1000 + household,
           "household_index": household, "tax_unit_index": tax_unit, "state_code": state, "age": 30}
    row.update({f"base_{k}": v for k, v in base.items()})
    row.update({f"alt_{k}": v for k, v in alt.items()})
    return row


def frame(*rows):
    return pd.DataFrame(list(rows))


MEDICAID = {"medicaid_enrolled": True, "is_medicaid_eligible": True, "medicaid_cost": 5000.0}
NOTHING = {"medicaid_enrolled": False, "is_medicaid_eligible": False, "medicaid_cost": 0.0}


def bucket_of(rows, index=0):
    classified = classify_persons(frame(*rows), HEALTH)
    return classified.set_index("person_index").loc[index]


def test_bucket_a_medicaid_ends_with_no_other_coverage():
    row = bucket_of([person(0, 0, 0, base=MEDICAID, alt=NOTHING)])
    assert row["bucket"] == "a"
    assert row["primary_base"] == "medicaid" and row["primary_alt"] == ""
    assert row["delta"] == pytest.approx(-5000)
    assert row["addback"] == 0


def test_bucket_b_medicaid_to_premium_credit():
    after = {**NOTHING, "is_aca_ptc_eligible": True, "tu_assigned_aca_ptc": 3000.0}
    row = bucket_of([person(0, 0, 0, base=MEDICAID, alt=after)])
    assert row["bucket"] == "b"
    assert (row["primary_base"], row["primary_alt"]) == ("medicaid", "ptc")
    assert row["delta"] == pytest.approx(-2000)
    assert row["addback"] == 0


def test_bucket_b_child_medicaid_to_chip():
    after = {**NOTHING, "chip_enrolled": True, "is_chip_eligible": True, "chip": 2000.0}
    row = bucket_of([person(0, 0, 0, base=MEDICAID, alt=after)])
    assert row["bucket"] == "b"
    assert row["primary_alt"] == "chip"


def test_bucket_c_mcm_family_tier_share_falls():
    row = bucket_of([person(0, 0, 0, base=MEDICAID, alt={"medicaid_cost": 4000.0}, state="NY")])
    assert row["bucket"] == "c_mcm"
    assert row["addback"] == pytest.approx(1000)
    assert row["addback_both_signs"] == pytest.approx(1000)


def test_bucket_c_mcm_msp_category_switch():
    base = {"msp_cost": 1600.0, "msp_qmb_months": 12}
    row = bucket_of([person(0, 0, 0, base=base, alt={"msp_cost": 1300.0, "msp_qmb_months": 0,
                                                     "msp_slmb_months": 12})])
    assert row["bucket"] == "c_mcm"
    assert row["primary_base"] == row["primary_alt"] == "msp"
    assert row["addback"] == pytest.approx(300)


def test_bucket_c_other_smaller_premium_credit_stays_a_loss():
    base = {"is_aca_ptc_eligible": True, "tu_assigned_aca_ptc": 3000.0}
    row = bucket_of([person(0, 0, 0, base=base, alt={"tu_assigned_aca_ptc": 2000.0})])
    assert row["bucket"] == "c_other"
    assert row["addback"] == 0


def test_bucket_c_other_chip_premium_rises():
    base = {"chip_enrolled": True, "is_chip_eligible": True, "chip": 2000.0, "tu_chip_premium": 0.0}
    row = bucket_of([person(0, 0, 0, base=base, alt={"tu_chip_premium": 240.0})])
    assert row["bucket"] == "c_other"
    assert row["delta"] == pytest.approx(-240)
    assert row["addback"] == 0


def test_rise_is_not_a_fall():
    row = bucket_of([person(0, 0, 0, base=MEDICAID, alt={"medicaid_cost": 6000.0})])
    assert row["bucket"] == "none"
    assert row["addback"] == 0
    assert row["addback_both_signs"] == pytest.approx(-1000)


def test_other_bucket_cost_share_without_coverage():
    rows = [person(0, 0, 0, alt={"tu_chip_premium": 100.0}), person(1, 0, 0, alt={"tu_chip_premium": 100.0})]
    classified = classify_persons(frame(*rows), HEALTH)
    assert list(classified["bucket"]) == ["other", "other"]
    assert classified["delta"].sum() == pytest.approx(-100)


def test_premium_credit_shared_over_eligible_members():
    rows = [person(0, 0, 0, base={"is_aca_ptc_eligible": True, "tu_assigned_aca_ptc": 3000.0}),
            person(1, 0, 0, base={"is_aca_ptc_eligible": True, "tu_assigned_aca_ptc": 3000.0}),
            person(2, 0, 0, base={**MEDICAID, "tu_assigned_aca_ptc": 3000.0})]
    values = person_values(frame(*rows), "base", HEALTH["person"], HEALTH["tax_unit"], HEALTH["costs_tax_unit"])
    assert list(values["primary"]) == ["ptc", "ptc", "medicaid"]
    assert list(values["value"]) == pytest.approx([1500, 1500, 5000])


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 2), st.booleans(), st.booleans(), st.booleans(),
                          st.floats(0, 9000), st.floats(0, 5000), st.floats(0, 500), st.floats(0, 800)),
                min_size=1, max_size=8))
def test_shares_add_up_to_tax_unit_totals(members):
    """However the members qualify, people's values add up to the unit's health value."""
    rows, totals = [], {}
    for i, (tu, medicaid, chip, ptc_eligible, mcost, ptc, premium, state) in enumerate(members):
        totals.setdefault(tu, (ptc, premium, state))
        tptc, tpremium, tstate = totals[tu]
        base = {"medicaid_enrolled": medicaid, "medicaid_cost": mcost if medicaid else 0.0,
                "chip_enrolled": chip, "chip": 100.0 if chip else 0.0, "is_aca_ptc_eligible": ptc_eligible,
                "tu_assigned_aca_ptc": tptc, "tu_chip_premium": tpremium, "tu_ma_connector_care": tstate}
        rows.append(person(i, 0, tu, base=base))
    persons = frame(*rows)
    values = person_values(persons, "base", HEALTH["person"], HEALTH["tax_unit"], HEALTH["costs_tax_unit"])
    expected = (persons["base_medicaid_cost"].sum() + persons["base_chip"].sum()
                + sum(p + s - c for p, c, s in totals.values()))
    assert values["value"].sum() == pytest.approx(expected, abs=1e-6)


def test_household_category_order():
    assert household_category(pd.Series(["none", "c_mcm", "a", "b"])) == "any_a"
    assert household_category(pd.Series(["c_other", "b"])) == "b_no_a"
    assert household_category(pd.Series(["c_mcm", "c_other"])) == "only_c_other"
    assert household_category(pd.Series(["c_mcm", "none"])) == "only_c_mcm"
    assert household_category(pd.Series(["other"])) == "other_only"
    assert household_category(pd.Series(["none", "none"])) == "no_fall"
    assert worst(["only_c_mcm", "b_no_a"], CATEGORIES) == "b_no_a"
    assert worst(["c_mcm", "c_other"], BUCKETS) == "c_other"


def _tested(rows):
    return pd.DataFrame(rows, columns=["person_index", "household_index", "change", "worker", "saved_d_with",
                                       "strict"])


def test_counterfactual_zeroes_within_program_falls_only():
    # Household 0: its only loss is a $1,000 family-tier Medicaid fall; it keeps -$400. Zeroing the
    # fall leaves +$600, so it leaves the strict group.
    # Household 1: an adult loses Medicaid (a) and a child's share falls (c_mcm); it keeps -$6,000.
    # Adding back the child's $1,000 still leaves -$5,000.
    # Household 2: a smaller premium credit (c_other) is a real loss; it stays strict.
    persons = frame(
        person(0, 0, 0, base=MEDICAID, alt={"medicaid_cost": 4000.0}, state="NY"),
        person(1, 1, 1, base=MEDICAID, alt=NOTHING),
        person(2, 1, 1, base=MEDICAID, alt={"medicaid_cost": 4000.0}),
        person(3, 2, 2, base={"is_aca_ptc_eligible": True, "tu_assigned_aca_ptc": 3000.0},
               alt={"tu_assigned_aca_ptc": 2000.0}),
    )
    classified = classify_persons(persons, HEALTH)
    tested = _tested([(0, 0, 1000.0, True, -400.0, True), (1, 1, 1000.0, True, -6000.0, True),
                      (3, 2, 1000.0, True, -100.0, True)])
    households = scenario_households(tested, classified, "change").set_index("household_index")
    assert list(households["category"]) == ["only_c_mcm", "any_a", "only_c_other"]
    assert list(households["strict_after_counterfactual"]) == [False, True, True]
    assert list(households["addback"]) == pytest.approx([1000, 1000, 0])


def test_raise_strict_needs_a_current_worker():
    persons = frame(person(0, 0, 0, base=MEDICAID, alt=NOTHING))
    classified = classify_persons(persons, HEALTH)
    tested = _tested([(0, 0, 1000.0, False, -400.0, False)])
    households = scenario_households(tested, classified, "change")
    assert not households["strict"].any()
    with pytest.raises(ValueError):
        scenario_households(_tested([(0, 0, 1000.0, False, -400.0, True)]), classified, "change")


def _scenario(rows, persons):
    classified = classify_persons(frame(*persons), HEALTH)
    tested = _tested(rows)
    return {"classified": classified, "households": scenario_households(tested, classified, "change")}


def test_sets_take_the_worst_category_and_any_strict_scenario():
    # Household 0 is strict in raise_1000 with only a within-Medicaid fall, and in the job test
    # with a loss of Medicaid: in `combined` it is any_a, in `raise_union` only_c_mcm.
    small = _scenario([(0, 0, 1000.0, True, -400.0, True)],
                      [person(0, 0, 0, base=MEDICAID, alt={"medicaid_cost": 4000.0})])
    job = _scenario([(0, 0, 15080.0, True, -2000.0, True)], [person(0, 0, 0, base=MEDICAID, alt=NOTHING)])
    empty = _scenario([(5, 5, 1000.0, True, 50.0, False)], [person(5, 5, 5)])
    scenarios = {("raise_1000", 1): small, ("raise_2000", 1): empty, ("raise_5000", 1): empty, ("job", 1): job}
    flags = set_flags(scenarios)
    assert flags["raise_union"]["category"]["only_c_mcm"] == [0]
    assert flags["raise_union"]["strict_after_counterfactual"] == []
    assert flags["combined"]["category"]["any_a"] == [0]
    assert flags["combined"]["strict_after_counterfactual"] == [0]
    assert flags["combined"]["person_bucket"]["a"] == [0]
    assert flags["raise_union"]["person_bucket"]["c_mcm"] == [0]
    assert flags["job"]["strict_adults"] == [0]


def test_add_tallies_merges_keys():
    assert add_tallies({"a": 1, "t": {"x": 2}}, {"a": 2, "t": {"y": 1}}) == {"a": 3, "t": {"x": 2, "y": 1}}
    assert add_tallies({}, {"a": 1}) == {"a": 1}


def test_scenario_paths_and_validation():
    assert out.scenario_label("job", 3) == "job_rank_03"
    assert out.scenario_json(1, "raise_5000", 2).endswith("/p4_1_s0/raise_5000_rank_02.json")
    with pytest.raises(ValueError):
        out.scenario_label("raise_3000", 1)
    import json

    record = {"status": "complete", "reproduction": {"pass": True, "max_abs_difference_d_with": 0.0},
              "rows": {"tested": {"sha256": out.sha256(b"t"), "file": "x"},
                       "persons": {"sha256": out.sha256(b"p"), "file": "y"}}}
    out.validate_scenario(json.dumps(record).encode(), b"t", b"p")
    with pytest.raises(ValueError):
        out.validate_scenario(json.dumps(record).encode(), b"t", b"changed")
    record["reproduction"]["max_abs_difference_d_with"] = 0.02
    with pytest.raises(ValueError):
        out.validate_scenario(json.dumps(record).encode(), b"t", b"p")
