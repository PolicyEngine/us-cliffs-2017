"""Private engineering pilot: one full-reference baseline and one raise branch.

Importing this file loads no model or data. The admitted worker supplies exact
source/runtime contracts. Only aggregate receipts leave its private directory.
This pilot supplies no commissioned estimates or scientific qualification.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from .commissioned import (
    _context,
    _earnings,
    _maximum,
    _project,
    _rank,
    _resources,
    _series,
)
from .native_materializer import input_digest

SCHEMA = "native-health-pilot-v1"
RAISE_REAL = 1000
FACTOR = Fraction(245120, 321943)
FCC_PATHS = tuple(
    f"gov.fcc.{program}.amount.{kind}"
    for program in ("acp", "ebb")
    for kind in ("standard", "tribal")
)
EGRESS = frozenset(
    {
        "pilot-result.json",
        "reference-health-receipt.json",
        "native-controls.json",
        "native-input-receipt.json",
        "native-context.json",
        "audit.json",
        "stage-events.jsonl",
    }
)


class PilotError(ValueError):
    """A bounded pilot contract or observed invariant failed."""


def _json(path, value):
    """Write only caller-constructed aggregate metadata, never engine objects."""
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise PilotError("Nonfinite aggregate")
    return result


class Events:
    def __init__(self, path):
        self.path = Path(path)
        self.stage = "initialization"
        with self.path.open("x"):
            pass

    def __call__(self, stage):
        # Stage names are constant source literals, never engine messages.
        self.stage = stage
        with self.path.open("a") as stream:
            stream.write(
                json.dumps(
                    {"stage": stage, "utc": datetime.now(timezone.utc).isoformat()}
                )
                + "\n"
            )


@contextmanager
def private_native_logs(directory):
    """Redirect OS descriptors too: native/logging output cannot become egress."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, exist_ok=False)
    saved = (os.dup(1), os.dup(2))
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        with (directory / "native.stdout").open("xb") as out:
            with (directory / "native.stderr").open("xb") as err:
                os.dup2(out.fileno(), 1)
                os.dup2(err.fileno(), 2)
                yield
    finally:
        # Flush Python buffers while their file descriptors still point inside
        # private/. Otherwise buffered native/logging text could escape later.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            for target, descriptor in zip((1, 2), saved, strict=True):
                os.dup2(descriptor, target)
                os.close(descriptor)


def make_fcc_2017_reform(*, reform_type=None):
    """Only four annual2017 cap inputs change; formulas/future caps survive."""
    if reform_type is None:
        from policyengine_core.reforms import Reform

        reform_type = Reform

    class FCC2017StudyCorrection(reform_type):
        def apply(self):
            self.modify_parameters({path: {"2017": 0} for path in FCC_PATHS})

    return FCC2017StudyCorrection


def prepare_fcc_system(system, proofs):
    """Authenticate selected source leaves before this explicit study reform."""
    for path in FCC_PATHS:
        leaf = system.parameters.get_child(path)
        suffix, expected = proofs[path]
        source = Path(leaf.file_path)
        if not str(source).endswith(suffix) or _sha(source) != expected:
            raise PilotError("FCC original cap source changed")
    system.apply_reform_set(make_fcc_2017_reform())
    for path in FCC_PATHS:
        if system.parameters.get_child(path).get_at_instant("2017-01-01") != 0:
            raise PilotError("FCC2017 study cap correction was not installed")
    return system


def _fcc_zero(runtime, sim):
    for name in ("acp", "ebb"):
        result = _series(runtime, sim.calc(name, period=2017, map_to="household"))
        if not (result == 0).all():
            raise PilotError("FCC2017 output was not zero")


