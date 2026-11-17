"""Tiny real-MicroSeries algebra tests, not model/data or5000-draw results."""

from types import SimpleNamespace

import pandas as pd
import pytest
from microdf import MicroSeries
from hypothesis import given, settings, strategies as st

from cliffs2017.commissioned import ContractError, PERSON_FLAG, RunSpec, _counts, run
from cliffs2017.paired_uncertainty import (
    HouseholdContributionSink,
    UncertaintyError,
    align_source_clusters,
    paired_cluster_bootstrap,
    totals_from_multiplicities,
)

KEY = ("1000", "0.60", "union", "households")


def test_invalid_sink_refuses_before_a_runtime_or_engine_is_requested():
    with pytest.raises(ContractError, match="must be callable"):
        run(RunSpec("toy"), None, contribution_sink=object())


def sink_fixture():
    index = pd.Index(["h1", "h2", "h3"])
    sink = HouseholdContributionSink(
        pd.Series([7, 7, 9], index=index),
        is_weighted=lambda value: isinstance(value, MicroSeries),
    )
    first = MicroSeries([1, 0, 1], weights=[2, 3, 5], index=index)
    second = MicroSeries([0, 1, 1], weights=[2, 3, 5], index=index)
    sink(KEY, first)
    sink(("1000", "0.60", "job", "households"), second)
    sink(("1000", "0.50", "same", "households"), first.copy())
    return sink, first, second


def test_public_weight_method_preserves_sums_and_applies_weights_once():
    sink, first, second = sink_fixture()
    totals = sink.cluster_totals()
    assert totals[KEY].tolist() == [2, 5]
    assert totals[KEY].sum() == first.sum() == 7
    assert totals[("1000", "0.60", "job", "households")].sum() == second.sum() == 8
    assert first.weight().tolist() == [2, 0, 5]
    assert sink.mapping_residuals().eq(0).all()
    first.iloc[0] = 0
    assert sink.cluster_totals()[KEY].sum() == 7  # independent captured copy


def test_cluster_alignment_keeps_legacy_role_clones_together_without_clone_index():
    table = pd.DataFrame(
        {
            "household_id": [11, 22, 33],
            "household_source_id": [7, 7, 9],
            "household_support_channel": [b"asec", b"puf_tax_detail", b"asec"],
            "household_support_clone_index": [0, 1, 0],
        }
    )
    labels = align_source_clusters(
        table, [33, 22, 11], pd.Index(["c", "b", "a"]), namespace="global_source_id"
    )
    assert labels.tolist() == [9, 7, 7]
    table["household_support_clone_index"] = [5, 8, 20]
    assert labels.equals(
        align_source_clusters(
            table, [33, 22, 11], labels.index, namespace="global_source_id"
        )
    )
    with pytest.raises(UncertaintyError, match="split clone siblings"):
        align_source_clusters(
            table, [11, 22, 33], labels.index, namespace="physical_channel_source_id"
        )


def test_explicit_physical_namespace_keeps_independent_source_id_collisions_separate():
    table = pd.DataFrame(
        {
            "household_id": [1, 2, 3],
            "household_source_id": [7, 7, 7],
            "household_support_channel": ["spine_a", "spine_a", "spine_b"],
        }
    )
    labels = align_source_clusters(
        table, [1, 2, 3], pd.RangeIndex(3), namespace="physical_channel_source_id"
    )
    assert labels.iloc[0] == labels.iloc[1] != labels.iloc[2]


@pytest.mark.parametrize("which", ["source", "native"])
def test_lineage_ids_do_not_silently_pass_through_float_encoding(which):
    table = pd.DataFrame(
        {
            "household_id": [1, 2],
            "household_source_id": [7, 8],
            "household_support_channel": ["spine_a", "spine_a"],
        }
    )
    ids = [1, 2]
    if which == "source":
        table["household_source_id"] = [7.0, 8.0]
    else:
        ids = [1.0, 2.0]
    with pytest.raises(UncertaintyError, match="integer encoding"):
        align_source_clusters(
            table, ids, pd.RangeIndex(2), namespace="global_source_id"
        )


@pytest.mark.parametrize("defect", ["missing", "different_cohort", "duplicate_id"])
def test_incomplete_lineage_is_not_replaced_by_row_independence(defect):
    table = pd.DataFrame(
        {
            "household_id": [1, 2],
            "household_source_id": [7, 8],
            "household_support_channel": ["spine_a", "spine_a"],
        }
    )
    ids = [1, 2]
    if defect == "missing":
        table.loc[0, "household_source_id"] = None
    elif defect == "different_cohort":
        ids = [1, 3]
    else:
        table.loc[1, "household_id"] = 1
    with pytest.raises(UncertaintyError):
        align_source_clusters(
            table, ids, pd.RangeIndex(2), namespace="global_source_id"
        )


