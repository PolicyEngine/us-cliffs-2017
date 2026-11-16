"""Identities, counterexamples and bootstrap properties for saved robustness."""

import numpy as np
import pandas as pd
import pytest
from microdf import MicroSeries

from scripts.driver_intervals import resample
from scripts.ijm_saved_robustness import (
    cap_thread_limits,
    component_checks,
    resource_change,
    scenario_flag,
    verified_input,
    weighted_cluster_outputs,
)


def component_frame():
    # Cash delta=1000; PTC=-100, Medicaid=-300, CHIP=-50,
    # CHIP premium=-10 and marketplace-net-premium contribution=-100.
    return pd.DataFrame(
        {
            "d_household_market_income": [1000.0],
            "d_assigned_aca_ptc": [-100.0],
            "d_medicaid_cost": [-300.0],
            "d_chip": [-50.0],
            "d_chip_premium": [-10.0],
            "d_marketplace_net_premium": [-100.0],
            "d_parts": [440.0],
            "d_net": [440.125],
            "d_net_single_ptc": [540.125],
            "d_net_without_health": [1000.0],
        }
    )


def test_value_endpoints_preserve_ptc_premiums_and_native_residual():
    frame = component_frame()
    health = [
        "d_assigned_aca_ptc",
        "d_medicaid_cost",
        "d_chip",
        "d_chip_premium",
        "d_marketplace_net_premium",
    ]
    audit = component_checks(frame, health)
    assert audit["ptc_once_identity_max_abs"] == 0
    assert audit["cash_component_identity_max_abs"] == 0
    assert audit["parts_sum_identity_max_abs"] == 0
    assert audit["native_net_minus_parts_max_abs"] == 0.125
    assert resource_change(frame, "full").tolist() == [540.125]
    assert resource_change(frame, "cash").tolist() == [1000.0]
    # Alpha zero removes only the specified benefit values. PTC, premium,
    # and native residual keep their coefficients and are not cash endpoint.
    assert resource_change(frame, "medicaid_a0").tolist() == [840.125]
    assert resource_change(frame, "medicaid_chip_a0").tolist() == [890.125]
    assert resource_change(frame, "medicaid_chip_a0.5").tolist() == [715.125]


def test_bad_shared_ptc_identity_is_rejected():
    frame = component_frame()
    frame["d_net_single_ptc"] += 1
    with pytest.raises(ValueError, match="accounting identities"):
        component_checks(
            frame,
            [
                "d_assigned_aca_ptc",
                "d_medicaid_cost",
                "d_chip",
                "d_chip_premium",
                "d_marketplace_net_premium",
            ],
        )


def test_downweighting_a_coverage_gain_can_create_a_new_cliff():
    frame = pd.DataFrame(
        {"d_net_single_ptc": [100.0], "d_medicaid_cost": [1000.0], "d_chip": [0.0]}
    )
    assert resource_change(frame, "full")[0] > 0
    assert resource_change(frame, "medicaid_chip_a0")[0] < 0


def test_worker_classification_is_invariant_to_saved_row_order():
    frame = pd.DataFrame(
        {
            "person_index": [0, 2],
            "change": [1000.0, 1000.0],
            "worker": [True, False],
            "d_net_single_ptc": [-100.0, -100.0],
        }
    )
    original = scenario_flag(frame, frame.d_net_single_ptc, 0, "current_workers", 3)
    reordered = frame.iloc[::-1]
    actual = scenario_flag(
        reordered, reordered.d_net_single_ptc, 0, "current_workers", 3
    )
    assert original.tolist() == [True, False, False]
    assert np.array_equal(actual, original)


def test_duplicate_source_copies_share_one_bootstrap_draw():
    outcomes = MicroSeries([1, 1, 0], weights=[2, 3, 7])
    cluster = weighted_cluster_outputs(outcomes, [10, 10, 20], [10, 20])
    assert type(cluster) is pd.Series
    assert cluster.tolist() == [5, 0]
    draws = resample(cluster.to_numpy()[:, None], draws=2000, seed=0)[:, 0]
    # Two source households are sampled. Both copies of source 10 move as
    # one $5 aggregate, rather than being resampled as independent records.
    assert set(draws) == {0, 5, 10}
    assert draws.mean() == pytest.approx(5, abs=0.25)


def test_paired_bootstrap_retains_covariance_for_identical_counts():
    stats = np.array([[5.0, 5.0], [0.0, 0.0]])
    draws = resample(stats, draws=200, seed=3)
    assert np.array_equal(draws[:, 0] - draws[:, 1], np.zeros(200))


def test_zero_clusters_remain_in_sampling_universe():
    outcomes = MicroSeries([False, False], weights=[2, 3])
    result = weighted_cluster_outputs(outcomes, [10, 10], [10, 20, 30])
    assert result.index.tolist() == [10, 20, 30]
    assert result.tolist() == [0, 0, 0]


def test_public_input_requires_exact_bytes(monkeypatch, tmp_path):
    import scripts.ijm_saved_robustness as module

    path = tmp_path / "input.h5"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download", lambda *args, **kwargs: str(path)
    )
    monkeypatch.setattr(module, "SOURCE_BYTES", 4)
    monkeypatch.setattr(module, "SOURCE_SHA256", module.sha256(path))
    _, evidence = verified_input()
    assert evidence["bytes"] == 4
    path.write_bytes(b"abce")
    with pytest.raises(ValueError, match="H5 bytes differ"):
        verified_input()


def test_thread_cap_preserves_existing_one_thread_limit():
    environment = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "8"}
    limits = cap_thread_limits(environment)
    assert limits["OMP_NUM_THREADS"] == 1
    assert environment["OMP_NUM_THREADS"] == "1"
    assert limits["OPENBLAS_NUM_THREADS"] == 2
    assert limits["VECLIB_MAXIMUM_THREADS"] == 2
    with pytest.raises(ValueError, match="nonnumeric"):
        cap_thread_limits({"OMP_NUM_THREADS": "4,2"})
