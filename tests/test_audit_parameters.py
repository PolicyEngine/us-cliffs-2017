"""The parameter audit's tracing logs scales and reads by path, and changes no value."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_parameters import ParameterRecorder, traced_reads  # noqa: E402

YEAR = 2017

# New Mexico's EITC formula reads its minimum age by path,
# parameters.gov.X(period).
NM_MIN_AGE = "gov.states.nm.tax.income.credits.eitc.eligibility.age.min"
# The federal EITC formulas read their age limits by path too.
FEDERAL_MIN_AGE = "gov.irs.credits.eitc.eligibility.age.min"
# California's income tax reads its rates as bracket scales.
CA_SINGLE_RATES = "gov.states.ca.tax.income.rates.single"


def filer(state):
    return {
        "people": {"adult": {"age": {YEAR: 22}, "employment_income": {YEAR: 9_000}}},
        "tax_units": {"tu": {"members": ["adult"]}},
        "spm_units": {"spm": {"members": ["adult"]}},
        "households": {"h": {"members": ["adult"], "state_code": {YEAR: state}}},
    }


def traced(system, state, variable, extend=True):
    """Calculate a variable with tracing on; return the value and the reads."""
    from policyengine_us import Simulation

    def run():
        sim = Simulation(tax_benefit_system=system, situation=filer(state))
        sim.trace = True
        sim.tracer = ParameterRecorder()
        return np.asarray(sim.calculate(variable, YEAR)), sim.tracer.reads

    if extend:
        with traced_reads():
            return run()
    return run()


def untraced(system, state, variable):
    from policyengine_us import Simulation

    sim = Simulation(tax_benefit_system=system, situation=filer(state))
    return np.asarray(sim.calculate(variable, YEAR))


@pytest.mark.parametrize(
    "state, variable, name",
    [
        ("NM", "nm_eitc_demographic_eligible", NM_MIN_AGE),
        ("NM", "eitc_demographic_eligible", FEDERAL_MIN_AGE),
        ("CA", "ca_income_tax_before_credits", CA_SINGLE_RATES),
    ],
)
def test_logs_reads_core_misses(system, state, variable, name):
    _, plain_reads = traced(system, state, variable, extend=False)
    _, reads = traced(system, state, variable)
    assert name not in plain_reads  # the gap the extensions close
    assert reads[name] == f"{YEAR}-01-01"


@pytest.mark.parametrize(
    "state, variable",
    [
        ("NM", "nm_eitc_demographic_eligible"),
        ("NM", "nm_eitc"),
        ("CA", "ca_income_tax_before_credits"),
        ("CA", "household_net_income"),
    ],
)
def test_values_match_a_run_without_tracing(system, state, variable):
    value, _ = traced(system, state, variable)
    assert np.array_equal(value, untraced(system, state, variable))


def test_logs_reads_at_a_later_instant(system):
    """Virginia TANF reads its need standards as of October 2020, by path."""
    from policyengine_us import Simulation

    with traced_reads():
        sim = Simulation(tax_benefit_system=system, situation=filer("VA"))
        sim.trace = True
        sim.tracer = ParameterRecorder()
        sim.calculate("va_tanf_need_standard", f"{YEAR}-01")
    instants = sim.tracer.instants
    assert instants["gov.states.va.dss.tanf.need_standard.group2.main"] == {"2020-10-01"}
    assert "2017-01-01" in instants["gov.states.va.dss.tanf.max_unit_size"]


def test_restores_core_tracing(system):
    from policyengine_core.tracers import tracing_parameter_node_at_instant as tracing

    before = (
        tracing.TracingParameterNode.__getattr__,
        tracing.TracingParameterNodeAtInstant.get_traced_child,
    )
    with traced_reads():
        pass
    after = (
        tracing.TracingParameterNode.__getattr__,
        tracing.TracingParameterNodeAtInstant.get_traced_child,
    )
    assert after == before
