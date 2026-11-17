"""Invariants of the combined raise-and-job union, on synthetic households.

The property tests build a real policyengine-core Microsimulation (person and
household entities, calibrated household weights, no tax formulas), run the
production counting code on random saved changes, and compare every count with a
brute-force oracle written independently here. Weights are whole numbers, so the
oracle and MicroSeries agree exactly.
"""

import copy
import io
import json

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from job_entry_pairs import install, make_pair, write_plan

from scripts import combined_union_inputs as ci
from scripts.expanded_combined_union import (
    FIELDS,
    GROWS,
    HALF,
    JOB_INCREMENT,
    LEVELS,
    MEASURES,
    NESTED,
    OVERLAP_BASES,
    RAISES,
    SETS,
    STRICT,
    THRESHOLDS,
    PartCounter,
    add_in_order,
    add_part_metrics,
    bootstrap_parts,
    check_count_invariants,
    check_set_invariants,
    compare_counts,
    count_sets,
    final_status_problems,
    household_any,
    raise_union_view,
    reproduce_job_records,
    resample,
    validate_job_rows,
)
from scripts.expanded_raise_union import CHANGES
from scripts.job_entry_outputs import sha256

YEAR = 2017
RATIOS = [-0.5, -0.01, 0.0, 0.1, 0.2, 0.3, 0.5, 0.55, 0.6, 0.9, 1.0]
# The job runner counts d < t x pay and the union d / pay < t; ratios exactly at a threshold
# can round differently between the two, so the synthetic job rows avoid them.
JOB_RATIOS = [-0.5, -0.01, 0.0, 0.1, 0.3, 0.55, 0.9, 1.0]


def synthetic_sim(sizes, weights):
    from policyengine_core.entities import build_entity
    from policyengine_core.periods import YEAR as Y
    from policyengine_core.simulations.microsimulation import Microsimulation
    from policyengine_core.taxbenefitsystems import TaxBenefitSystem
    from policyengine_core.variables import Variable

    person = build_entity(key="person", plural="people", label="Person", is_person=True)
    household = build_entity(key="household", plural="households", label="Household",
                             roles=[{"key": "member", "plural": "members", "label": "Member"}])
    system = TaxBenefitSystem([person, household])
    system.add_variable(type("household_weight", (Variable,), {
        "value_type": float, "entity": household, "definition_period": Y, "label": "weight"}))
    people, households, k = {}, {}, 0
    for h, (size, w) in enumerate(zip(sizes, weights)):
        members = []
        for _ in range(size):
            people[f"p{k}"] = {}
            members.append(f"p{k}")
            k += 1
        households[f"h{h}"] = {"members": members, "household_weight": {YEAR: float(w)}}
    return Microsimulation(tax_benefit_system=system, situation={"people": people, "households": households})