def test_one_common_toy_draw_keeps_paired_clones_and_identical_metrics_together():
    sink, _, _ = sink_fixture()
    totals = sink.cluster_totals()
    counts = pd.DataFrame([[2, 0], [1, 1], [0, 2]], columns=totals.index)
    drawn = totals_from_multiplicities(totals, counts)
    assert drawn[KEY].tolist() == [4, 7, 10]
    assert drawn[("1000", "0.60", "job", "households")].tolist() == [6, 8, 10]
    assert (drawn[KEY] - drawn[("1000", "0.50", "same", "households")]).eq(0).all()
    # Non-nested scenario flags use the same resample, not an independence formula.
    assert (drawn[KEY] - drawn[("1000", "0.60", "job", "households")]).tolist() == [
        -2,
        -1,
        0,
    ]


class FixedToyDraws:
    def __init__(self):
        self.rows = [[2, 0], [1, 1], [1, 1], [0, 2]]
        self.offset, self.calls = 0, []

    def multinomial(self, groups, probabilities, *, size):
        assert groups == 2 and list(probabilities) == [0.5, 0.5]
        self.calls.append(size)
        result = self.rows[self.offset : self.offset + size]
        self.offset += size
        return result


def test_tiny_fixed_replicates_are_batch_invariant_and_preserve_original_points():
    sink, _, _ = sink_fixture()
    rng = FixedToyDraws()
    first = paired_cluster_bootstrap(
        sink.cluster_totals(),
        point_totals=sink.point_totals(),
        draws=4,
        batch_size=2,
        rng=rng,
    )
    second = paired_cluster_bootstrap(
        sink.cluster_totals(),
        point_totals=sink.point_totals(),
        draws=4,
        batch_size=3,
        rng=FixedToyDraws(),
    )
    assert rng.calls == [2, 2]  # common to all metric columns, not once per metric
    pd.testing.assert_frame_equal(first.replicates, second.replicates)
    assert first.summary.loc[KEY, "point"] == 7
    assert first.summary.loc[KEY, "bootstrap_se"] == pytest.approx(6**0.5)
    assert first.summary.loc[KEY, "lower_95"] == pytest.approx(4.225)
    assert first.summary.loc[KEY, "upper_95"] == pytest.approx(9.775)
    assert first.summary["cluster_sum_residual"].eq(0).all()


@pytest.mark.parametrize(
    "bad",
    [
        pd.DataFrame([[1.0, 1.0]], columns=[7, 9]),
        pd.DataFrame([[-1, 3]], columns=[7, 9]),
        pd.DataFrame([[0, 1]], columns=[7, 9]),
        pd.DataFrame([[1, 1]], columns=[9, 7]),
    ],
)
def test_incompatible_multiplicities_refuse_before_totals(bad):
    sink, _, _ = sink_fixture()
    with pytest.raises(UncertaintyError):
        totals_from_multiplicities(sink.cluster_totals(), bad)


def test_plain_unweighted_input_or_duplicate_metric_cannot_enter_the_sink():
    sink, first, _ = sink_fixture()
    with pytest.raises(UncertaintyError, match="unique"):
        sink(KEY, first)
    with pytest.raises(UncertaintyError, match="MicroSeries"):
        sink(("new", "0", "x", "members"), pd.Series([1, 0, 1], index=first.index))


class ToyMappingSimulation:
    """Three-person/two-household fake of the source-verified Core map_to API."""

    def __init__(self):
        self.original = MicroSeries([True, False, False], weights=[2, 2, 5])
        self.flag = self.original.copy()

    def set_input(self, name, period, flag):
        assert name == PERSON_FLAG and period == 2017
        self.flag = flag.copy()

    def delete_arrays(self, name, period):
        pass

    def calc(self, name, *, period, map_to=None):
        assert period == 2017
        assert name != "household_weight"
        if name == PERSON_FLAG:
            if map_to == "household":
                return MicroSeries(
                    [
                        int(self.flag.iloc[0]) + int(self.flag.iloc[1]),
                        int(self.flag.iloc[2]),
                    ],
                    weights=[2, 5],
                )
            return self.flag.copy()
        households = MicroSeries(
            [bool(self.flag.iloc[0] or self.flag.iloc[1]), bool(self.flag.iloc[2])],
            weights=[2, 5],
        )
        if map_to == "person":
            return MicroSeries(
                [households.iloc[0], households.iloc[0], households.iloc[1]],
                weights=[2, 2, 5],
            )
        return households


