"""Build the PolicyEngine-US microsimulation for one configuration.

The runner and the tests both build simulations here, so the tests check
exactly what the runner computes.
"""

from __future__ import annotations

HEALTH_PARAMETER = "gov.simulation.include_health_benefits_in_net_income"


def reforms(health: bool, aca_before_2018: bool, medicaid_totals=None, year: int | None = None):
    """The reforms one configuration applies, or None.

    ``medicaid_totals`` (cliffs2017.medicaid) fixes Medicaid's two state
    totals at their full-sample values for ``year``.
    """
    from policyengine_core.reforms import Reform

    out = []
    if aca_before_2018:
        from cliffs2017.aca2017 import ACABefore2018

        out.append(ACABefore2018)
    if health:
        out.append(
            Reform.from_dict(
                {HEALTH_PARAMETER: {"2000-01-01.2100-12-31": True}}, country_id="us"
            )
        )
    if medicaid_totals is not None:
        from cliffs2017.medicaid import fixed_state_totals

        out.append(fixed_state_totals(medicaid_totals, year))
    return tuple(out) if out else None


def build_simulation(
    dataset,
    year: int,
    health: bool = False,
    aca_before_2018: bool = False,
    medicaid_totals=None,
):
    """A Microsimulation of ``dataset`` (already deflated to ``year`` if earlier).

    A dataset for an earlier year than its base (cliffs2017.deflate) needs no
    later years; a later simulation year extends the base year by the model's
    own uprating through ``year``. With health coverage counted, pass the
    full-sample ``medicaid_totals``: without them, each household's Medicaid
    value depends on the other households in ``dataset``.
    """
    from policyengine_us import Microsimulation

    return Microsimulation(
        dataset=dataset,
        reform=reforms(health, aca_before_2018, medicaid_totals, year),
        dataset_end_year=max(year, int(dataset.time_period)),
    )
