"""Check declared native experiment state without calculating or changing it.

The caller supplies source-qualified expectations. This witness checks benign
branch integrity; it does not attest arbitrary Python execution or certify data.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from .government_transfer_account import CASH_VARIABLE, GOVERNMENT_VARIABLE
from .reference_benchmark_prices import FORBIDDEN_STORED_PRICE_INPUTS

IRMAA_INPUT = "medicare_irmaa_magi_two_years_prior"
FORBIDDEN_INPUTS = FORBIDDEN_STORED_PRICE_INPUTS | {CASH_VARIABLE, GOVERNMENT_VARIABLE}
REQUIRED_VARIABLES = frozenset(
    {CASH_VARIABLE, GOVERNMENT_VARIABLE, "slcsp_age_0", "lcbp_age_0"}
)
CORE_METHODS = frozenset({"_get_set_input_periods", "_get_recorded_input_array"})
CONTEXT_DIGESTS = (
    "runtime_identity_sha256",
    "reference_preparation_sha256",
    "health_price_anchor_sha256",
    "price_basis_sha256",
    "component_ledger_sha256",
)
_UNSET = object()


class WitnessError(ValueError):
    """Actual state differs from a declared experiment expectation."""


def reject_declared_price_inputs(arrays):
    """Check decoded input names before serialization or construction."""
    if not isinstance(arrays, Mapping):
        raise WitnessError("An explicit input mapping is required")
    if FORBIDDEN_INPUTS.intersection(arrays):
        raise WitnessError(
            "A supplied derived price or account would override formulas"
        )


def _value(value):
    if type(value) in (list, tuple):
        return tuple(_value(item) for item in value)
    if type(value) not in (str, bool, int, float, type(None)):
        raise WitnessError("Declare primitive parameter values")
    if type(value) is float and not math.isfinite(value):
        raise WitnessError("Nonfinite parameter value")
    return type(value).__name__, value


def _composition(value):
    return tuple(value) if isinstance(value, (tuple, list)) else value


def _array_signature(array):
    if array is None:
        raise WitnessError("A fixed supplied input is missing")
    try:
        shape = tuple(array.shape)
        dtype = array.dtype
        values = array.tolist()
        data = array.tobytes(order="C")
    except (AttributeError, TypeError, ValueError) as error:
        raise WitnessError("An explicit typed input array is required") from error
    if len(shape) != 1 or shape[0] <= 0 or dtype.kind not in "biuf":
        raise WitnessError("Fixed inputs require a nonempty numeric vector")
    if len(values) != shape[0] or any(
        type(item) not in (bool, int, float) or not math.isfinite(item)
        for item in values
    ):
        raise WitnessError("Fixed input values must be finite and match their shape")
    return str(dtype.str), shape, sha256(data).hexdigest()


@dataclass(frozen=True)
class VariableExpectation:
    name: str
    period: str
    formula: object
    entity: str
    definition_period: str
    value_type: type = float
    adds: object = None
    subtracts: object = None
    defined_for: object = _UNSET

    def __post_init__(self):
        if not self.name or not self.period or not self.entity:
            raise WitnessError("Declare the variable, period and entity")
        if self.formula is not None and not callable(self.formula):
            raise WitnessError("Expected formula must be the actual function object")
        if (
            self.defined_for is not _UNSET
            and self.defined_for is not None
            and not isinstance(self.defined_for, str)
        ):
            raise WitnessError("Declare a variable enrollment mask or explicit None")
        object.__setattr__(self, "adds", _composition(self.adds))
        object.__setattr__(self, "subtracts", _composition(self.subtracts))


@dataclass(frozen=True)
class FixedInput:
    name: str
    period: str
    entity: str
    purpose: str
    signature: tuple

    @classmethod
    def from_array(cls, name, period, entity, purpose, expected_array):
        """Snapshot an explicitly supplied expectation, never infer an anchor."""
        return cls(name, period, entity, purpose, _array_signature(expected_array))

    def __post_init__(self):
        if self.purpose not in {"health_unit_value", "frozen_irmaa"}:
            raise WitnessError("Declare a health unit value or frozen IRMAA input")
        if not self.name or not self.period or not self.entity:
            raise WitnessError("Declare the fixed input's schema")
        if self.name in FORBIDDEN_INPUTS:
            raise WitnessError(
                "A derived price or account cannot become a fixed anchor"
            )
        if (self.name == IRMAA_INPUT) != (self.purpose == "frozen_irmaa"):
            raise WitnessError("The IRMAA exception requires its explicit purpose")
        if self.purpose == "frozen_irmaa" and (
            self.period != "2017" or self.entity != "tax_unit"
        ):
            raise WitnessError("Freeze the benefit-year2017 tax-unit IRMAA input")
        if not isinstance(self.signature, tuple) or len(self.signature) != 3:
            raise WitnessError("An explicit fixed-array signature is required")


class LiveContextWitness:
    """Read current formulas, parameters and supplied inputs before/after a branch.

    core_methods holds the actual unbound Core3.36.0 method objects authenticated
    by the runtime owner. Parameters map (leaf_path, instant) to known values.
    Formula-object identity detects replacement, not malicious __code__ edits.
    Other callbacks still own topology, take-up and allowed earnings changes.
    """

    def __init__(
        self,
        context,
        *,
        core_version,
        core_methods,
        variables,
        parameters,
        fixed_inputs,
    ):
        if core_version != "3.36.0" or set(core_methods) != CORE_METHODS:
            raise WitnessError("Use the source-bound Core3.36.0 input methods")
        if not all(callable(method) for method in core_methods.values()):
            raise WitnessError("Actual unbound Core method objects are required")
        if not isinstance(context, Mapping) or (
            context.get("law_year"),
            context.get("reporting_year"),
        ) != (2017, 2025):
            raise WitnessError("Declare native2017/reference2025 context")
        if any(
            not isinstance(context.get(key), str)
            or len(context[key]) != 64
            or any(character not in "0123456789abcdef" for character in context[key])
            for key in CONTEXT_DIGESTS
        ):
            raise WitnessError(
                "Declare actual runtime/input/price/account identity digests"
            )
        self.context = MappingProxyType(dict(context))
        self.core_methods = MappingProxyType(dict(core_methods))
        self.variables = tuple(variables)
        self.parameters = tuple(
            (path, instant, _value(value))
            for (path, instant), value in parameters.items()
        )
        self.fixed_inputs = tuple(fixed_inputs)
        names = [item.name for item in self.variables]
        variable_periods = [(item.name, item.period) for item in self.variables]
        inputs = [(item.name, item.period) for item in self.fixed_inputs]
        if not REQUIRED_VARIABLES.issubset(names) or len(variable_periods) != len(
            set(variable_periods)
        ):
            raise WitnessError("Bind the required variables and unique formula periods")
        if not self.parameters or len(inputs) != len(set(inputs)):
            raise WitnessError("Bind explicit parameter values and unique fixed inputs")
        if not any(item.purpose == "health_unit_value" for item in self.fixed_inputs):
            raise WitnessError("Declare the actual unmasked health unit inputs")
        if not any(item.purpose == "frozen_irmaa" for item in self.fixed_inputs):
            raise WitnessError("Declare the once-imputed frozen IRMAA input")

    def __call__(self, simulation):
        for name, expected in self.core_methods.items():
            actual = getattr(simulation, name, None)
            if getattr(actual, "__self__", None) is not simulation or (
                getattr(actual, "__func__", None) is not expected
            ):
                raise WitnessError("Core input-provenance method differs")
        system = simulation.tax_benefit_system
        for name in FORBIDDEN_INPUTS.intersection(system.variables):
            if simulation._get_set_input_periods(name):
                raise WitnessError(
                    "A supplied derived price or account overrides formulas"
                )
        for item in self.variables:
            variable = system.variables.get(item.name)
            if (
                variable is None
                or variable.get_formula(item.period) is not item.formula
            ):
                raise WitnessError("An admitted formula changed")
            if (
                variable.entity.key != item.entity
                or str(variable.definition_period).lower() != item.definition_period
                or variable.value_type is not item.value_type
                or _composition(variable.adds) != item.adds
                or _composition(variable.subtracts) != item.subtracts
                or variable.is_neutralized
                or (
                    item.defined_for is not _UNSET
                    and getattr(variable, "defined_for", _UNSET) != item.defined_for
                )
            ):
                raise WitnessError("An admitted variable definition changed")
        for path, instant, expected in self.parameters:
            actual = system.parameters.get_child(path).get_at_instant(instant)
            if _value(actual) != expected:
                raise WitnessError("An admitted parameter value changed")
        for item in self.fixed_inputs:
            variable = system.variables.get(item.name)
            if variable is None or variable.entity.key != item.entity:
                raise WitnessError("A fixed input's entity differs")
            matching = [
                period
                for period in simulation._get_set_input_periods(item.name)
                if str(period) == item.period
            ]
            if not matching:
                raise WitnessError("A fixed value is not a surviving supplied input")
            if str(variable.definition_period).lower() != str(matching[0].unit).lower():
                raise WitnessError("A fixed input's definition period differs")
            actual = simulation._get_recorded_input_array(item.name, matching[0])
            if _array_signature(actual) != item.signature:
                raise WitnessError("A fixed input changed")
        return self.context

    def audit(self, baseline, branch, selected):
        """Compose with the scenario audit; perform no calculation or mutation."""
        self(baseline)
        if branch is not None:
            self(branch)
