"""Calculate one exploratory hypothetical household curve with the released API.

Use the separate household-curves requirements, without this repository's older
project environment. Each process makes one API call. Full API receipts belong
outside the repository. The output includes noncash resources and excludes
health benefits; it is not a population estimate or a qualified paper figure.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path


ENTITY_KEYS = {
    "Person": "person",
    "MaritalUnit": "marital_unit",
    "Family": "family",
    "SPMUnit": "spm_unit",
    "TaxUnit": "tax_unit",
    "Household": "household",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def member_total(result: Mapping, variable: str, entity: str) -> list[float]:
    """Sum actual members of this one household, without survey weights."""
    groups = result[ENTITY_KEYS[entity]]
    groups = [groups] if isinstance(groups, Mapping) else groups
    vectors = [group[variable] for group in groups]
    require(bool(vectors), f"No native members for {variable}")
    for values in vectors:
        require(isinstance(values, list) and len(values) == 61, variable)
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in values),
            f"Nonfinite/non-numeric output: {variable}",
        )
    return [math.fsum(values[i] for values in vectors) for i in range(61)]


def check_identity(actual: list[float], expected: list[float], name: str) -> float:
    residual = max(abs(a - b) for a, b in zip(actual, expected, strict=True))
    require(residual <= 0.05, f"{name}: residual {residual} exceeds $0.05")
    return residual


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scenario", choices=("single_adult", "single_parent"))
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    require(args.scenario is not None, "Select exactly one household")
    require(not args.receipt.exists() and not args.csv.exists(), "Existing output")
    require(sys.flags.isolated == 1, "Run Python with -I")
    require(sys.version_info[:3] == (3, 14, 7), "Use the pinned Python3.14.7")
    require(
        "POLICYENGINE_US_DATA_MANIFEST_FILE" not in os.environ,
        "Custom data manifests are outside this analysis",
    )
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    require(config["schema_version"] == 1, "Unexpected configuration schema")
    versions = {name: metadata.version(name) for name in config["versions"]}
    require(versions == config["versions"], "Unexpected installed package versions")
    request = config["scenarios"][args.scenario]["request"]
    require(request["year"] == 2025 and "reform" not in request, "2025 baseline")
    require(len(request["axes"]) == 1, "Use one parallel axis group")
    require(
        [axis["count"] for axis in request["axes"][0]] == [61, 61],
        "Expected61 paired earnings/hour points",
    )

    import policyengine as pe

    # One genuine call per process, with no direct country imports or outputs
    # supplied as inputs. The native API owns calculation and entity mapping.
    result = pe.us.calculate_household(**request)
    columns = {
        name: member_total(result, name, entity)
        for name, entity in config["output_entities"].items()
    }
    earnings = [i * 1000 for i in range(61)]
    for i, person in enumerate(result["person"]):
        expected = earnings if i == 0 else [0] * 61
        for actual, target in zip(person["employment_income"], expected, strict=True):
            require(math.isclose(actual, target, abs_tol=0.01), "Earnings axis")
    hours = result["person"][0]["weekly_hours_worked_before_lsr"]
    for wage, hour in zip(earnings, hours, strict=True):
        require(
            math.isclose(hour, wage / (30 * 52), abs_tol=0.00001),
            "The two axes must zip61 points, rather than form a cross product",
        )
    residuals = {}
    for account, target in {
        "market_income": "household_market_income",
        "benefits": "household_benefits",
        "tax_before_refundable_credits": "household_tax_before_refundable_credits",
        "refundable_tax_credits": "household_refundable_tax_credits",
    }.items():
        component_sum = [
            math.fsum(columns[name][i] for name in config["accounts"][account])
            for i in range(61)
        ]
        residuals[account] = check_identity(columns[target], component_sum, account)
    expected_tax = [
        columns["household_tax_before_refundable_credits"][i]
        - columns["household_refundable_tax_credits"][i]
        for i in range(61)
    ]
    residuals["net_tax"] = check_identity(
        columns["household_tax"], expected_tax, "net tax"
    )
    expected_net = [
        columns["household_market_income"][i]
        + columns["household_benefits"][i]
        + columns["household_refundable_tax_credits"][i]
        - columns["household_tax_before_refundable_credits"][i]
        - columns["household_health_costs"][i]
        for i in range(61)
    ]
    residuals["net_resources"] = check_identity(
        columns["household_net_income"], expected_net, "net resources"
    )
    require(
        all(v == 0 for v in columns["household_health_costs"]),
        "Expected the unchanged health-excluded baseline",
    )
    spm = result["provenance"]["spm"]
    require(spm["geography_kind"] == "national", "Unexpected SPM geography")
    require(spm["scenario"] == "ce_trend", "Unexpected SPM scenario")
    require(set(spm["years"]) == {"2025"}, "Unexpected SPM measurement year")
    require(spm["forecast_sha256"] == config["spm_content_sha256"], "SPM hash")
    require(spm["runtime_versions"] == versions, "SPM package versions")
    receipt = {
        "classification": "EXPLORATORY_HYPOTHETICAL_HOUSEHOLD__NOT_PAPER_QUALIFIED",
        "completed_utc": datetime.now(UTC).isoformat(),
        "scenario": args.scenario,
        "year": 2025,
        "api_calls": 1,
        "axis_rows": 61,
        "versions": versions,
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "identity_max_abs_residual_USD": residuals,
        "result": result,
    }
    serialized = json.dumps(receipt, indent=2, allow_nan=False) + "\n"
    with args.receipt.open("x") as handle:
        handle.write(serialized)
    with args.csv.open("x", newline="") as handle:
        names = sorted(columns)
        writer = csv.DictWriter(handle, fieldnames=["scenario", "year", *names])
        writer.writeheader()
        for i in range(61):
            writer.writerow(
                {
                    "scenario": args.scenario,
                    "year": 2025,
                    **{name: columns[name][i] for name in names},
                }
            )
    print(
        json.dumps(
            {
                "scenario": args.scenario,
                "api_calls": 1,
                "axis_rows": 61,
                "identity_max_abs_residual_USD": residuals,
            }
        )
    )


if __name__ == "__main__":
    main()
