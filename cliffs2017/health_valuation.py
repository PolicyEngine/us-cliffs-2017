"""Reference unit values with native eligibility and Medicare premiums.

Importing this module loads no engine or data. Callers qualify the full reference
sample, convert its unmasked unit values to native money once, and supply them.
These interfaces do not certify those inputs or historical program coverage.
"""

from collections.abc import Mapping
from fractions import Fraction
from types import MappingProxyType
from typing import ClassVar

from .native_witness import FixedInput, WitnessError

MEDICAID_UNIT = "cliffs_reference_medicaid_unit_value"
CHIP_UNIT = "cliffs_reference_chip_net_unit_value"
MEDICARE_GROSS_UNIT = "cliffs_reference_medicare_gross_unit_value"
MEDICAID_VALUE = "cliffs_medicaid_government_value"
CHIP_VALUE = "cliffs_chip_net_value"
MEDICARE_NET_VALUE = "cliffs_medicare_net_value"
HEALTH_INPUTS = frozenset({MEDICAID_UNIT, CHIP_UNIT, MEDICARE_GROSS_UNIT})
HEALTH_OUTPUTS = frozenset({MEDICAID_VALUE, CHIP_VALUE, MEDICARE_NET_VALUE})
REFERENCE_READS = MappingProxyType(
    {
        MEDICAID_UNIT: "medicaid_cost_if_enrolled",
        CHIP_UNIT: CHIP_UNIT,
        MEDICARE_GROSS_UNIT: MEDICARE_GROSS_UNIT,
    }
)
NATIVE_PER_REFERENCE_DOLLAR = Fraction(245120, 321943)


class ReferenceHealthCapture:
    """Capture once on the caller's authenticated full reference2025 sample.

    The caller supplies actual formula objects and the admitted full-sample
    person count. This object does not certify their source or cohort identity.
    """

    def __init__(self, *, reference_formulas, person_count):
        if (
            not isinstance(reference_formulas, Mapping)
            or set(reference_formulas) != set(REFERENCE_READS.values())
            or not all(callable(formula) for formula in reference_formulas.values())
            or type(person_count) is not int
            or person_count <= 0
        ):
            raise WitnessError(
                "Bind actual unmasked formulas and full reference person count"
            )
        self.formulas = MappingProxyType(dict(reference_formulas))
        self.person_count = person_count
        self._arrays = None
        self._fixed = None
        self._native_attempted = False
        self._receipt = None

    def __call__(self, simulation):
        if self._arrays is not None:
            raise WitnessError("Capture the prepared reference health units only once")
        if simulation.populations["person"].count != self.person_count:
            raise WitnessError("Reference full-sample person count changed")
        for name, expected in self.formulas.items():
            variable = simulation.tax_benefit_system.variables.get(name)
            if (
                variable is None
                or variable.get_formula("2025") is not expected
                or variable.defined_for is not None
                or variable.entity.key != "person"
                or str(variable.definition_period).lower() != "year"
                or variable.is_neutralized
                or simulation._get_set_input_periods(name)
            ):
                raise WitnessError("Reference unmasked formula/schema/input differs")
        arrays, fixed, zeros = {}, {}, {}
        for native_name, read_name in REFERENCE_READS.items():
            series = simulation.calc(read_name, period=2025, map_to="person")
            if type(series).__name__ != "MicroSeries" or not type(
                series
            ).__module__.startswith("microdf."):
                raise WitnessError(
                    "Reference reads must retain managed person projection"
                )
            holder = simulation.get_holder(read_name)
            periods = [
                period
                for period in holder.get_known_periods(simulation.branch_name)
                if str(period) == "2025" and str(period.unit).lower() == "year"
            ]
            if len(periods) != 1:
                raise WitnessError(
                    "The reference unit has no unique current-branch annual cache"
                )
            raw = holder.get_array(periods[0], simulation.branch_name)
            if raw is None:
                raise WitnessError("The actual reference unit cache is missing")
            # Copy Core's cached 2025 reference formula-result array.
            array = raw.copy()
            expected = FixedInput.from_array(
                native_name, "2025", "person", "health_unit_value", array
            )
            if expected.signature[1] != (self.person_count,) or any(
                value < 0 for value in array.tolist()
            ):
                raise WitnessError(
                    "Reference units need finite nonnegative person vectors"
                )
            if len(series) != self.person_count:
                raise WitnessError("Managed reference person projection changed length")
            comparison = series == array
            if (
                type(comparison).__name__ != "MicroSeries"
                or not type(comparison).__module__.startswith("microdf.")
                or not comparison.all()
            ):
                raise WitnessError(
                    "Managed reference units differ from the raw Core cache"
                )
            arrays[native_name], fixed[native_name] = array, expected
            zeros[native_name] = sum(value == 0 for value in array.tolist())
        self._arrays, self._fixed = arrays, fixed
        self._receipt = {
            "reference_year": 2025,
            "person_count": self.person_count,
            "reference_signatures": tuple(
                (name, fixed[name].signature) for name in sorted(fixed)
            ),
            "zero_unit_cells": tuple(sorted(zeros.items())),
        }

    @property
    def receipt(self):
        if self._receipt is None:
            raise WitnessError("The actual reference units have not been captured")
        return MappingProxyType(dict(self._receipt))

    def prepare_health(self, simulation):
        """Convert once, explicitly encode, and install on one fresh native sim."""
        if self._arrays is None or self._native_attempted:
            raise WitnessError("Capture reference units before one native installation")
        self._native_attempted = True
        native_arrays = {}
        for name, array in self._arrays.items():
            actual = FixedInput.from_array(
                name, "2025", "person", "health_unit_value", array
            )
            if actual.signature != self._fixed[name].signature:
                raise WitnessError("Captured reference unit values changed")
            variable = simulation.tax_benefit_system.variables.get(name)
            if variable is None:
                raise WitnessError("The native health-input reform is missing")
            native_arrays[name] = (
                array.astype("float64", copy=True) * float(NATIVE_PER_REFERENCE_DOLLAR)
            ).astype(variable.dtype, copy=True)
        fixed = install_health_anchors(simulation, native_arrays=native_arrays)
        self._receipt = {
            **self._receipt,
            "native_year": 2017,
            "native_per_reference_dollar": (
                NATIVE_PER_REFERENCE_DOLLAR.numerator,
                NATIVE_PER_REFERENCE_DOLLAR.denominator,
            ),
            "encoding": "float64 multiplication once, then explicit actual-variable dtype",
            "native_signatures": tuple((item.name, item.signature) for item in fixed),
        }
        return fixed