def run_raise_pilot(runtime, audit, *, events):
    """Exercise native interfaces; retain strict precision refusal as evidence.

    Select rank1 among working adults in each household, using maintained
    analysis mapping and country earnings increments. No job scenarios run.
    """
    runtime.validate()
    events("native_baseline")
    sim = runtime.factory()
    _context(runtime, sim)
    runtime.install(sim)
    _, earnings = _earnings(runtime, sim)
    age = _series(runtime, sim.calc("age", period=2017))
    workers = (age >= 18) & (earnings > 0)
    rank, _ = _rank(runtime, sim, workers)
    selected = workers & (rank == 1)
    touched_hh, touched = _project(runtime, sim, selected)
    if not selected.any():
        raise PilotError("No working adult was available for the raise pilot")
    if len(selected[selected]) != len(touched_hh[touched_hh]):
        raise PilotError("Rank selection was not one adult per household")
    audit.snapshot_pilot(sim, selected)
    runtime.audit(sim, None, selected)
    base = _resources(runtime, sim)
    base_hh = _series(runtime, runtime.account(sim, period=2017, map_to="household"))
    _fcc_zero(runtime, sim)
    branch_name = "cliffs_pilot_raise_1000_rank1"
    if branch_name in sim.branches:
        raise PilotError("Pilot branch already exists")
    gross = selected * RAISE_REAL
    changes = runtime.split_raise(sim.person, 2017, runtime.to_native(gross))
    branch = None
    events("native_raise")
    try:
        branch = runtime.create_branch(sim, 2017, branch_name, changes)
        runtime.audit(sim, branch, selected)
        changed = _resources(runtime, branch)
        changed_hh = _series(
            runtime, runtime.account(branch, period=2017, map_to="household")
        )
        _fcc_zero(runtime, branch)
        difference = _series(runtime, changed - base)
        untouched_error = _maximum(difference[~touched])
        if untouched_error != 0:
            raise PilotError("Untouched household resources changed")
        _, after = _earnings(runtime, branch)
        actual = _series(runtime, runtime.to_reference(after - earnings))
        selected_error = _maximum((actual - gross)[selected])
        unselected_error = _maximum(actual[~selected])
        if unselected_error != 0:
            raise PilotError("Unselected member earnings changed")
        # The audit owns actual raw input target/cast and ULP observations.
        precision = audit.precision_report
        if precision.get("status") not in {"EXACT", "precision_refused"}:
            raise PilotError("Raw input precision audit did not complete")
        runtime.audit(sim, branch, selected)
        result = {
            "status": "engineering_controls_passed"
            if selected_error == 0 and precision["status"] == "EXACT"
            else "precision_refused",
            "qualification": "engineering_diagnostic_only_not_scientific_results",
            "law_year": 2017,
            "reporting_year": 2025,
            "raise_real_2025": RAISE_REAL,
            "selected_sample_adults": len(selected[selected]),
            "selected_sample_households": len(touched_hh[touched_hh]),
            "selected_weighted_adults": _number(selected.sum()),
            "selected_weighted_households": _number(touched_hh.sum()),
            "baseline_household_resources_real_2025": _number(base_hh.sum()),
            "raise_household_resources_real_2025": _number(changed_hh.sum()),
            "intended_selected_earnings_increment_real_2025": RAISE_REAL,
            "selected_earnings_increment_max_deviation_real_2025": selected_error,
            "untouched_household_resources_max_deviation_real_2025": untouched_error,
            "unselected_member_earnings_max_deviation_real_2025": unselected_error,
            "precision_tolerance_adopted": 0,
            "FCC2017_acp_ebb_zero": True,
            "precision": precision,
        }
    finally:
        if branch_name in sim.branches:
            del sim.branches[branch_name]
    runtime.audit(sim, None, selected)
    return sim, result


