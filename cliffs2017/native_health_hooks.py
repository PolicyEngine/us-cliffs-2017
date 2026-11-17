"""Private driver hooks for the declared native2017/reference2025 experiment.

No engine or data imports occur here. Source proofs authenticate ordinary loaded
files; they do not attest adversarial Python mutation or certify the data pair.
The runtime owner supplies the real runtime observer and full reference cohort.
"""

import inspect
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from .government_transfer_account import (
    CASH_VARIABLE,
    GOVERNMENT_VARIABLE,
    AccountSpec,
    make_account_reform,
)
from .health_valuation import (
    HEALTH_INPUTS,
    HEALTH_OUTPUTS,
    REFERENCE_READS,
    ReferenceHealthCapture,
    make_health_valuation_reform,
    make_reference_health_unit_reform,
)
from .native_materializer import input_digest, verify_frozen_irmaa
from .native_witness import (
    CORE_METHODS,
    FORBIDDEN_INPUTS,
    IRMAA_INPUT,
    FixedInput,
    LiveContextWitness,
    VariableExpectation,
    WitnessError,
    _array_signature,
    _composition,
    _value,
)
from .reference_benchmark_prices import make_reference_benchmark_reform

REFERENCE_ORIGINALS = (
    "medicaid_cost_if_enrolled",
    "per_capita_chip",
    "medicare_gross_cost",
)
NATIVE_ORIGINALS = (
    "base_part_a_premium",
    "base_part_b_premium",
    "gross_medicare_part_b_premium",
    "gross_medicare_part_b_premium_if_enrolled",
    "income_adjusted_part_d_premium_surcharge",
    IRMAA_INPUT,
)
PARAMETER_WATCH = (
    ("gov.aca.state_rating_area_cost", "2025-01-01"),
    ("gov.aca.lcbp.state_rating_area_cost", "2025-01-01"),
    ("gov.hhs.medicare.part_a.full_premium", "2017-01-01"),
    ("gov.hhs.medicare.part_a.reduced_premium", "2017-01-01"),
    ("gov.hhs.medicare.part_a.premium_free_quarters_threshold", "2017-01-01"),
    ("gov.hhs.medicare.part_a.reduced_premium_quarters_threshold", "2017-01-01"),
    ("gov.hhs.medicare.part_b.base_premium", "2017-01-01"),
    ("calibration.gov.hhs.medicare.part_d.enrollment_share", "2017-01-01"),
    ("calibration.gov.hhs.medicare.part_d.premiums_per_enrollee", "2017-01-01"),
    ("gov.simulation.medicare_irmaa_uses_current_year_income", "2017-01-01"),
)


def load_core_readers(*, simulation_type=None, holder_type=None):
    """Load maintained Core methods only after the owner admits the runtime.

    Pure tests inject both deliberate doubles. Production omits both arguments;
    the source-qualified setup then authenticates every returned function.
    """
    if (simulation_type is None) != (holder_type is None):
        raise WitnessError("Supply both explicit doubles or the maintained Core types")
    if simulation_type is None:
        from policyengine_core.holders.holder import Holder
        from policyengine_core.simulations.simulation import Simulation

        simulation_type, holder_type = Simulation, Holder
    readers = {
        "get_holder": simulation_type.get_holder,
        "get_array": holder_type.get_array,
        "get_known_periods": holder_type.get_known_periods,
    }
    inputs = {name: getattr(simulation_type, name) for name in CORE_METHODS}
    return readers, inputs


def _source(function, proof):
    """Check one caller-pinned original source file, never a data payload."""
    if not callable(function):
        raise WitnessError("The expected original formula is missing")
    source = inspect.getsourcefile(function)
    _source_file(source, proof, {".py"})
    return function


def _source_file(source, proof, suffixes):
    suffix, expected = proof
    if source is None or not str(source).endswith(suffix):
        raise WitnessError("Loaded function does not match its source path")
    path = Path(source)
    if path.suffix not in suffixes or sha256(path.read_bytes()).hexdigest() != expected:
        raise WitnessError("Loaded original source bytes differ")


def _bound(instance, name, expected):
    method = getattr(instance, name, None)
    if (
        getattr(method, "__self__", None) is not instance
        or getattr(method, "__func__", None) is not expected
    ):
        raise WitnessError("The source-bound Core method changed")


def _fixed(simulation, item):
    periods = [
        p for p in simulation._get_set_input_periods(item.name) if str(p) == item.period
    ]
    if len(periods) != 1 or str(periods[0].unit).lower() != "year":
        raise WitnessError("The fixed annual input no longer survives")
    actual = simulation._get_recorded_input_array(item.name, periods[0])
    if _array_signature(actual) != item.signature:
        raise WitnessError("The fixed input changed")


