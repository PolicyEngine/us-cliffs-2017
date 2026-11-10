"""Build the PolicyEngine-US microsimulation for one configuration.

The runner and the tests both build simulations here, so the tests check
exactly what the runner computes.
"""

from __future__ import annotations

HEALTH_PARAMETER = "gov.simulation.include_health_benefits_in_net_income"


def reforms(health: bool, aca_before_2018: bool):
    """The reforms one configuration applies, or None."""
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
    return tuple(out) if out else None


def build_simulation(dataset, year: int, health: bool = False, aca_before_2018: bool = False):
    """A Microsimulation of ``dataset`` (already deflated to ``year`` if earlier).

    A dataset for an earlier year than its base (cliffs2017.deflate) needs no
    later years; a later simulation year extends the base year by the model's
    own uprating through ``year``.
    """
    from policyengine_us import Microsimulation

    return Microsimulation(
        dataset=dataset,
        reform=reforms(health, aca_before_2018),
        dataset_end_year=max(year, int(dataset.time_period)),
    )