@st.composite
def populations(draw, with_job=True):
    n = draw(st.integers(1, 6))
    sizes = draw(st.lists(st.integers(1, 4), min_size=n, max_size=n))
    weights = draw(st.lists(st.integers(1, 500), min_size=n, max_size=n))
    sources = draw(st.lists(st.integers(0, n - 1), min_size=n, max_size=n))
    hh = np.repeat(np.arange(n), sizes)
    people = len(hh)
    # Raise rows: up to two adults per household, the same adults and workers for every raise.
    raise_people, ranks = [], []
    for h in range(n):
        members = np.flatnonzero(hh == h)
        take = draw(st.integers(0, min(2, len(members))))
        raise_people += members[:take].tolist()
        ranks += list(range(1, take + 1))
    workers = [draw(st.booleans()) for _ in raise_people]
    frames = {}
    for key, amount in CHANGES.items():
        ratios = [draw(st.sampled_from(RATIOS)) for _ in raise_people]
        health = [draw(st.sampled_from(RATIOS)) for _ in raise_people]
        frames[key] = pd.DataFrame({
            "person_index": np.array(raise_people, dtype=np.int64),
            "person_id": np.array(raise_people, dtype=np.int64) + 1000,
            "household_id": hh[raise_people].astype(np.int64) + 1,
            "rank": np.array(ranks, dtype=np.int64),
            "change": np.full(len(raise_people), amount),
            "worker": np.array(workers, dtype=bool),
            "d_net_single_ptc": np.array(health, dtype=float) * amount,
            "d_net_without_health": np.array(ratios, dtype=float) * amount,
        })
    # Job rows: anyone not a raise worker may be a candidate, one per household per rank.
    worker_people = {p for p, w in zip(raise_people, workers) if w}
    job_people = [p for p in range(people) if p not in worker_people and with_job and draw(st.booleans())]
    rank_of, seen = [], {}
    for p in job_people:
        seen[hh[p]] = seen.get(hh[p], 0) + 1
        rank_of.append(seen[hh[p]])
    gross = np.array([draw(st.sampled_from([15080.0, 20800.0])) for _ in job_people])
    job = pd.DataFrame({
        "person_index": np.array(job_people, dtype=np.int64),
        "person_id": np.array(job_people, dtype=np.int64) + 1000,
        "household_id": hh[job_people].astype(np.int64) + 1,
        "state_code": ["AA"] * len(job_people),
        "rank": np.array(rank_of, dtype=np.int64),
        "gross_pay": gross,
        "d_net_single_ptc": np.array([draw(st.sampled_from(JOB_RATIOS)) for _ in job_people]) * gross,
        "d_net_without_health": np.array([draw(st.sampled_from(JOB_RATIOS)) for _ in job_people]) * gross,
        "scope": ["resolved"] * len(job_people),
    })
    return dict(sizes=np.array(sizes), weights=np.array(weights, dtype=float), sources=np.array(sources),
                hh=hh, frames=frames, job=job)


# ---------------------------------------------------------------------------
# An independent oracle: plain loops over households with the synthetic weights.


def o_households(flags, hh, n):
    out = np.zeros(n, bool)
    for p in np.flatnonzero(flags):
        out[hh[p]] = True
    return out


def o_counts(pop, hh_flags, adult_flags=None):
    w, sizes, hh = pop["weights"], pop["sizes"], pop["hh"]
    out = {"households": float(sum(w[h] for h in np.flatnonzero(hh_flags))),
           "household_members": float(sum(w[h] * sizes[h] for h in np.flatnonzero(hh_flags)))}
    if adult_flags is not None:
        out["adults"] = float(sum(w[hh[p]] for p in np.flatnonzero(adult_flags) if hh_flags[hh[p]]))
    return out


def o_flags(pop, measure):
    """test -> threshold -> person flags, written without the production helpers."""
    column = MEASURES[measure]
    people = len(pop["hh"])
    out = {}
    for key, frame in pop["frames"].items():
        out[key] = {}
        for name, t in THRESHOLDS.items():
            flags = np.zeros(people, bool)
            for row in frame.itertuples():
                if row.worker and getattr(row, column) / row.change < t:
                    flags[row.person_index] = True
            out[key][name] = flags
    out["job"] = {}
    for name, t in THRESHOLDS.items():
        flags = np.zeros(people, bool)
        for row in pop["job"].itertuples():
            if getattr(row, column) / row.gross_pay < t:
                flags[row.person_index] = True
        out["job"][name] = flags
    return out


def o_original(pop, measure, key):
    column = MEASURES[measure]
    flags = np.zeros(len(pop["hh"]), bool)
    for row in pop["frames"][key].itertuples():
        if getattr(row, column) / row.change < 0:
            flags[row.person_index] = True
    return flags


def o_records(pop):
    w, hh = pop["weights"], pop["hh"]
    n = len(w)
    records = {}
    for key, frame in pop["frames"].items():
        workers = frame.loc[frame["worker"], "person_index"].to_numpy()
        change = {"workers_reached": float(sum(w[hh[p]] for p in workers))}
        for measure in MEASURES:
            flags = o_original(pop, measure, key)
            households = o_households(flags, hh, n)
            c = o_counts(pop, households, flags)
            worker_flags = np.zeros(len(hh), bool)
            worker_flags[workers] = True
            change[measure] = {
                "people_on_cliff": c["adults"], "households_with_person_on_cliff": c["households"],
                "people_in_those_households": c["household_members"],
                "workers_on_cliff": float(sum(w[hh[p]] for p in np.flatnonzero(flags & worker_flags))),
            }
        records[key] = {"change": change}
    return records


