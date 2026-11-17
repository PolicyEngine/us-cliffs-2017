"""Observable eligibility, state coverage and accounting guards for the pilot."""

import json

import numpy as np
import pandas as pd
import pytest
from microdf import MicroSeries

from scripts.expanded_job_entry import (
    PILOT_WAGES,
    eligible_nonworkers,
    hourly_wages,
    job_increments,
    json_scalar,
    map_flag,
    run_pilot,
    stratified_pilot,
)


def test_selection_boundaries_and_observed_exclusions():
    """A job test concerns working-age nonworkers, with explicit exclusions."""
    age = MicroSeries([17, 18, 64, 65, 30, 30, 30, 30, 30], weights=[1] * 9)
    zero = age * 0
    wages = zero.copy()
    wages.iloc[4] = 1
    self_employment = zero.copy()
    self_employment.iloc[5] = -100
    student = zero > 0
    student.iloc[6] = True
    disabled = zero > 0
    disabled.iloc[7] = True
    result = eligible_nonworkers(age, wages, self_employment, zero, student, disabled)
    assert isinstance(result, MicroSeries)
    assert result.tolist() == [
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        True,
    ]


def test_minimum_wage_pilot_uses_actual_2017_values():
    """DOL historical table: CO $9.30, NC $7.25, WA $11.00 in 2017."""
    assert PILOT_WAGES == {"CO": 9.30, "NC": 7.25, "WA": 11.00}
    assert PILOT_WAGES["CO"] * 40 * 52 == 19_344
    assert PILOT_WAGES["NC"] * 40 * 52 == 15_080
    assert PILOT_WAGES["WA"] * 40 * 52 == 22_880


def test_state_wage_mapping_preserves_microseries_weight_context():
    state = MicroSeries(["CO", "NC", "WA"], weights=[2, 3, 4])
    result = hourly_wages(state, PILOT_WAGES)
    assert isinstance(result, MicroSeries)
    assert result.sum() == pytest.approx(9.30 * 2 + 7.25 * 3 + 11 * 4)
    with pytest.raises(ValueError, match="missing verified"):
        hourly_wages(MicroSeries(["CA"], weights=[1]), PILOT_WAGES)


def test_job_inputs_replace_unemployment_and_work_time_only_for_entrant():
    """The full-year job changes earnings, hours, weeks and unemployment income."""
    records = {
        "hours_worked_last_week": [0, 20],
        "weekly_hours_worked_before_lsr": [0, 20],
        "weeks_worked": [0, 50],
        "weeks_unemployed": [15, 0],
        "unemployment_compensation": [4_000, 0],
        "hourly_wage": [0, 15],
    }

    class Sim:
        def calc(self, variable, period):
            return MicroSeries(records[variable], weights=[2, 3])

    selected = MicroSeries([True, False], weights=[2, 3])
    wage = MicroSeries([7.25, 11], weights=[2, 3])
    changes, gross = job_increments(Sim(), selected, wage)
    assert gross.tolist() == [15_080, 0]
    assert changes["hours_worked_last_week"].tolist() == [40, 0]
    assert changes["weeks_worked"].tolist() == [52, 0]
    assert changes["weeks_unemployed"].tolist() == [-15, 0]
    assert changes["unemployment_compensation"].tolist() == [-4_000, 0]
    assert all(isinstance(value, MicroSeries) for value in changes.values())


def test_pilot_refuses_national_or_unverified_scope():
    class Data:
        household = pd.DataFrame(index=range(31))

    with pytest.raises(ValueError, match="more than 30"):
        run_pilot(Data())
    with pytest.raises(ValueError, match="verified only"):
        stratified_pilot(None, ["CA"])
    with pytest.raises(ValueError, match="1..10"):
        stratified_pilot(None, ["CO"], per_state=100)


def test_validation_record_serializes_actual_model_scalar_types():
    # Model net-income values are float32; validation must survive writing its
    # result after successful counterfactual calculations.
    result = json.dumps({"difference": np.float32(0)}, default=json_scalar)
    assert json.loads(result) == {"difference": 0}
    with pytest.raises(TypeError, match="cannot serialize"):
        json.dumps({"invalid": object()}, default=json_scalar)


def test_reusing_flag_updates_previously_cached_household_projection():
    """Different retention thresholds must not reuse the previous union."""

    class CachedSim:
        cached = None

        def set_input(self, name, year, value):
            self.flag = value

        def delete_arrays(self, name, year):
            self.cached = None

        def calc(self, name, period, map_to=None):
            # Core retains a calculated dependent until explicitly cleared.
            # This fixture has one adult in each of two households.
            if self.cached is None:
                self.cached = self.flag.copy()
            return self.cached

    sim = CachedSim()
    both = MicroSeries([True, True], weights=[2, 3])
    one = MicroSeries([True, False], weights=[2, 3])
    assert map_flag(sim, both)[0].sum() == 5
    assert map_flag(sim, one)[0].sum() == 2
