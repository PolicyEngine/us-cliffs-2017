"""Run one engineering-only earnings experiment through the managed public API.

Use the separate released-wrapper requirements lock, not this repository's
legacy project environment. The execution manifest supplies local cache and
source seals; the portable inputs describe the experiment. Output belongs in a
private run directory and contains scalar engineering diagnostics only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from importlib import metadata
from pathlib import Path


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_seals(rows):
    for row in rows:
        require(
            digest(row["path"]) == row["sha256"], "Source seal changed: " + row["path"]
        )


def native_periods(definition, years):
    if definition == "year":
        return years
    if definition == "month":
        return [f"{year}-{month:02}" for year in years for month in range(1, 13)]
    if definition == "eternity":
        return [years[-1]]
    raise RuntimeError("Unsupported primitive definition period: " + definition)


def run(inputs, execution, inputs_path):
    require(
        sys.version_info[:3] == tuple(inputs["python_version"]), "Interpreter mismatch"
    )
    require(
        Path.cwd().resolve() == Path(execution["working_directory"]).resolve(),
        "Managed-cache cwd mismatch",
    )
    require(digest(inputs_path) == execution["inputs_sha256"], "Inputs changed")
    verify_seals(execution["source_seals"])
    for package, expected in inputs["versions"].items():
        require(
            metadata.version(package) == expected,
            "Installed version mismatch: " + package,
        )
    project = inputs_path.resolve().parents[1]
    require(
        digest(project / inputs["requirements_lock"])
        == inputs["requirements_lock_sha256"],
        "Requirements lock changed",
    )
    cache = Path(execution["managed_cache"])
    require(cache.is_file() and not cache.is_symlink(), "Missing regular managed cache")
    require(digest(cache) == inputs["dataset_sha256"], "Managed cache hash mismatch")

    import policyengine as pe
    from microdf import MicroSeries
    from policyengine.core.scoping_strategy import RowFilterStrategy

    def checked(series, reference=None):
        require(isinstance(series, MicroSeries), "Financial result lost MicroSeries")
        if reference is not None:
            require(series.index.equals(reference.index), "Entity indexes do not align")
            require(len(series) == len(reference), "Entity lengths differ")
        return series

    def calculate(simulation, variable, period, entity="person"):
        return checked(simulation.calc(variable, period=period, map_to=entity))

    def finite(series):
        require(math.isfinite(float(series.min(skipna=False))), "Nonfinite minimum")
        require(math.isfinite(float(series.max(skipna=False))), "Nonfinite maximum")

    def within(series, tolerance, label):
        checked(series)
        finite(series)
        require((series <= tolerance).all() and (series >= -tolerance).all(), label)
        return max(
            abs(float(series.min(skipna=False))), abs(float(series.max(skipna=False)))
        )

    certificate = pe.us.model.data_certification.model_dump(mode="json")
    require(
        certificate["compatibility_basis"] == "exact_build_model_version",
        "Normal certificate missing",
    )
    require(
        certificate["certified_for_model_version"]
        == inputs["versions"]["policyengine-us"],
        "Certificate model mismatch",
    )
    require(
        certificate["data_build_id"] == inputs["build_id"], "Certificate build mismatch"
    )
    print(
        json.dumps({"phase": "managed_constructor_start", "application_calls": 1}),
        flush=True,
    )
    sim = pe.us.managed_microsimulation(
        dataset=inputs["dataset"],
        spm={"geography_kind": "national"},
        scoping_strategy=RowFilterStrategy(
            variable_name="state_fips", variable_value=11
        ),
    )
    years = sorted(int(year) for year in sim.dataset.datasets)
    require(years == inputs["expected_native_years"], "Native horizon changed")
    bundle = sim.policyengine_bundle
    require(
        bundle["legacy_input_renames"]
        == {"would_claim_wic": "takes_up_wic_if_eligible"},
        "WIC input mapping changed",
    )
    scope = bundle["scoping"]
    require(
        scope["method"] == "native_projected_history_row_filter",
        "Scoping method changed",
    )
    require(
        scope["strategy"]["variable_name"] == "state_fips"
        and scope["strategy"]["variable_value"] == 11,
        "DC selector changed",
    )
    require(
        sorted(int(year) for year in scope["years"]) == years, "Missing scoped history"
    )
    reference_ids = scope["years"][str(years[0])]["id_sha256"]
    require(
        all(
            scope["years"][str(scope_year)]["id_sha256"] == reference_ids
            for scope_year in years
        ),
        "Cohort changes across years",
    )
    year = inputs["year"]
    require(
        scope["years"][str(year)]["scoped_rows"] == inputs["expected_rows"],
        "Closed cohort counts changed",
    )
    require(
        sim.spm_config["geography_kind"] == "national"
        and sim.spm_config["scenario"] == "ce_trend"
        and sim.spm_config["forecast_content_sha256"] == inputs["spm_content_sha256"],
        "SPM context mismatch",
    )
    require(
        not sim.tax_benefit_system.parameters(
            f"{year}-01-01"
        ).gov.simulation.include_health_benefits_in_net_income,
        "Health inclusion changed",
    )

    wages0 = calculate(sim, "employment_income_before_lsr", year).copy(deep=True)
    final_wages0 = calculate(sim, "employment_income", year).copy(deep=True)
    net0 = calculate(sim, "household_net_income", year).copy(deep=True)
    age = checked(calculate(sim, "age", year), wages0)
    rank = checked(calculate(sim, "adult_earnings_index", year), wages0)
    ids0 = {
        name: calculate(sim, name, year).copy(deep=True)
        for name in inputs["identity_variables"]
    }
    require((ids0["state_fips"] == 11).all(), "Non-DC person in cohort")
    target = checked((age >= 18) & (rank == 1) & (wages0 > 0), wages0)
    require(target.any(), "No targets for the declared selection")
    require(
        ids0["household_id"][target].is_unique,
        "Two increments would enter one household",
    )
    require(
        len(target) == inputs["expected_rows"]["person"],
        "Target population length changed",
    )

    snapshots = {}
    for name in sim.get_input_variables(include_computed_variables=False):
        variable = sim.tax_benefit_system.get_variable(name, check_existence=True)
        if variable.unit != "currency-USD":
            continue
        for period in native_periods(
            str(variable.definition_period), inputs["primitive_check_years"]
        ):
            if name == "employment_income_before_lsr" and period == year:
                continue
            snapshots[name, period, variable.entity.key] = calculate(
                sim, name, period, variable.entity.key
            ).copy(deep=True)
    require(snapshots, "No primitive monetary input guards")
    for row in inputs["participation_inputs"]:
        variable = sim.tax_benefit_system.get_variable(
            row["variable"], check_existence=True
        )
        require(
            variable.is_input_variable(), "Participation preference became a formula"
        )
        require(
            str(variable.definition_period) == row["period"],
            "Participation period changed",
        )
        require(variable.entity.key == row["entity"], "Participation entity changed")
        for period in native_periods(row["period"], [year]):
            snapshots[row["variable"], period, row["entity"]] = calculate(
                sim, row["variable"], period, row["entity"]
            ).copy(deep=True)

    baseline_components = {
        name: checked(calculate(sim, name, year), net0).copy(deep=True)
        for name in inputs["resource_components"]
    }
    for name in inputs["zero_response_variables"]:
        within(
            checked(calculate(sim, name, year), wages0),
            0,
            "Baseline response/health value is nonzero: " + name,
        )
    branch_name = "wage1000_" + execution["run_id"]
    require(branch_name not in sim.branches, "Counterfactual branch already exists")
    print(
        json.dumps(
            {
                "phase": "counterfactual_start",
                "target_rows_unweighted": len(wages0[target]),
                "primitive_snapshot_periods": len(snapshots),
            }
        ),
        flush=True,
    )
    alt = sim.get_branch(branch_name, clone_system=False)
    raised = checked(wages0 + target * inputs["earnings_increment"], wages0)
    alt.set_input("employment_income_before_lsr", year, raised)
    net1 = checked(calculate(alt, "household_net_income", year), net0)
    final_wages1 = checked(calculate(alt, "employment_income", year), final_wages0)
    expected_shock = checked(target * inputs["earnings_increment"], wages0)
    realized_shock = checked(final_wages1 - final_wages0, wages0)
    shock_error = within(
        realized_shock - expected_shock,
        inputs["earnings_absolute_tolerance"],
        "Realized earnings shock differs from the declared target",
    )
    require(
        calculate(sim, "employment_income_before_lsr", year).equals(wages0),
        "Original primitive wages changed",
    )
    require(
        calculate(sim, "employment_income", year).equals(final_wages0),
        "Original final wages changed",
    )
    require(
        calculate(sim, "household_net_income", year).equals(net0),
        "Original net resources changed",
    )
    for name, original in ids0.items():
        require(
            calculate(alt, name, year).equals(original),
            "Identity/geography changed: " + name,
        )
    for (name, period, entity), original in snapshots.items():
        require(
            calculate(alt, name, period, entity).equals(original),
            "Unrelated primitive/takeup input changed: " + name + " " + str(period),
        )
        require(
            calculate(sim, name, period, entity).equals(original),
            "Original input changed: " + name + " " + str(period),
        )
    for name in inputs["zero_response_variables"]:
        within(
            checked(calculate(alt, name, year), wages0),
            0,
            "Counterfactual response/health value is nonzero: " + name,
        )
    alternate_components = {
        name: checked(calculate(alt, name, year), net1)
        for name in inputs["resource_components"]
    }

    def accounting(components, net):
        reconstructed = (
            components["household_market_income"]
            + components["household_benefits"]
            + components["household_refundable_tax_credits"]
            - components["household_tax_before_refundable_credits"]
            - components["household_health_costs"]
        )
        tolerance = inputs["accounting_absolute_tolerance"] + inputs[
            "accounting_relative_tolerance"
        ] * ((net * net) ** 0.5)
        return reconstructed, within(
            reconstructed - net, tolerance, "Resource accounting identity failed"
        )

    reconstructed0, residual0 = accounting(baseline_components, net0)
    reconstructed1, residual1 = accounting(alternate_components, net1)
    change = checked(net1 - net0, net0)
    delta_tolerance = 2 * inputs["accounting_absolute_tolerance"] + inputs[
        "accounting_relative_tolerance"
    ] * (((net0 * net0) ** 0.5) + ((net1 * net1) ** 0.5))
    delta_error = within(
        change - (reconstructed1 - reconstructed0),
        delta_tolerance,
        "Resource-change decomposition failed",
    )
    target_changes = checked(change[target])
    finite(target_changes)
    negative = checked(target_changes < 0, target_changes)
    verify_seals(execution["source_seals"])
    require(
        digest(inputs_path) == execution["inputs_sha256"], "Inputs changed during run"
    )
    require(
        digest(cache) == inputs["dataset_sha256"], "Managed cache changed during run"
    )
    return {
        "classification": "ENGINEERING_ONLY_NOT_A_POPULATION_OR_PAPER_ESTIMATE",
        "status": "ONE_EARNINGS_RAISE_TRIAL_COMPLETED",
        "selection": inputs["selection_name"],
        "year": year,
        "application_managed_constructor_calls": 1,
        "application_counterfactual_branches": 1,
        "caller_primitive_overrides": [
            {"variable": "employment_income_before_lsr", "year": year}
        ],
        "cohort_rows_unweighted": inputs["expected_rows"],
        "target_rows_unweighted": len(target_changes),
        "negative_resource_change_rows_unweighted": len(target_changes[negative]),
        "guard_metrics_USD": {
            "maximum_earnings_shock_error": shock_error,
            "baseline_resource_identity_maximum_error": residual0,
            "alternate_resource_identity_maximum_error": residual1,
            "resource_change_decomposition_maximum_error": delta_error,
        },
        "guards": {
            "MicroSeries_and_alignment": True,
            "one_increment_per_household": True,
            "realized_shock_only_on_target": True,
            "zero_labor_response_and_health_values": True,
            "original_wages_and_net_unchanged": True,
            "identities_and_geography_unchanged": True,
            "unrelated_monetary_and_participation_inputs_unchanged": True,
            "resource_accounting": True,
            "source_input_and_cache_seals_unchanged": True,
        },
        "primitive_snapshot_periods_checked": len(snapshots),
        "participation_variables_checked": len(inputs["participation_inputs"]),
        "data_certificate": certificate,
        "policyengine_bundle": bundle,
        "spm_configuration": sim.spm_config,
        "inputs_sha256": execution["inputs_sha256"],
        "requirements_lock_sha256": inputs["requirements_lock_sha256"],
        "limits": inputs["claims_limits"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text())
    execution = json.loads(args.execution_manifest.read_text())
    require(
        args.output.resolve().parent == Path(execution["output_directory"]).resolve(),
        "Private output directory mismatch",
    )
    require(not args.output.exists(), "Refuse a repeated native attempt")
    result = run(inputs, execution, args.inputs)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {"status": result["status"], "classification": result["classification"]}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