def o_metrics(pop):
    """Every count count_sets reports, by brute force."""
    hh, n = pop["hh"], len(pop["weights"])
    metrics = {}
    for measure in MEASURES:
        tests = o_flags(pop, measure)
        person = {s: {t: np.logical_or.reduce([tests[c][t] for c in comps]) for t in THRESHOLDS}
                  for s, comps in SETS.items()}
        house = {s: {t: o_households(person[s][t], hh, n) for t in THRESHOLDS} for s in SETS}
        for s in SETS:
            for t in THRESHOLDS:
                metrics[f"{measure}|{s}|{t}"] = o_counts(pop, house[s][t], person[s][t])
            extra = house[s][HALF] & ~house[s][STRICT]
            metrics[f"{measure}|{s}|additional"] = o_counts(pop, extra, person[s][HALF])
        originals = {}
        for key in RAISES:
            flags = o_original(pop, measure, key)
            originals[key] = o_households(flags, hh, n)
            metrics[f"{measure}|original_{key}"] = o_counts(pop, originals[key], flags)
        for base in OVERLAP_BASES:
            for level, t in LEVELS.items():
                metrics[f"{measure}|{base}|original_1000_in_{level}"] = o_counts(
                    pop, originals["raise_1000"] & house[base][t])
                metrics[f"{measure}|{base}|original_1000_outside_{level}"] = o_counts(
                    pop, originals["raise_1000"] & ~house[base][t])
            metrics[f"{measure}|{base}|below_half_outside_original_1000"] = o_counts(
                pop, house[base][HALF] & ~originals["raise_1000"], person[base][HALF])
        for base, raise_only in JOB_INCREMENT.items():
            for level, t in LEVELS.items():
                metrics[f"{measure}|{base}|added_by_job_{level}"] = o_counts(
                    pop, house[base][t] & ~house[raise_only][t], person[base][t])
    return metrics


def run_counts(pop, job=None, per_source=True):
    sim = synthetic_sim(pop["sizes"], pop["weights"])
    counter = PartCounter(sim, YEAR, "t", pop["sources"], per_source=per_source)
    result = count_sets(counter, pop["frames"], o_records(pop), pop["job"] if job is None else job)
    return counter, result


# ---------------------------------------------------------------------------
# Counting and invariants


@given(populations())
def test_counts_match_brute_force_oracle_and_every_invariant_holds(pop):
    counter, result = run_counts(pop)
    expected = o_metrics(pop)
    assert set(counter.metrics) == set(expected)
    for label, fields in expected.items():
        assert counter.metrics[label] == fields, label
    # The four household-level invariants and the six count-level ones.
    assert all(check_set_invariants(result["household"], result["groups"]).values())
    assert all(check_count_invariants(counter.metrics).values())
    # Per-source totals come from MicroSeries.groupby and add up to each count.
    for label, fields in counter.sources_totals.items():
        for f, column in fields.items():
            assert column.sum() == pytest.approx(counter.metrics[label][f], rel=1e-12)


@given(populations())
def test_threshold_nesting_unions_and_groups_at_household_level(pop):
    _, result = run_counts(pop)
    for measure, sets in result["household"].items():
        for name, by_threshold in sets.items():
            for low, high in zip(NESTED, NESTED[1:]):
                assert not (by_threshold[low] & ~by_threshold[high]).any()
            strict, half = by_threshold[STRICT], by_threshold[HALF]
            additional = result["groups"][measure][name]["additional"]
            assert not (strict & additional).any()
            assert np.array_equal(strict | additional, half)
            for t in THRESHOLDS:
                for component in SETS[name]:
                    assert not (sets[component][t] & ~by_threshold[t]).any()
        for small, large in GROWS:
            for t in (STRICT, HALF):
                assert not (sets[small][t] & ~sets[large][t]).any()


@given(populations())
def test_union_count_between_largest_component_and_sum(pop):
    counter, _ = run_counts(pop, per_source=False)
    for measure in MEASURES:
        for name, components in SETS.items():
            for t in THRESHOLDS:
                for f in FIELDS:
                    union = counter.metrics[f"{measure}|{name}|{t}"][f]
                    parts = [counter.metrics[f"{measure}|{c}|{t}"][f] for c in components]
                    assert max(parts) <= union <= sum(parts)


