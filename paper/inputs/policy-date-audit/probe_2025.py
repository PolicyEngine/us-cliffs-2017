"""Reproduce the bounded 2025 parameter trace; persist metadata only.

Run through a suitable resource guard in the exact frozen simulation environment.
The portable adapter changes path discovery/output selection from the executed
probe. It does not change the model calls, sample, trace, or classification.
"""

import argparse
import os
from pathlib import Path


for key in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[key] = "1"

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    import hashlib
    import importlib.metadata
    import importlib.util
    import json
    import sys

    import numpy as np
    import policyengine_us
    from huggingface_hub import hf_hub_download
    from policyengine_core.parameters import ParameterNode
    from policyengine_us.data.dataset_schema import USSingleYearDataset

    expected_versions = {"policyengine-us": "2.116.0", "policyengine-core": "3.34.10"}
    for package, expected in expected_versions.items():
        assert importlib.metadata.version(package) == expected, package

    sys.path.insert(0, str(ROOT))
    from cliffs2017.medicaid import load_totals
    from cliffs2017.simulation import build_simulation

    spec = importlib.util.spec_from_file_location(
        "original_parameter_audit", ROOT / "scripts/audit_parameters.py"
    )
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    revision = "9a814a3b3b53c0ecd6e1737b6ec862c31300ef6f"
    path = hf_hub_download(
        "policyengine/populace-us",
        "populace_us_2024.h5",
        repo_type="dataset",
        revision=revision,
    )
    with Path(path).open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    assert digest == "6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
    raw_dataset = USSingleYearDataset(path)
    sample = audit.stratified(raw_dataset, 2, seed=0)
    del raw_dataset
    totals, meta = load_totals(ROOT / "results/medicaid/totals_2025_p4_s0.json")
    assert meta["sha256"] == "a4ffd77bec582f1f3ab11032b1fab419878c37fbdf89a10314a65dbfa65b787d"

    def make():
        return build_simulation(
            sample,
            2025,
            health=True,
            aca_before_2018=False,
            medicaid_totals=totals,
            leave_out_csfp=True,
        )

    with audit.traced_reads():
        sim = make()
        sim.trace = True
        recorder = audit.ParameterRecorder()
        sim.tracer = recorder
        traced = {
            name: np.asarray(sim.calculate(name, 2025).values)
            for name in ("is_on_cliff", "cliff_gap")
        }
    control = make()
    assert all(
        np.array_equal(values, np.asarray(control.calculate(name, 2025).values))
        for name, values in traced.items()
    ), "Tracer changed cliff flags/gaps"

    raw = ParameterNode(directory_path=Path(policyengine_us.__file__).parent / "parameters")
    rows = []
    for name, first_read in sorted(recorder.reads.items()):
        node = audit.raw_lookup(raw, name)
        if node is None:
            rows.append(
                {
                    "parameter": name,
                    "first_read": first_read,
                    "instants": sorted(recorder.instants[name]),
                    "status": "not in raw files",
                }
            )
            continue
        firsts = [
            leaf.values_list[-1].instant_str
            for leaf in audit.leaves(node)
            if leaf.values_list
        ]
        if not firsts:
            continue
        rows.append(
            {
                "parameter": name,
                "first_read": first_read,
                "instants": sorted(recorder.instants[name]),
                "earliest_raw_start": min(firsts),
                "latest_raw_start": max(firsts),
                "leaves": len(firsts),
                "leaves_after_jan2025": sum(value > "2025-01-01" for value in firsts),
                "leaves_after_dec2025": sum(value > "2025-12-31" for value in firsts),
                "leaves_after_first_read": sum(value > first_read for value in firsts),
                "status": "raw",
            }
        )
    raw_rows = [row for row in rows if row["status"] == "raw"]
    summary = {
        "sample_households": len(sample.household),
        "sample_people": len(sample.person),
        "states": int(sample.household.state_fips.nunique()),
        "traced_parameters": len(rows),
        "raw_parameters": len(raw_rows),
        "any_leaf_after_jan2025": sum(row["leaves_after_jan2025"] > 0 for row in raw_rows),
        "any_leaf_after_dec2025": sum(row["leaves_after_dec2025"] > 0 for row in raw_rows),
        "all_leaves_after_dec2025": sum(
            row["earliest_raw_start"] > "2025-12-31" for row in raw_rows
        ),
        "reads_after_dec2025": [
            row for row in rows if any(instant > "2025-12-31" for instant in row["instants"])
        ],
    }
    record = {
        "target": 2025,
        "summary": summary,
        "seed": 0,
        "households_per_state_max": 2,
        "source_dataset_revision": revision,
        "source_dataset_sha256": digest,
        "versions": expected_versions,
        "health": True,
        "aca_before_2018": False,
        "fixed_medicaid_totals_sha256": meta["sha256"],
        "leave_out_csfp": True,
        "wic_mapping": sim.stored_input_renames,
        "tracing_controls_equal": True,
        "rows": rows,
        "scope": "Parameter metadata only; no population weighting or impact totals.",
    }
    for filename, value in (
        ("policy-date-trace-2025.json", record),
        ("policy-date-trace-2025-summary.json", summary),
    ):
        (args.output / filename).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