def _leaves(node):
    children = getattr(node, "children", None)
    if isinstance(children, Mapping):
        for child in children.values():
            yield from _leaves(child)
    elif hasattr(node, "brackets"):
        for bracket in node.brackets:
            yield from _leaves(bracket)
    else:
        yield node


GENERATED_ZERO_ROOTS = frozenset(
    {"gov.aca.state_rating_area_cost", "gov.aca.lcbp.state_rating_area_cost"}
)


def _parameter_homogenizer():
    # Loaded only inside the already-admitted engine phase, never at module import.
    from policyengine_core.parameters.operations.homogenize_parameters import (
        homogenize_parameter_node,
    )

    return homogenize_parameter_node


def _generated_zero_leaf(system, root, node, leaf):
    """Recognize only Core3.36's missing ACA breakdown zero declaration.

    The root YAML and maintained homogenizer are authenticated by the caller.
    This recognizes ordinary processed source provenance, not adversarial mutation.
    """
    if root not in GENERATED_ZERO_ROOTS or node.metadata.get("breakdown") != [
        "state_code",
        "range(1, 68)",
    ]:
        raise WitnessError("Missing parameter source is not a selected ACA breakdown")
    prefix = root + "."
    parts = leaf.name[len(prefix) :].split(".") if leaf.name.startswith(prefix) else []
    states = {item.name for item in system.variables["state_code"].possible_values}
    if (
        len(parts) != 2
        or parts[0] not in states
        or parts[1] not in {str(area) for area in range(1, 68)}
    ):
        raise WitnessError("The generated ACA leaf name differs from its breakdown")
    history = leaf.values_list
    if not history or not {"0000-01-01", "2040-01-01"}.issubset(
        {item.instant_str for item in history}
    ):
        raise WitnessError("The generated ACA leaf lacks Core's zero-history sentinels")
    for item in history:
        _value(item.value)
        if isinstance(item.value, bool) or item.value != 0:
            raise WitnessError("The generated ACA leaf has a nonzero history")


def _parameter_watch(system, proofs):
    result = {}
    checked = set()
    homogenizer_checked = False
    for root, instant in PARAMETER_WATCH:
        node = system.parameters.get_child(root)
        # A single YAML owns each selected root, including generated descendants.
        _source_file(node.file_path, proofs[root], {".yaml", ".yml"})
        checked.add((root, node.file_path))
        for leaf in _leaves(node):
            source = leaf.file_path
            if source is None:
                if not homogenizer_checked:
                    _source(_parameter_homogenizer(), proofs["parameter_homogenizer"])
                    homogenizer_checked = True
                _generated_zero_leaf(system, root, node, leaf)
            elif (root, source) not in checked:
                _source_file(source, proofs[root], {".yaml", ".yml"})
                checked.add((root, source))
            value = leaf.get_at_instant(instant)
            _value(value)  # Same finite/primitive convention as the live witness.
            if source is None and (isinstance(value, bool) or value != 0):
                raise WitnessError("The generated ACA leaf no longer evaluates to zero")
            result[leaf.name, instant] = value
    if not result:
        raise WitnessError("The selected price/premium watch set is empty")
    return result


def _variable_expectations(system, names, period):
    return tuple(
        VariableExpectation(
            name,
            period,
            system.variables[name].get_formula(period),
            system.variables[name].entity.key,
            str(system.variables[name].definition_period).lower(),
            value_type=system.variables[name].value_type,
            adds=system.variables[name].adds,
            subtracts=system.variables[name].subtracts,
            defined_for=system.variables[name].defined_for,
        )
        for name in sorted(names)
    )


def _check_definitions(system, expected, original_objects):
    for item in expected:
        variable = system.variables.get(item.name)
        if (
            variable is not original_objects[item.name]
            or variable.get_formula(item.period) is not item.formula
            or variable.entity.key != item.entity
            or str(variable.definition_period).lower() != item.definition_period
            or variable.value_type is not item.value_type
            or _composition(variable.adds) != item.adds
            or _composition(variable.subtracts) != item.subtracts
            or variable.defined_for != item.defined_for
            or variable.is_neutralized
        ):
            raise WitnessError("A source-bound prepared definition changed")