@given(populations())
def test_emptied_job_rows_reduce_combined_to_the_raise_union_exactly(pop):
    full, _ = run_counts(pop, per_source=False)
    empty, result = run_counts(pop, job=pop["job"].iloc[0:0], per_source=False)
    for measure in MEASURES:
        for t in THRESHOLDS:
            assert empty.metrics[f"{measure}|combined|{t}"] == full.metrics[f"{measure}|raise_union|{t}"]
            assert empty.metrics[f"{measure}|combined_1000|{t}"] == full.metrics[f"{measure}|raise_1000|{t}"]
            assert empty.metrics[f"{measure}|job|{t}"] == {"adults": 0.0, "households": 0.0,
                                                           "household_members": 0.0}
    # The emptied combined set, read as the raise union's keys, equals the raise union itself.
    ours, _ = raise_union_view(full.metrics)
    emptied, _ = raise_union_view(empty.metrics, base="combined")
    assert compare_counts(emptied, ours, "emptied")["exact"]


@given(populations())
def test_adding_a_test_never_lowers_strict_or_below_half(pop):
    counter, _ = run_counts(pop, per_source=False)
    for measure in MEASURES:
        for small, large in GROWS:
            for t in (STRICT, HALF):
                for f in FIELDS:
                    assert counter.metrics[f"{measure}|{small}|{t}"][f] <= counter.metrics[f"{measure}|{large}|{t}"][f]


@given(populations())
def test_each_person_counted_once(pop):
    """Flagged adults never exceed residents, and residents never exceed the population.

    PartCounter.record also stops unless every resident maps to 0 or 1 and every
    flagged adult lives in a flagged household; the oracle test above checks each
    resident is counted once by value."""
    counter, result = run_counts(pop, per_source=False)
    for measure in MEASURES:
        for name in SETS:
            for t in THRESHOLDS:
                c = counter.metrics[f"{measure}|{name}|{t}"]
                assert c["adults"] <= c["household_members"]
                assert c["household_members"] <= float((pop["weights"] * pop["sizes"]).sum())


def test_job_rows_repeating_a_person_or_household_rank_are_rejected():
    table = pd.DataFrame({"person_id": [1, 2, 3], "person_household_id": [10, 10, 20]})
    rows = pd.DataFrame({"person_index": [0, 1, 2], "person_id": [1, 2, 3], "household_id": [10, 10, 20],
                         "state_code": ["AA", "AA", "BB"], "rank": [1, 2, 1],
                         "gross_pay": [15080.0, 15080.0, 20800.0],
                         "d_net_single_ptc": [1.0, -5.0, 3.0], "d_net_without_health": [1.0, 2.0, 3.0]})
    rates = {"AA": 7.25, "BB": 10.0}
    validate_job_rows(rows, table, rates)
    for column, values, match in (
        ("person_index", [0, 0, 2], "repeat a person"),
        ("rank", [1, 1, 1], "two adults in one household"),
        ("household_id", [10, 20, 20], "household IDs"),
        ("gross_pay", [15080.0, 15080.0, 20000.0], "gross pay"),
        ("state_code", ["AA", "AA", "CC"], "without a recorded rate"),
    ):
        bad = rows.copy()
        bad[column] = values
        if column == "person_index":
            bad["person_id"] = [1, 1, 3]
        with pytest.raises(ValueError, match=match):
            validate_job_rows(bad, table, rates)


@settings(max_examples=10)
@given(populations())
def test_a_raise_worker_who_is_also_a_job_candidate_is_rejected(pop):
    assume(pop["frames"]["raise_1000"]["worker"].any())
    worker = pop["frames"]["raise_1000"].loc[pop["frames"]["raise_1000"]["worker"]].iloc[0]
    job = pd.concat([pop["job"], pd.DataFrame({
        "person_index": [worker.person_index], "person_id": [worker.person_id],
        "household_id": [worker.household_id], "state_code": ["AA"], "rank": [9], "gross_pay": [15080.0],
        "d_net_single_ptc": [0.0], "d_net_without_health": [0.0], "scope": ["resolved"]})], ignore_index=True)
    with pytest.raises(ValueError, match="also a job-entry candidate"):
        run_counts(pop, job=job, per_source=False)


