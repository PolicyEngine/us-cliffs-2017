"""Load the explicitly historical 2017 experiment without changing its engine.

The current policyengine.py release refuses the frozen model before its
``allow_unmanaged`` constructor can run.  This module preserves the previously
run historical experiment, records that exception, and never describes it as a
current certified bundle. New aggregation uses ``calc``/MicroSeries and
``map_to``; callers must not aggregate weight columns themselves.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PACKAGES = {
    "policyengine-us": "2.116.0",
    "policyengine-core": "3.34.10",
    "microdf-python": "1.5.12",
    "spm-calculator": "1.1.0",
    "numpy": "2.5.4",
    "pandas": "3.1.1",
    "tables": "3.11.1",
    "huggingface-hub": "2.4.0",
}


def historical_provenance() -> dict:
    versions = {name: metadata.version(name) for name in FROZEN_PACKAGES}
    if versions != FROZEN_PACKAGES:
        raise RuntimeError(
            f"historical experiment requires {FROZEN_PACKAGES}: {versions}"
        )
    try:
        wrapper_version = metadata.version("policyengine")
    except metadata.PackageNotFoundError:
        wrapper_version = None
    return {
        "experiment": "frozen-historical-2017",
        "versions": versions,
        "policyengine_wrapper_installed": wrapper_version,
        "policyengine_wrapper_attempted": "6.17.2",
        "managed_bundle": False,
        "managed_loader_limitation": (
            "policyengine 6.17.2 rejects the historical model 2.116.0 during "
            "country import, before allow_unmanaged can select a custom dataset"
        ),
        "source_dataset": (
            "policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260909"
        ),
        "population": "2024 microdata scaled to 2017 size, incomes and prices",
        "policy": "2017 federal rules, model's 2018 Medicaid/CHIP limits, later state rules",
        "aggregation": "MicroSeries methods; household weights mapped internally",
    }


def load_historical_dataset(
    year: int = 2017,
    *,
    parts: int = 1,
    part: int = 0,
    seed: int = 0,
    system=None,
):
    """Return the same frozen, deflated data used in the previous experiment."""
    historical_provenance()
    from policyengine_us import CountryTaxBenefitSystem

    from cliffs2017.run import load_dataset

    system = system or CountryTaxBenefitSystem()
    dataset, _ = load_dataset(year, 1.0, seed, system, parts, part)
    return dataset


def build_historical_simulation(dataset, year: int = 2017, *, health: bool = True):
    """Preserve the existing reforms, WIC inputs and Medicaid valuation."""
    historical_provenance()
    from cliffs2017.medicaid import load_totals
    from cliffs2017.simulation import build_simulation

    totals = None
    if health:
        path = ROOT / "results" / "medicaid" / f"totals_{year}_p4_s0.json"
        if not path.exists():
            raise FileNotFoundError(
                f"frozen full-sample Medicaid totals missing: {path}"
            )
        totals, _ = load_totals(path)
    return build_simulation(
        dataset,
        year,
        health=health,
        aca_before_2018=year < 2018,
        medicaid_totals=totals,
        leave_out_csfp=year >= 2024,
    )