def _types(model_api, reform_type):
    if (model_api is None) != (reform_type is None):
        raise ValueError("Supply both test doubles or use the maintained engine")
    if model_api is None:
        from policyengine_core.reforms import Reform
        from policyengine_us import model_api

        reform_type = Reform
    return model_api, reform_type


def make_reference_health_unit_reform(
    *, chip_formula, medicare_gross_formula, model_api=None, reform_type=None
):
    """Unmask actual source-bound 2025 formula objects on the reference system.

    Ordinary CHIP and Medicare outputs mask currently ineligible people. These
    distinct helpers retain their formulas but have no enrollment mask. The
    caller must authenticate the selected formula objects before construction.
    """
    if not callable(chip_formula) or not callable(medicare_gross_formula):
        raise TypeError("Bind the actual selected 2025 formula objects")
    api, reform = _types(model_api, reform_type)

    class cliffs_reference_chip_net_unit_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Unmasked reference CHIP net government unit value"
        formula = chip_formula

    class cliffs_reference_medicare_gross_unit_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Unmasked reference Medicare gross spending per enrollee"
        formula = medicare_gross_formula

    class ReferenceHealthUnitReform(reform):
        def apply(self):
            self.add_variable(cliffs_reference_chip_net_unit_value)
            self.add_variable(cliffs_reference_medicare_gross_unit_value)

    return ReferenceHealthUnitReform