def test_invariant_checks_catch_violations():
    yes, no = np.array([True, False]), np.array([False, False])
    household = {m: {s: {t: no.copy() for t in THRESHOLDS} for s in SETS} for m in MEASURES}
    groups = {m: {s: {"additional": no.copy()} for s in SETS} for m in MEASURES}
    assert all(check_set_invariants(household, groups).values())
    broken = copy.deepcopy(household)
    broken["with_health"]["job"][STRICT] = yes  # strict without below-20%
    checks = check_set_invariants(broken, groups)
    assert not checks["threshold_nesting_households"]
    assert not checks["union_contains_components_households"]  # combined lacks it
    bad_groups = copy.deepcopy(groups)
    bad_groups["with_health"]["raise_1000"]["additional"] = yes  # additional outside below-half
    assert not check_set_invariants(household, bad_groups)["strict_additional_partition_below_half_households"]


@given(populations())
def test_count_checks_catch_a_shrinking_union(pop):
    counter, _ = run_counts(pop, per_source=False)
    metrics = copy.deepcopy(counter.metrics)
    metrics[f"with_health|combined|{HALF}"]["household_members"] = -1.0
    checks = check_count_invariants(metrics)
    assert not checks["adding_a_test_never_lowers_strict_or_below_half_counts"]
    assert not checks["strict_plus_additional_equals_below_half_counts"]


# ---------------------------------------------------------------------------
# Job runner reproduction


def runner_records(pop):
    w, hh = pop["weights"], pop["hh"]
    job, records = pop["job"], []
    for rank in sorted(set(job["rank"])):
        rows = job[job["rank"] == rank]
        touched = set(hh[rows["person_index"]])
        below = {column: {f"keeps_less_than_{v:g}": int((rows[column] < v * rows["gross_pay"]).sum())
                          for v in THRESHOLDS.values()} for column in MEASURES.values()}
        records.append({"scope": "resolved", "rank": int(rank), "counts": {
            "weighted_candidates_tested": float(sum(w[hh[p]] for p in rows["person_index"])),
            "weighted_members_of_touched_households": float(sum(w[h] * pop["sizes"][h] for h in touched)),
            "sample_tested_below_threshold": below}})
    return records


@given(populations())
def test_job_runner_per_rank_totals_are_reproduced_and_a_wrong_total_stops(pop):
    counter, result = run_counts(pop, per_source=False)
    sample = {m: {t: int(result["sets"][m]["job"][t].sum()) for t in THRESHOLDS} for m in MEASURES}
    records = runner_records(pop)
    out = reproduce_job_records(counter, pop["job"], records, sample)
    assert out["pass"] and out["max_relative_difference"] == 0
    if records:
        wrong = copy.deepcopy(records)
        wrong[0]["counts"]["weighted_candidates_tested"] += 1
        with pytest.raises(ValueError, match="weighted_candidates_tested"):
            reproduce_job_records(PartCounter(counter.sim, YEAR, "t2", per_source=False), pop["job"], wrong, sample)


# ---------------------------------------------------------------------------
# Bootstrap


def test_batched_resample_matches_driver_intervals():
    from scripts.driver_intervals import resample as sequential

    rng = np.random.default_rng(3)
    stats = rng.integers(0, 5, size=(40, 3)).astype(float)
    stats[::4] = 0
    np.testing.assert_allclose(resample(stats, 17, 5, batch=4), sequential(stats, 17, 5), rtol=1e-12)


def _npz(sources, matrix, columns):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, sources=np.asarray(sources), matrix=np.asarray(matrix, float),
                        columns=np.array(columns))
    return buffer.getvalue()


def test_bootstrap_resamples_parts_jointly_and_rejects_shared_sources():
    columns = ["a|households", "b|households"]
    records = [{"part": p, "metrics": {"a": {"households": 2.0}, "b": {"households": 1.0 * (p == 0)}}}
               for p in range(ci.PARTS)]
    npz = [_npz([10 * p, 10 * p + 1], [[1.0, 1.0 * (p == 0)], [1.0, 0.0]], columns) for p in range(ci.PARTS)]
    out = bootstrap_parts(records, npz, draws=50, seed=1)
    assert out["source_households"] == 8 and out["draws"] == 50
    assert out["columns"]["a|households"]["estimate"] == 8.0
    lo, hi = out["columns"]["b|households"]["interval_95"]
    assert 0 <= lo <= 1 <= hi
    shared = list(npz)
    shared[1] = _npz([0, 11], [[1.0, 0.0], [1.0, 0.0]], columns)
    with pytest.raises(ValueError, match="two parts"):
        bootstrap_parts(records, shared, draws=5, seed=1)
    wrong = copy.deepcopy(records)
    wrong[0]["metrics"]["a"]["households"] = 3.0
    with pytest.raises(ValueError, match="per-source totals add"):
        bootstrap_parts(wrong, npz, draws=5, seed=1)