def test_count_sink_uses_household_mapping_and_restores_person_analysis_input():
    sim = ToyMappingSimulation()
    runtime = SimpleNamespace(is_weighted=lambda value: isinstance(value, MicroSeries))
    sink = HouseholdContributionSink(pd.Series([7, 9]), is_weighted=runtime.is_weighted)
    result = _counts(
        runtime,
        sim,
        sim.original,
        contribution_sink=sink,
        key=("1000", "0.60", "raise"),
    )
    assert result == {"adults": 2.0, "households": 2.0, "members": 4.0}
    assert sim.flag.equals(sim.original)
    for metric, point in result.items():
        key = ("1000", "0.60", "raise", metric)
        assert sink.point_totals()[key] == point
        assert sink.cluster_totals()[key].sum() == point


@st.composite
def integer_clone_ledgers_and_draws(draw):
    groups = draw(st.integers(min_value=2, max_value=4))
    sizes = [2] + draw(
        st.lists(st.integers(1, 3), min_size=groups - 1, max_size=groups - 1)
    )
    source_groups = [
        1000 + 17 * group for group, size in enumerate(sizes) for _ in range(size)
    ]
    count = len(source_groups)
    flags = draw(
        st.lists(
            st.tuples(st.integers(0, 1), st.integers(0, 1), st.integers(0, 9)),
            min_size=count,
            max_size=count,
        )
    )
    order = draw(st.permutations(tuple(range(count))))
    selections = draw(
        st.lists(
            st.lists(st.integers(0, groups - 1), min_size=groups, max_size=groups),
            min_size=1,
            max_size=4,
        )
    )
    return source_groups, flags, order, selections


@settings(max_examples=75, deadline=None, derandomize=True, database=None)
@given(integer_clone_ledgers_and_draws())
def test_generated_clone_ledger_matches_independent_integer_oracle(case):
    source_groups, flags, order, selections = case
    index = pd.Index([f"h{position}" for position in order])
    native_ids = [100 + 3 * position for position in order]
    source_table = pd.DataFrame(
        {
            "household_id": native_ids,
            "household_source_id": [source_groups[position] for position in order],
            "household_support_channel": [
                "asec" if position % 2 else "puf_tax_detail" for position in order
            ],
            "household_support_clone_index": list(range(len(order))),
        }
    ).iloc[::-1]
    clusters = align_source_clusters(
        source_table, native_ids, index, namespace="global_source_id"
    )
    sink = HouseholdContributionSink(
        clusters, is_weighted=lambda value: isinstance(value, MicroSeries)
    )
    first = MicroSeries(
        [flags[position][0] for position in order],
        weights=[flags[position][2] for position in order],
        index=index,
    )
    second = MicroSeries(
        [flags[position][1] for position in order],
        weights=[flags[position][2] for position in order],
        index=index,
    )
    duplicate_key = ("1000", "0.50", "identical", "households")
    second_key = ("1000", "0.60", "job", "households")
    sink(KEY, first)
    sink(duplicate_key, first.copy())
    sink(second_key, second)
    # Independent toy input oracle: plain integer products, no MicroSeries or
    # production groupby/dot/weight methods used to construct expected totals.
    expected = {}
    for position in order:
        group = source_groups[position]
        a, b, weight = flags[position]
        totals = expected.setdefault(group, [0, 0])
        totals[0] += a * weight
        totals[1] += b * weight
    totals = sink.cluster_totals()
    groups = list(expected)
    assert totals.index.tolist() == groups
    assert totals[KEY].tolist() == [expected[group][0] for group in groups]
    assert totals[second_key].tolist() == [expected[group][1] for group in groups]
    assert sink.point_totals()[KEY] == sum(a * weight for a, _, weight in flags)
    assert sink.mapping_residuals().eq(0).all()
    multiplicities = pd.DataFrame(
        [
            [selection.count(group) for group in range(len(groups))]
            for selection in selections
        ],
        columns=totals.index,
    )
    actual = totals_from_multiplicities(totals, multiplicities)
    expected_first = [
        sum(expected[groups[group]][0] for group in selection)
        for selection in selections
    ]
    expected_second = [
        sum(expected[groups[group]][1] for group in selection)
        for selection in selections
    ]
    assert actual[KEY].tolist() == expected_first
    assert actual[duplicate_key].tolist() == expected_first
    assert actual[second_key].tolist() == expected_second