def make_health_valuation_reform(*, model_api=None, reform_type=None):
    """Add account-only unit inputs and native-gated health values.

    Medicare follows the bound country's medicare_cost algebra, changing only
    gross spending to the supplied reference unit. Native premium rules and the
    average Part D premium remain live. MSP stays a separate native component.
    """
    api, reform = _types(model_api, reform_type)

    class cliffs_reference_medicaid_unit_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Fixed reference Medicaid unit value in native money"

    class cliffs_reference_chip_net_unit_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Fixed reference CHIP net unit value in native money"

    class cliffs_reference_medicare_gross_unit_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Fixed reference Medicare gross unit value in native money"

    class cliffs_medicaid_government_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Medicaid government value at the reference unit price"
        defined_for = "medicaid_enrolled"
        adds: ClassVar[list[str]] = [MEDICAID_UNIT]

    class cliffs_chip_net_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "CHIP net government value at the reference unit price"
        defined_for = "chip_enrolled"
        adds: ClassVar[list[str]] = [CHIP_UNIT]

    class cliffs_medicare_net_value(api.Variable):
        value_type = float
        entity = api.Person
        definition_period = api.YEAR
        unit = api.USD
        label = "Medicare net government value at reference gross spending"
        defined_for = "medicare_enrolled"

        def formula(person, period, parameters):
            p = parameters(period).calibration.gov.hhs.medicare
            gross = person(MEDICARE_GROSS_UNIT, period)
            part_a = person("base_part_a_premium", period)
            part_b = person("gross_medicare_part_b_premium_if_enrolled", period)
            average_part_d = p.part_d.enrollment_share * p.part_d.premiums_per_enrollee
            own_part_d = person("income_adjusted_part_d_premium_surcharge", period)
            return api.max_(gross - part_a - part_b - average_part_d - own_part_d, 0)

    class HealthValuationReform(reform):
        def apply(self):
            for variable in (
                cliffs_reference_medicaid_unit_value,
                cliffs_reference_chip_net_unit_value,
                cliffs_reference_medicare_gross_unit_value,
                cliffs_medicaid_government_value,
                cliffs_chip_net_value,
                cliffs_medicare_net_value,
            ):
                self.add_variable(variable)

    return HealthValuationReform


def install_health_anchors(simulation, *, native_arrays, period=2017):
    """Install three already-converted arrays; verify Core's surviving inputs.

    This function performs no currency conversion or reference calculation.
    Arrays must already use the actual variable dtype, avoiding an unrecorded
    setter cast. Any failure invalidates the fresh simulation; callers discard it.
    """
    if type(period) is not int or period != 2017:
        raise WitnessError("Install health units only at the native2017 clock")
    if not isinstance(native_arrays, Mapping) or set(native_arrays) != HEALTH_INPUTS:
        raise WitnessError("Supply all three explicit unmasked health unit arrays")
    expectations = []
    system = simulation.tax_benefit_system
    for name in sorted(HEALTH_INPUTS):
        variable = system.variables.get(name)
        array = native_arrays[name]
        if (
            variable is None
            or variable.entity.key != "person"
            or str(variable.definition_period).lower() != "year"
            or variable.value_type is not float
            or variable.get_formula("2017") is not None
            or variable.defined_for is not None
            or variable.is_neutralized
        ):
            raise WitnessError("Health input schema differs from the admitted reform")
        expected = FixedInput.from_array(
            name, "2017", "person", "health_unit_value", array
        )
        if (
            expected.signature[1] != (simulation.populations["person"].count,)
            or array.dtype.type is not variable.dtype
            or any(value < 0 for value in array.tolist())
        ):
            raise WitnessError(
                "Health units need the person shape, native dtype and nonnegative values"
            )
        if simulation._get_set_input_periods(name):
            raise WitnessError("Do not overwrite an existing health-unit input")
        expectations.append(expected)
    for expected in expectations:
        simulation.set_input(expected.name, "2017", native_arrays[expected.name])
        matches = [
            item
            for item in simulation._get_set_input_periods(expected.name)
            if str(item) == "2017"
        ]
        if len(matches) != 1:
            raise WitnessError("Core did not retain the explicit annual health input")
        actual = simulation._get_recorded_input_array(expected.name, matches[0])
        recorded = FixedInput.from_array(
            expected.name, "2017", "person", "health_unit_value", actual
        )
        if recorded.signature != expected.signature:
            raise WitnessError("Core changed the supplied health-unit array")
    return tuple(expectations)