# ---------------------------------------------------------------------------
# Raise-union key mapping and inputs


@settings(max_examples=3)
@given(populations())
def test_raise_union_view_covers_every_committed_raise_union_key(pop):
    committed = json.loads((Path(__file__).resolve().parents[1] / ci.RAISE_UNION_JSON).read_text())
    counter, _ = run_counts(pop, per_source=False)
    view, originals = raise_union_view(counter.metrics)
    assert set(view) == set(committed["metrics"])
    assert set(originals) == set(committed["original_all_adults_strict"])
    for key, fields in committed["metrics"].items():
        assert set(view[key]) == set(fields), key
    assert ci.RAISE_KEYS == tuple(CHANGES) == RAISES


def write_scope(root, tag, states_by_part, outside_by_part, ranks=(1,), skip=None):
    """Job-entry plans and strictly valid pairs for one scope (tests/job_entry_pairs.py)."""
    offset = 0 if tag == "resolved" else 100
    for part in range(ci.PARTS):
        in_scope = states_by_part[part]
        n = sum(in_scope.values())
        write_plan(root, part, tag, {r: n if r == 1 else 0 for r in ranks}, in_scope, outside_by_part[part])
        if skip == part or not n:
            continue
        tested = []
        for state, k in sorted(in_scope.items()):
            for _ in range(k):
                i = offset + len(tested)
                tested.append({"person_index": i, "person_id": 1000 + i, "household_id": 500 + i, "state_code": state})
        assert install(root, make_pair(part=part, scope=tag, tested=tested,
                                       run_id=f"r{part}{tag.replace('-', '')}")).startswith(("wrote", "same"))


def test_coverage_defers_missing_and_partial_scopes_and_accepts_a_complete_later_scope(tmp_path):
    resolved = [{"CO": 2, "WA": 1}, {"CO": 1}, {"WA": 2}, {"CO": 1, "WA": 1}]
    md = [{"MD": 1}, {}, {"MD": 2}, {"MD": 1}]
    write_scope(tmp_path, "resolved", resolved, md)
    coverage, _ = ci.job_coverage(tmp_path)
    assert coverage["jurisdictions_covered"] == ["CO", "WA"]
    assert coverage["jurisdictions_deferred"] == {"MD": 4}
    assert coverage["status"] == ci.STATUS_PARTIAL
    # A later scope missing a part's rank is excluded and its state stays deferred.
    write_scope(tmp_path, "states-MD", [m or {} for m in md], resolved, skip=2)
    coverage, _ = ci.job_coverage(tmp_path)
    assert "states-MD" in coverage["scopes_excluded"]
    assert coverage["jurisdictions_deferred"] == {"MD": 4}
    # Once complete, it is picked up with no code change.
    write_scope(tmp_path, "states-MD", [m or {} for m in md], resolved)
    coverage, by_part = ci.job_coverage(tmp_path)
    assert coverage["jurisdictions_covered"] == ["CO", "MD", "WA"]
    assert coverage["jurisdictions_deferred"] == {}
    assert coverage["status"] == ci.STATUS_ALL
    assert coverage["expected_rows_by_part"]["2"] == {"MD": 2, "WA": 2}


def test_shipped_files_must_match_the_manifest(tmp_path):
    manifest = {"year": 2017, "parts": 4, "seed": 0, "code": {"commit": "c", "sha256": {}},
                "inputs": [{"part": 0, "name": "a", "sha256": sha256(b"x")}], "coverage": {}}
    manifest["digest"] = ci.manifest_digest(manifest)
    ci.check_files(manifest, 0, {"a": b"x"})
    with pytest.raises(ValueError, match="differs from its manifest hash"):
        ci.check_files(manifest, 0, {"a": b"y"})
    with pytest.raises(ValueError, match="differ from the manifest"):
        ci.check_files(manifest, 0, {})
    changed = dict(manifest, coverage={"x": 1})
    assert ci.manifest_digest(changed) != manifest["digest"]


