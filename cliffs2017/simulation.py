"""Build the PolicyEngine-US microsimulation for one configuration.

The runner and the tests both build simulations here, so the tests check
exactly what the runner computes.
"""

from __future__ import annotations

HEALTH_PARAMETER = "gov.simulation.include_health_benefits_in_net_income"


def reforms(
    health: bool,
    aca_before_2018: bool,
    medicaid_totals=None,
    year: int | None = None,
    leave_out_csfp: bool = False,
):
    """The reforms one configuration applies, or None.

    ``medicaid_totals`` (cliffs2017.medicaid) fixes Medicaid's two state
    totals at their full-sample values for ``year``. ``leave_out_csfp``
    removes the Commodity Supplemental Food Program from household benefits
    (cliffs2017.benefits).
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
    if leave_out_csfp:
        from cliffs2017.benefits import LeaveOutCSFP

        out.append(LeaveOutCSFP)
    return tuple(out) if out else None


def build_simulation(
    dataset,
    year: int,
    health: bool = False,
    aca_before_2018: bool = False,
    medicaid_totals=None,
    leave_out_csfp: bool = False,
):
    """A Microsimulation of ``dataset`` (already deflated to ``year`` if earlier).

    A dataset for an earlier year than its base (cliffs2017.deflate) needs no
    later years; a later simulation year extends the base year by the model's
    own uprating through ``year``. With health coverage counted, pass the
    full-sample ``medicaid_totals``: without them, each household's Medicaid
    value depends on the other households in ``dataset``.

    Each simulation sets WIC take-up from Microcosm's stored draw for every
    month it covers, as policyengine.py does when it loads US data
    (cliffs2017.wic_take_up), and records the renames it applied in
    ``stored_input_renames``.
    """
    from policyengine_us import Microsimulation

    from cliffs2017.wic_take_up import map_stored_wic_take_up

    base = int(dataset.time_period)
    sim = Microsimulation(
        dataset=dataset,
        reform=reforms(health, aca_before_2018, medicaid_totals, year, leave_out_csfp),
        dataset_end_year=max(year, base),
    )
    sim.stored_input_renames = map_stored_wic_take_up(
        sim, dataset, range(min(year, base), max(year, base) + 1)
    )
    return sim
