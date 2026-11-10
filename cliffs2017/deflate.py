"""Take the Microcosm 2024 population back to an earlier year's dollar levels.

PolicyEngine-US ages a dataset only forward (``extend_single_year_dataset``
refuses an end year before the dataset's year), and policyengine-core never
carries an input backward in time, so a 2017 simulation needs its own 2017
inputs. This module builds them from the 2024 build: every dollar-valued input
is multiplied by index(target) / index(2024) for an index chosen below, and
household weights scale with population. Demographics, family structure,
take-up draws and other non-dollar inputs stay as they are, so the result is
the 2024 population at 2017 income and price levels, not a 2017 population.

Index choice (each has a real value for 2017 in PolicyEngine-US's parameter
files; several of the model's own income indices do not, because the IRS SOI
series jump from 2015 to 2020):

- earnings: the SSA national average wage index (``gov.ssa.nawi``), for wages,
  self-employment income, tips, and wage-linked benefits (unemployment
  compensation, workers' compensation, disability benefits);
- cola: the cumulative Social Security cost-of-living adjustments
  (``gov.ssa.cola_history.rate``), for Social Security, SSI and veterans'
  benefits;
- the model's own CMS series for health premiums and medical spending, and
  its Census population series for household weights (both annual through
  2017);
- cpi_u: CPI-U (``gov.bls.cpi.cpi_u``) for every other dollar-valued input.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from policyengine_core.parameters import get_parameter

from policyengine_us.data.dataset_schema import USSingleYearDataset

EARNINGS_INDICES = {
    "calibration.gov.irs.soi.employment_income_per_capita",
    "calibration.gov.irs.soi.self_employment_income_per_capita",
    "calibration.gov.irs.soi.unemployment_compensation_per_capita",
}
# The model's own index is kept only for these, which have annual values
# through the target year.
KEEP_MODEL_INDEX = {
    "calibration.gov.hhs.cms.esi_premium_per_enrollee",
    "calibration.gov.hhs.cms.moop_per_capita",
    "calibration.gov.hhs.cms.direct_purchase_premium_per_enrollee",
    "calibration.gov.census.populations.total",
}
COLA_COLUMNS = {
    "social_security_retirement",
    "social_security_disability",
    "social_security_survivors",
    "social_security_dependents",
    "social_security",
    "ssi_reported",
    "veterans_benefits",
}
# Dollar-valued inputs with no uprating attribute (unit missing in the model).
EXTRA_CPI_COLUMNS = {"household_vehicles_value"}
# Calendar-year inputs that must not postdate the target year.
YEAR_COLUMNS = {
    "first_home_mortgage_origination_year",
    "second_home_mortgage_origination_year",
}


@dataclass
class ColumnFactor:
    entity: str
    column: str
    index: str
    factor: float
    model_uprating: str | None


def _value(parameters, path, year):
    return float(get_parameter(parameters, path)(f"{year}-01-01"))


def cola_ratio(parameters, target: int, base: int) -> float:
    """Benefit level in January of ``target`` relative to January of ``base``.

    A COLA dated December of year Y raises benefits from the December payment
    on, so January of year T reflects every COLA dated in December of T-1 or
    earlier.
    """
    rate = get_parameter(parameters, "gov.ssa.cola_history.rate")
    growth = 1.0
    for year in range(target, base):
        growth *= 1 + float(rate(f"{year}-12-01"))
    return 1 / growth


def index_factors(system, target: int, base: int) -> dict[str, float]:
    p = system.parameters
    return {
        "earnings": _value(p, "gov.ssa.nawi", target) / _value(p, "gov.ssa.nawi", base),
        "cola": cola_ratio(p, target, base),
        "cpi_u": _value(p, "gov.bls.cpi.cpi_u", target)
        / _value(p, "gov.bls.cpi.cpi_u", base),
    }


def column_factors(dataset: USSingleYearDataset, system, target: int) -> list[ColumnFactor]:
    base = int(dataset.time_period)
    general = index_factors(system, target, base)
    factors = []
    for entity, frame in zip(dataset.table_names, dataset.tables):
        for column in frame.columns:
            variable = system.variables.get(column)
            if variable is None:
                continue
            uprating = variable.uprating
            if column in COLA_COLUMNS:
                index, factor = "cola", general["cola"]
            elif uprating in EARNINGS_INDICES:
                index, factor = "earnings", general["earnings"]
            elif uprating in KEEP_MODEL_INDEX:
                index = uprating
                factor = _value(system.parameters, uprating, target) / _value(
                    system.parameters, uprating, base
                )
            elif uprating is not None or column in EXTRA_CPI_COLUMNS:
                index, factor = "cpi_u", general["cpi_u"]
            else:
                continue
            factors.append(ColumnFactor(entity, column, index, factor, uprating))
    return factors


def deflate(dataset: USSingleYearDataset, system, target: int):
    """Return (dataset at ``target`` levels, table of the factors applied)."""
    base = int(dataset.time_period)
    if target >= base:
        raise ValueError("Use PolicyEngine-US's own forward extension for later years.")
    out = dataset.copy(deep=True)
    tables = dict(zip(out.table_names, out.tables))
    factors = column_factors(dataset, system, target)
    for item in factors:
        frame = tables[item.entity]
        frame[item.column] = frame[item.column].to_numpy(dtype=np.float64) * item.factor
    for entity, frame in tables.items():
        for column in YEAR_COLUMNS & set(frame.columns):
            values = frame[column].to_numpy()
            frame[column] = np.where(values > target, target, values)
    result = USSingleYearDataset(
        person=tables["person"],
        household=tables["household"],
        tax_unit=tables["tax_unit"],
        spm_unit=tables["spm_unit"],
        family=tables["family"],
        marital_unit=tables["marital_unit"],
        time_period=target,
    )
    table = pd.DataFrame([vars(f) for f in factors])
    return result, table


def _keep_households(dataset: USSingleYearDataset, keep: np.ndarray, weight_divisor: float):
    """The households where ``keep`` is true, with all their members and units."""
    households = dataset.household
    kept_ids = set(households.household_id[keep])
    person = dataset.person[dataset.person.person_household_id.isin(kept_ids)]
    household = households[keep].copy()
    household["household_weight"] = household["household_weight"] / weight_divisor

    def members(frame, id_column, person_column):
        if len(frame) == 0:
            return frame
        return frame[frame[id_column].isin(set(person[person_column]))]

    return USSingleYearDataset(
        person=person,
        household=household,
        tax_unit=members(dataset.tax_unit, "tax_unit_id", "person_tax_unit_id"),
        spm_unit=members(dataset.spm_unit, "spm_unit_id", "person_spm_unit_id"),
        family=members(dataset.family, "family_id", "person_family_id"),
        marital_unit=members(
            dataset.marital_unit, "marital_unit_id", "person_marital_unit_id"
        ),
        time_period=int(dataset.time_period),
    )


def household_draws(dataset: USSingleYearDataset, seed: int = 0) -> np.ndarray:
    """One uniform draw per household, the basis of subsample and partition."""
    return np.random.default_rng(seed).random(len(dataset.household))


def subsample(dataset: USSingleYearDataset, fraction: float, seed: int = 0):
    """Keep a random share of households (with all their members), reweighted."""
    keep = household_draws(dataset, seed) < fraction
    return _keep_households(dataset, keep, fraction)


def partition(dataset: USSingleYearDataset, parts: int, index: int, seed: int = 0):
    """Household group ``index`` of ``parts`` disjoint groups, at full weight.

    The groups cover every household once, so summing a total over the parts
    gives the full-sample total. Group 0 holds the same households as
    ``subsample(dataset, 1 / parts, seed)``.
    """
    if not 0 <= index < parts:
        raise ValueError(f"part {index} is not in 0..{parts - 1}")
    group = np.minimum((household_draws(dataset, seed) * parts).astype(int), parts - 1)
    return _keep_households(dataset, group == index, 1.0)