def test_part_pairs_install_once_and_never_overwrite(tmp_path):
    npz = _npz([1], [[1.0]], ["a|households"])
    record = {"status": "complete", "part": 0, "digest": "d" * 64, "invariants": {"x": {"pass": True}},
              "per_source": {"file": f"{ci.OUT_BASE}/per_source/x_part_0_r1.npz", "sha256": sha256(npz)}}
    data = json.dumps(record).encode()
    rel = ci.part_json_rel("d" * 64, 0)
    assert ci.install_part_pair(tmp_path, rel, data, npz).startswith("wrote")
    assert ci.install_part_pair(tmp_path, rel, data, npz).startswith("same")
    assert ci.local_part(tmp_path, "d" * 64, 0) == record
    failing = dict(record, invariants={"x": {"pass": False}})
    with pytest.raises(ValueError, match="passing invariants"):
        ci.validate_part_pair(json.dumps(failing).encode(), npz)
    with pytest.raises(ValueError, match="SHA-256"):
        ci.validate_part_pair(data, npz + b"0")


def test_parts_add_left_to_right_as_the_raise_union_did():
    """Python 3.12+ sum() compensates exact floats; the raise union added numpy scalars plainly."""
    values = [6045189.590398442 / 4 + d for d in (0.1, 0.2, 0.3, 0.4)]
    plain = ((values[0] + values[1]) + values[2]) + values[3]
    assert add_in_order(values) == plain == sum(np.float64(v) for v in values)
    committed = json.loads((Path(__file__).resolve().parents[1] / ci.RAISE_UNION_JSON).read_text())
    records = [{"part": p["part"], "metrics": p["metrics"]} for p in reversed(committed["parts"])]
    assert add_part_metrics(records) == {k: dict(sorted(v.items())) for k, v in sorted(committed["metrics"].items())}


def test_scope_selection_leaves_unselected_scopes_deferred(tmp_path):
    resolved = [{"CO": 2, "WA": 1}, {"CO": 1}, {"WA": 2}, {"CO": 1, "WA": 1}]
    md = [{"MD": 1}, {}, {"MD": 2}, {"MD": 1}]
    write_scope(tmp_path, "resolved", resolved, md)
    write_scope(tmp_path, "states-MD", md, resolved)
    coverage, _ = ci.job_coverage(tmp_path, ["resolved"])
    assert coverage["scopes_excluded"] == {"states-MD": "states-MD: not selected for this run"}
    assert coverage["jurisdictions_deferred"] == {"MD": 4}
    assert ci.job_coverage(tmp_path)[0]["jurisdictions_deferred"] == {}


def _final_candidate():
    invariants = {"each_person_counted_once": {"pass_every_part": True},
                  "raise_union_reproduced": {"pass_every_part": True, "exact": True},
                  "national_counts": {"threshold_nesting_counts": True}}
    return {"coverage": {"jurisdictions_deferred": {}, "jurisdictions_covered": [f"S{i}" for i in range(51)]},
            "invariants": invariants, "reproduction": {"raise_union_exact": True}}


def test_final_status_needs_all_jurisdictions_every_invariant_and_an_exact_raise_union():
    assert final_status_problems(_final_candidate()) == []
    deferred = _final_candidate()
    deferred["coverage"]["jurisdictions_deferred"] = {"MD": 265}
    deferred["coverage"]["jurisdictions_covered"] = deferred["coverage"]["jurisdictions_covered"][:50]
    assert len(final_status_problems(deferred)) == 2
    failed = _final_candidate()
    failed["invariants"]["each_person_counted_once"]["pass_every_part"] = False
    failed["invariants"]["national_counts"]["threshold_nesting_counts"] = False
    assert [p.split(":")[0] for p in final_status_problems(failed)] == [
        "invariant each_person_counted_once", "invariant national_counts"]
    inexact = _final_candidate()
    inexact["invariants"]["raise_union_reproduced"]["exact"] = False
    inexact["reproduction"]["raise_union_exact"] = False
    assert len(final_status_problems(inexact)) == 2