class ReferenceHealthSetup:
    """Callbacks for the existing once-prepared full reference constructor."""

    def __init__(
        self,
        *,
        expected_runtime,
        observe_runtime,
        person_count,
        source_proofs,
        core_readers,
    ):
        if expected_runtime.versions.get("policyengine-core") != "3.36.0" or set(
            core_readers
        ) != {"get_holder", "get_array", "get_known_periods"}:
            raise WitnessError("Bind the source-qualified Core3.36 reference readers")
        self.runtime, self.observe_runtime = expected_runtime, observe_runtime
        self.person_count, self.proofs = person_count, dict(source_proofs)
        self.readers = dict(core_readers)
        self.capture, self.system, self.origin_system = None, None, None
        self.variables, self.variable_objects = (), {}
        for name, function in self.readers.items():
            _source(function, self.proofs[name])

    def _runtime(self):
        if self.observe_runtime() != self.runtime:
            raise WitnessError(
                "Actual runtime/source differs from the selected binding"
            )

    def prepare_system(self, system):
        self._runtime()
        if self.origin_system is not None:
            raise WitnessError("Own exactly one reference system")
        _source(make_reference_health_unit_reform, self.proofs["health_valuation"])
        formulas = {
            name: _source(system.variables[name].get_formula("2025"), self.proofs[name])
            for name in REFERENCE_ORIGINALS
        }
        system.apply_reform_set(
            make_reference_health_unit_reform(
                chip_formula=formulas["per_capita_chip"],
                medicare_gross_formula=formulas["medicare_gross_cost"],
            )
        )
        selected = {
            name: system.variables[name].get_formula("2025")
            for name in REFERENCE_READS.values()
        }
        self.capture = ReferenceHealthCapture(
            reference_formulas=selected, person_count=self.person_count
        )
        self.variables = _variable_expectations(
            system, REFERENCE_READS.values(), "2025"
        )
        self.variable_objects = MappingProxyType(
            {item.name: system.variables[item.name] for item in self.variables}
        )
        self.origin_system = system
        return system

    def capture_reference(self, simulation):
        self._runtime()
        if self.origin_system is None or self.capture is None:
            raise WitnessError("The prepared reference system is missing")
        if self.system is not None and simulation.tax_benefit_system is not self.system:
            raise WitnessError("The managed reference constructor changed systems")
        # US SPM shares a private policy copy with the same registered variables.
        # Authenticate that finite prepared set before binding its final system.
        _check_definitions(
            simulation.tax_benefit_system, self.variables, self.variable_objects
        )
        if list(simulation.dataset.years) != [2024, 2025]:
            raise WitnessError("The maintained source/reference years differ")
        # Core retains the multi-year container's first-year default. Every
        # health formula/cache query below remains explicitly reference2025.
        self.observed_default_calculation_period = str(
            simulation.default_calculation_period
        )
        _bound(simulation, "get_holder", self.readers["get_holder"])
        for name in REFERENCE_READS.values():
            holder = simulation.get_holder(name)
            for method in ("get_array", "get_known_periods"):
                _bound(holder, method, self.readers[method])
        self.capture(simulation)
        self.system = simulation.tax_benefit_system

    @property
    def anchor_digest(self):
        if self.capture is None:
            raise WitnessError("The actual reference capture is missing")
        receipt = self.capture.receipt
        # Native installation adds fields later. Bind the immutable reference
        # signatures plus the fixed conversion convention before AccountSpec.
        original = {
            key: receipt[key]
            for key in (
                "reference_year",
                "person_count",
                "reference_signatures",
                "zero_unit_cells",
            )
        }
        return input_digest(
            {
                "reference": original,
                "native_factor": (245120, 321943),
                "native_encoding": "float64_then_actual_Core_dtype",
            }
        )


class _HealthLiveWitness(LiveContextWitness):
    def __call__(self, simulation):
        if any(simulation._get_set_input_periods(name) for name in HEALTH_OUTPUTS):
            raise WitnessError(
                "A supplied health output would override its account formula"
            )
        return super().__call__(simulation)