def assemble_and_run(config, output, events):
    """Assemble real maintained constructors only inside an admitted worker."""
    from .government_transfer_account import AccountSpec
    from .managed_input_contract import build_managed_input_contract
    from .native_currency import PriceBasis
    from .native_health_hooks import (
        NativeHealthHooks,
        ReferenceHealthSetup,
        load_core_readers,
    )
    from .native_materializer import (
        FROZEN_IRMAA_STRATEGY,
        compile_native_plan,
        prepare_reference_once,
        write_native_dataset,
    )
    from .native_observers import load_native_observers
    from .native_runtime import NativeInputs, load_maintained_tools, make_native_runtime

    def document(key):
        record = config["files"][key]
        if _sha(record["path"]) != record["sha256"]:
            raise PilotError("Admitted source/config bytes changed")
        return json.loads(Path(record["path"]).read_text())

    events("runtime_and_contract")
    declaration, metadata = document("input_contract"), document("input_metadata")
    contract, specs, registry = build_managed_input_contract(
        declaration, actual_metadata=metadata
    )
    # Importing the maintained country installs its supported Social Security
    # compatibility wrappers. Capture those actual method objects afterward.
    tools = load_maintained_tools()
    readers, methods = load_core_readers()
    from policyengine_core.holders.holder import Holder

    audit = load_native_observers(
        config,
        contract=contract,
        specs=specs,
        registry=registry,
        tools=tools,
        core_methods=methods,
        holder_to_array=Holder._to_array,
    )
    expected_runtime = audit.expected_runtime
    health_proofs = document("health_source_proofs")
    fcc_proofs = document("fcc_source_proofs")
    reference = ReferenceHealthSetup(
        expected_runtime=expected_runtime,
        observe_runtime=audit.observe_runtime,
        person_count=contract.entity_counts["person"],
        source_proofs=health_proofs,
        core_readers=readers,
    )

    def reference_system(**kwargs):
        return reference.prepare_system(tools.system_constructor(**kwargs))

    def capture_reference(sim):
        reference.capture_reference(sim)

    events("reference_preparation_and_health_capture")
    values, fixed_facts, receipt = prepare_reference_once(
        managed_constructor=tools.managed_constructor,
        system_constructor=reference_system,
        source_path=config["dataset_path"],
        observe_source=audit.observe_source,
        spm=config["spm"],
        registry=registry,
        contract=contract,
        archival_inputs={},
        expected_context=audit.expected_reference_context,
        observe_context=audit.observe_reference,
        capture_reference=capture_reference,
    )
    price_basis = document("price_basis")
    if price_basis["index_by_year"] != {"2017": "245.120", "2025": "321.943"}:
        raise PilotError("Published currency inputs differ")
    basis = PriceBasis(
        {
            int(year): Fraction(value)
            for year, value in price_basis["index_by_year"].items()
        }
    )
    contract_sha = input_digest(declaration)
    plan = compile_native_plan(
        values,
        contract=contract,
        basis=basis,
        specs=specs,
        fixed_facts=fixed_facts,
        reference_receipt=receipt,
        contract_sha256=contract_sha,
        role_keys=audit.role_keys,
        required_history=(FROZEN_IRMAA_STRATEGY,),
    )
    audit.bind_native(plan)
    events("private_native_packet")
    written = write_native_dataset(
        plan,
        output / "private" / "native_inputs.h5",
        serializer_source_sha256=audit.serializer_source_sha256,
        observe_serializer=audit.observe_serializer,
    )
    ledger = document("ledger")
    spec = AccountSpec(
        nonhealth_benefits=tuple(ledger["nonhealth_benefits"]),
        nonptc_government_health=tuple(ledger["nonptc_government_health"]),
        runtime_identity_sha256=expected_runtime.source_receipt_sha256,
        reference_preparation_sha256=contract_sha,
        health_price_anchor_sha256=reference.anchor_digest,
        price_basis_sha256=config["files"]["price_basis"]["sha256"],
    )

    class PilotHealthHooks(NativeHealthHooks):
        def prepare_system(self, system):
            prepare_fcc_system(system, fcc_proofs)
            result = super().prepare_system(system)
            self.parameters.update({(path, "2017-01-01"): 0 for path in FCC_PATHS})
            return result

    hooks = PilotHealthHooks(
        reference=reference,
        account_spec=spec,
        core_methods=methods,
        source_proofs=health_proofs,
    )
    controls = {
        "source_country_commit": expected_runtime.country_commit,
        "explicit_study_reform": "FCC2017_four_cap_zero_only",
        "zero_paths": list(FCC_PATHS),
        "zero_period": "2017",
        "source_proofs_sha256": config["files"]["fcc_source_proofs"]["sha256"],
        "IRMAA": FROZEN_IRMAA_STRATEGY,
        "currency_factor": [FACTOR.numerator, FACTOR.denominator],
        "scope": "full_reference_health_capture_one_baseline_one_rank1_raise",
    }
    bindings = audit.bindings(receipt, spec, written, controls)

    def read_packet(path):
        if Path(path) != Path(written.receipt["path"]):
            raise PilotError("Native packet path differs")
        return _sha(path), written.dataset.load_dataset()

    runtime = make_native_runtime(
        prepared_inputs=lambda: NativeInputs(plan, written, read_packet),
        tools=tools,
        expected_runtime=expected_runtime,
        observe_runtime=audit.observe_runtime,
        account_spec=spec,
        bindings=bindings,
        spm=config["spm"],
        prepare_system=hooks.prepare_system,
        prepare_health=hooks.prepare_health,
        pre_freeze_context=hooks.pre_freeze_context,
        witness_builder=hooks.witness_builder,
        audit_facts=audit.audit_facts,
        hourly_wages_real=lambda sim, **kwargs: (_ for _ in ()).throw(
            PilotError("Job wages are outside this raise-only pilot")
        ),
    )
    sim, result = run_raise_pilot(runtime, audit, events=events)
    events("final_live_audit")
    _context(runtime, sim)
    health_receipt = dict(reference.capture.receipt)
    health_receipt["observed_reference_container_default"] = (
        reference.observed_default_calculation_period
    )
    health_receipt["health_read_period"] = "2025"
    _json(output / "reference-health-receipt.json", health_receipt)
    _json(output / "native-controls.json", controls)
    _json(output / "native-input-receipt.json", dict(written.receipt))
    _json(output / "native-context.json", dict(runtime.context_for(sim)))
    _json(output / "audit.json", audit.aggregate_receipt())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    events = Events(output / "stage-events.jsonl")
    result = None
    code = 1
    try:
        config = json.loads(Path(args.config).read_text())
        if (
            config.get("schema_version") != SCHEMA
            or config.get("raise_real_2025") != RAISE_REAL
        ):
            raise PilotError("Unsupported pilot configuration")
        # Root's cloud controller authenticates its source/resource admission.
        # The concrete helper observes installed runtime and source state.
        with private_native_logs(output / "private"):
            result = assemble_and_run(config, output, events)
        code = 0 if result["status"] == "engineering_controls_passed" else 3
    except BaseException as error:
        # Full messages/tracebacks stay private. Egress frames contain no source
        # lines, messages, locals, engine reprs, rows or member IDs.
        private = output / "private"
        private.mkdir(mode=0o700, exist_ok=True)
        with (private / "failure.traceback").open("x") as stream:
            traceback.print_exception(error, file=stream)
        result = {
            "status": "interrupted"
            if isinstance(error, KeyboardInterrupt)
            else "refused",
            "stage": events.stage,
            "exception_type": type(error).__name__,
            "frames": [
                {"file": frame.filename, "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)
            ],
            "qualification": "not_qualified",
        }
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
    _json(output / "pilot-result.json", result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
