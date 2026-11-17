"""Compose native input, account and scenario APIs without defining policy rules.

Importing this module loads no model or data. A native caller supplies authenticated
source/runtime preparations; synthetic providers do not qualify those preparations.
"""

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from .commissioned import Runtime, install_analysis_variables
from .government_transfer_account import AccountSpec, GovernmentTransferAccount
from .managed_native import PacketPlan, RuntimeBinding, construct_managed_native
from .native_materializer import (
    WrittenDataset,
    freeze_baseline_irmaa,
    verify_frozen_irmaa,
)
from .native_witness import LiveContextWitness, reject_declared_price_inputs


class BridgeError(ValueError):
    """An actual preparation capability or experiment invariant is missing."""


@dataclass(frozen=True)
class NativeInputs:
    plan: PacketPlan
    written: WrittenDataset
    read_packet: Callable


@dataclass(frozen=True)
class NativeTools:
    """Maintained native surfaces, supplied after runtime source authentication."""

    managed_constructor: Callable
    system_constructor: Callable
    model_api: object
    create_branch: Callable
    split_raise: Callable
    is_weighted: Callable


def load_maintained_tools():
    """Late-import the managed engine and source-bound country branch helpers.

    The caller authenticates these installed sources before calling this function.
    Only pe.us.managed_microsimulation constructs an engine here. The country
    class constructs its fresh tax-benefit system, not a direct Microsimulation.
    """
    import policyengine as pe
    from microdf import MicroSeries
    from policyengine_us import CountryTaxBenefitSystem, model_api
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
        earnings_increments,
    )

    return NativeTools(
        pe.us.managed_microsimulation,
        CountryTaxBenefitSystem,
        model_api,
        create_perturbed_branch,
        earnings_increments,
        lambda value: isinstance(value, MicroSeries),
    )