class NativeHealthHooks:
    """Actual pre-freeze checks, then the full post-freeze live witness."""

    def __init__(self, *, reference, account_spec, core_methods, source_proofs):
        if (
            not isinstance(account_spec, AccountSpec)
            or account_spec.health_price_anchor_sha256 != reference.anchor_digest
        ):
            raise WitnessError(
                "Bind AccountSpec to the actual reference anchor receipt"
            )
        if (
            account_spec.runtime_identity_sha256
            != reference.runtime.source_receipt_sha256
        ):
            raise WitnessError("The account and reference runtime identities differ")
        if not HEALTH_OUTPUTS.issubset(account_spec.nonptc_government_health):
            raise WitnessError(
                "The account must include the three native health values"
            )
        if {"medicaid_cost", "chip", "medicare_cost", "medicare_gross_cost"} & set(
            account_spec.nonptc_government_health
        ):
            raise WitnessError("Do not duplicate replaced health components")
        if set(core_methods) != CORE_METHODS:
            raise WitnessError("Bind the actual Core input-provenance methods")
        self.reference, self.spec = reference, account_spec
        self.methods, self.proofs = dict(core_methods), dict(source_proofs)
        for name, function in self.methods.items():
            _source(function, self.proofs[name])
        self.context = MappingProxyType(
            {
                "law_year": 2017,
                "reporting_year": 2025,
                **{
                    name: getattr(account_spec, name)
                    for name in (
                        "runtime_identity_sha256",
                        "reference_preparation_sha256",
                        "health_price_anchor_sha256",
                        "price_basis_sha256",
                        "component_ledger_sha256",
                    )
                },
                "native_price_factor": (245120, 321943),
            }
        )
        self.system, self.origin_system = None, None
        self.variables, self.variable_objects = (), {}
        self.parameters, self.fixed = {}, ()

    def prepare_system(self, system):
        self.reference._runtime()
        if self.origin_system is not None:
            raise WitnessError("Own exactly one native system")
        for name in NATIVE_ORIGINALS:
            _source(system.variables[name].get_formula("2017"), self.proofs[name])
        for function, key in (
            (make_account_reform, "government_transfer_account"),
            (make_reference_benchmark_reform, "reference_benchmark_prices"),
            (make_health_valuation_reform, "health_valuation"),
        ):
            _source(function, self.proofs[key])
        system.apply_reform_set(
            (
                make_account_reform(self.spec),
                make_reference_benchmark_reform(),
                make_health_valuation_reform(),
            )
        )
        names = {
            CASH_VARIABLE,
            GOVERNMENT_VARIABLE,
            "slcsp_age_0",
            "lcbp_age_0",
            *HEALTH_INPUTS,
            *HEALTH_OUTPUTS,
            *NATIVE_ORIGINALS,
        }
        self.variables = _variable_expectations(system, names, "2017")
        self.variable_objects = MappingProxyType(
            {item.name: system.variables[item.name] for item in self.variables}
        )
        self.parameters = _parameter_watch(system, self.proofs)
        self.origin_system = system
        return system

    def prepare_health(self, simulation):
        if self.system is not None or self.origin_system is None or self.fixed:
            raise WitnessError("Install once on the owned native system")
        # Validate definitions/parameters before any health input installation.
        self._prepared_state(simulation)
        self.system = simulation.tax_benefit_system
        self.fixed = self.reference.capture.prepare_health(simulation)
        if simulation.tax_benefit_system is not self.system:
            raise WitnessError("The native system changed during health installation")
        return self.fixed

    def _prepared_state(self, simulation):
        self.reference._runtime()
        if (
            self.origin_system is None
            or str(simulation.default_calculation_period) != "2017"
        ):
            raise WitnessError("Native source/clock setup is incomplete")
        if self.spec.health_price_anchor_sha256 != self.reference.anchor_digest:
            raise WitnessError("The reference anchor identity changed")
        for name, method in self.methods.items():
            _bound(simulation, name, method)
        if any(
            simulation._get_set_input_periods(name)
            for name in FORBIDDEN_INPUTS | HEALTH_OUTPUTS
        ):
            raise WitnessError(
                "A supplied derived price/account/health output overrides formulas"
            )
        _check_definitions(
            simulation.tax_benefit_system, self.variables, self.variable_objects
        )
        for (path, instant), expected in self.parameters.items():
            if _value(
                simulation.tax_benefit_system.parameters.get_child(path).get_at_instant(
                    instant
                )
            ) != _value(expected):
                raise WitnessError(
                    "A selected reference-price/native-premium leaf changed"
                )

    def pre_freeze_context(self, simulation):
        if simulation.tax_benefit_system is not self.system or not self.fixed:
            raise WitnessError("Native source/clock/health setup is incomplete")
        self._prepared_state(simulation)
        for item in self.fixed:
            _fixed(simulation, item)
        return self.context

    def witness_builder(self, simulation, health_fixed_inputs, irmaa_receipt):
        if tuple(health_fixed_inputs) != self.fixed:
            raise WitnessError("The bridge supplied different health expectations")
        verify_frozen_irmaa(
            simulation,
            irmaa_receipt,
            expected_context=self.context,
            observe_context=self.pre_freeze_context,
        )
        periods = [
            p
            for p in simulation._get_set_input_periods(IRMAA_INPUT)
            if str(p) == "2017"
        ]
        if len(periods) != 1:
            raise WitnessError("The actual frozen prior-MAGI input is missing")
        array = simulation._get_recorded_input_array(IRMAA_INPUT, periods[0])
        irmaa = FixedInput.from_array(
            IRMAA_INPUT, "2017", "tax_unit", "frozen_irmaa", array
        )
        result = _HealthLiveWitness(
            self.context,
            core_version="3.36.0",
            core_methods=self.methods,
            variables=self.variables,
            parameters=self.parameters,
            fixed_inputs=(*self.fixed, irmaa),
        )
        result(simulation)
        return result