def make_native_runtime(
    *,
    prepared_inputs,
    tools,
    expected_runtime,
    observe_runtime,
    account_spec,
    bindings,
    spm,
    prepare_system,
    prepare_health,
    pre_freeze_context,
    witness_builder,
    audit_facts,
    hourly_wages_real,
    mode="native",
    earnings_tolerance=0,
    resource_tolerance=0,
):
    """Build one scenario Runtime from explicit source-owned capabilities.

    prepared_inputs() returns NativeInputs made by the maintained materializer.
    prepare_system(system) returns that fresh system with final account/price
    definitions. prepare_health(sim) installs the actual fixed health unit values.
    pre_freeze_context(sim) authenticates setup before IRMAA is frozen;
    witness_builder(sim, health_fixed_inputs, irmaa_receipt) returns the live witness.
    audit_facts checks prepared topology, weights, draws and allowed earnings.
    hourly_wages_real(sim, is_weighted=..., period=2017) already returns weighted
    real2025 dollars/hour, so it receives no additional conversion here.
    """
    if (
        not isinstance(tools, NativeTools)
        or not isinstance(account_spec, AccountSpec)
        or not isinstance(expected_runtime, RuntimeBinding)
    ):
        raise BridgeError("Supply actual native tools, account and runtime binding")
    providers = {
        "prepared inputs": prepared_inputs,
        "runtime observer": observe_runtime,
        "final system/account/price setup": prepare_system,
        "health unit anchor preparation": prepare_health,
        "pre-freeze context observer": pre_freeze_context,
        "live witness builder": witness_builder,
        "prepared-facts audit": audit_facts,
        "real2025 hourly wage provider": hourly_wages_real,
    }
    providers.update(
        {
            name: getattr(tools, name)
            for name in (
                "managed_constructor",
                "system_constructor",
                "create_branch",
                "split_raise",
                "is_weighted",
            )
        }
    )
    missing = [name for name, callback in providers.items() if not callable(callback)]
    if missing:
        raise BridgeError("Missing actual capability: " + ", ".join(missing))
    if mode not in {"native", "synthetic_test"}:
        raise BridgeError("Declare native or explicitly synthetic execution")
    if account_spec.runtime_identity_sha256 != expected_runtime.source_receipt_sha256:
        raise BridgeError("Account and actual runtime source differ")
    context = MappingProxyType(
        {
            "law_year": 2017,
            "reporting_year": 2025,
            "runtime_identity_sha256": account_spec.runtime_identity_sha256,
            "reference_preparation_sha256": account_spec.reference_preparation_sha256,
            "health_price_anchor_sha256": account_spec.health_price_anchor_sha256,
            "price_basis_sha256": account_spec.price_basis_sha256,
            "component_ledger_sha256": account_spec.component_ledger_sha256,
            "native_price_factor": (
                account_spec.native_per_reference_dollar.numerator,
                account_spec.native_per_reference_dollar.denominator,
            ),
        }
    )
    state = {"attempted": False, "simulation": None, "witness": None, "irmaa": None}

    def context_for(sim):
        if state["witness"] is None:
            raise BridgeError("The actual native preparation has not completed")
        actual = state["witness"](sim)
        if actual != context:
            raise BridgeError("The current native account/price state changed")
        return actual

    def factory():
        if state["attempted"]:
            raise BridgeError("This Runtime already owns its one prepared baseline")
        state["attempted"] = True
        inputs = prepared_inputs()
        if not isinstance(inputs, NativeInputs) or not callable(inputs.read_packet):
            raise BridgeError("Actual materialized native inputs are missing")
        plan, written = inputs.plan, inputs.written
        if not isinstance(plan, PacketPlan) or not isinstance(written, WrittenDataset):
            raise BridgeError("Use the maintained packet/materializer outputs")
        reject_declared_price_inputs(plan.arrays)
        if (
            plan.native_price_factor != account_spec.native_per_reference_dollar
            or plan.contract_sha256 != account_spec.reference_preparation_sha256
        ):
            raise BridgeError("Input preparation/currency differs from the account")
        status = written.receipt.get("status")
        expected_status = (
            "PRIVATE_NATIVE_INPUT_ARTIFACT_NOT_CERTIFIED"
            if mode == "native"
            else "SYNTHETIC_SERIALIZER_DOUBLE_NOT_A_DATASET"
        )
        if status != expected_status:
            raise BridgeError("A synthetic or unbound artifact cannot become native")

        def final_system(**kwargs):
            return prepare_system(tools.system_constructor(**kwargs))

        def managed(**kwargs):
            sim = tools.managed_constructor(**kwargs)
            health_fixed_inputs = prepare_health(sim)
            irmaa = freeze_baseline_irmaa(
                sim, expected_context=context, observe_context=pre_freeze_context
            )
            witness = witness_builder(sim, health_fixed_inputs, irmaa)
            if mode == "native" and not isinstance(witness, LiveContextWitness):
                raise BridgeError("Use the source-bound live native witness")
            if not callable(witness) or not callable(getattr(witness, "audit", None)):
                raise BridgeError("The actual live witness is missing")
            state["witness"], state["irmaa"] = witness, irmaa
            context_for(sim)
            return sim

        try:
            sim = construct_managed_native(
                plan,
                path=written.receipt["path"],
                dataset_sha256=written.receipt["sha256"],
                expected_runtime=expected_runtime,
                observe_runtime=observe_runtime,
                managed_constructor=managed,
                system_constructor=final_system,
                spm=spm,
                read_packet=inputs.read_packet,
                role_transport=written.receipt["role_transport"],
                context_receipts={
                    name: context[name]
                    for name in (
                        "runtime_identity_sha256",
                        "reference_preparation_sha256",
                        "health_price_anchor_sha256",
                        "price_basis_sha256",
                        "component_ledger_sha256",
                    )
                },
                observe_context=context_for,
            )
        except BaseException:
            state["witness"], state["irmaa"] = None, None
            raise
        state["simulation"] = sim
        return sim

    def install(sim):
        context_for(sim)
        install_analysis_variables(sim.tax_benefit_system, tools.model_api)
        context_for(sim)

    def create_branch(sim, period, name, changes):
        if sim is not state["simulation"] or name in sim.branches:
            raise BridgeError("Create only a new owned branch of this baseline")
        try:
            branch = tools.create_branch(sim, period, name, changes)
            if sim.branches.get(name) is not branch:
                raise BridgeError("The maintained helper returned a different branch")
            return branch
        except BaseException:
            # Runtime.run releases successful zero/raise/job branches in finally.
            # Release a partially created owned name too; preserve every other name.
            sim.branches.pop(name, None)
            raise

    def audit(baseline, branch, selected):
        state["witness"].audit(baseline, branch, selected)
        for sim in (baseline, branch):
            if sim is not None:
                verify_frozen_irmaa(
                    sim,
                    state["irmaa"],
                    expected_context=context,
                    observe_context=context_for,
                )
        if audit_facts(baseline, branch, selected) is False:
            raise BridgeError("Prepared population/input preservation failed")

    factor = float(account_spec.native_per_reference_dollar)
    runtime = Runtime(
        factory=factory,
        install=install,
        is_weighted=tools.is_weighted,
        create_branch=create_branch,
        split_raise=tools.split_raise,
        to_native=lambda value: value * factor,
        to_reference=lambda value: value / factor,
        account=GovernmentTransferAccount(account_spec, context_for),
        context_for=context_for,
        hourly_wages_real=lambda sim: hourly_wages_real(
            sim, is_weighted=tools.is_weighted, period=2017
        ),
        audit=audit,
        expected_context=context,
        bindings=MappingProxyType(dict(bindings)),
        mode=mode,
        earnings_tolerance=earnings_tolerance,
        resource_tolerance=resource_tolerance,
    )
    runtime.validate()
    return runtime
