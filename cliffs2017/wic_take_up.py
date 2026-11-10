"""Set WIC take-up from the draw Microcosm stores, as policyengine.py does.

Microcosm's 2024 build stores each person's WIC take-up draw as
``would_claim_wic``. PolicyEngine-US has since renamed that input
``takes_up_wic_if_eligible`` (Person, MONTH, default True) and defines ``wic``
only for people who take it up, so a simulation that loads the file directly
never reads the draw and gives WIC to everyone eligible. policyengine.py, the
package PolicyEngine runs the model through, sets the new input from the stored
draw for every month when it loads US data (PolicyEngine/policyengine.py#531,
for PolicyEngine/microcosm#1026). ``map_stored_wic_take_up`` does the same for
the simulations here, on the same conditions:

- the engine defines ``takes_up_wic_if_eligible`` and not ``would_claim_wic``;
- the person table stores ``would_claim_wic`` and not ``takes_up_wic_if_eligible``;
- the table lists the simulation's people in the simulation's order;
- every stored value is boolean (or 0 or 1), with none missing.

It sets the input on the simulation and on every branch the simulation already
has, before anything is calculated, so the branches PolicyEngine-US makes to
raise each adult's earnings start from the mapped values.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

import numpy as np
import pandas as pd

LEGACY = "would_claim_wic"
LIVE = "takes_up_wic_if_eligible"
RENAMES = {LEGACY: LIVE}


def pending(variables) -> bool:
    """Whether the engine reads WIC take-up under the new name only."""
    return LEGACY not in variables and LIVE in variables


def stored_draw(person: pd.DataFrame) -> np.ndarray | None:
    """The stored draw as booleans, or None when the table gives none to map.

    A table that already stores ``takes_up_wic_if_eligible`` loads it directly,
    so it gives none. Missing or non-boolean values raise ``ValueError``.
    """
    if LEGACY not in person.columns or LIVE in person.columns:
        return None
    stored = person[LEGACY]
    if stored.isna().any():
        raise ValueError(f"{LEGACY} has missing values")
    if pd.api.types.is_bool_dtype(stored.dtype):
        return stored.to_numpy(dtype=bool)
    if pd.api.types.is_numeric_dtype(stored.dtype) and stored.isin((0, 1)).all():
        return stored.to_numpy().astype(bool)
    # An object column may hold booleans or 0 and 1; check each value before
    # casting, since bool("False") is True.
    if stored.map(
        lambda value: isinstance(value, (bool, np.bool_, int, np.integer, float, np.floating))
        and value in (0, 1)
    ).all():
        return stored.to_numpy().astype(bool)
    raise ValueError(f"{LEGACY} holds values that are not boolean")


def simulation_and_branches(simulation) -> Iterator:
    """The simulation, its branches, their branches, and so on, once each."""
    seen: set[int] = set()
    stack = [simulation]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        branches = getattr(current, "branches", None)
        if isinstance(branches, Mapping):
            stack.extend(branches.values())


def map_stored_wic_take_up(simulation, dataset, years: Iterable[int]) -> dict[str, str]:
    """Set ``takes_up_wic_if_eligible`` from the stored draw for each month of ``years``.

    Returns the renames applied, ``{"would_claim_wic": "takes_up_wic_if_eligible"}``,
    or ``{}`` when the conditions in the module docstring leave nothing to map.
    """
    if not pending(simulation.tax_benefit_system.variables):
        return {}
    person = dataset.person
    draw = stored_draw(person)
    if draw is None:
        return {}
    if "person_id" not in person.columns:
        raise ValueError("the person table has no person_id column, so its order can't be checked")
    stored_ids = person["person_id"].to_numpy()
    periods = [f"{year}-{month:02d}" for year in years for month in range(1, 13)]
    if not periods:
        raise ValueError("no years to map WIC take-up for")
    simulations = list(simulation_and_branches(simulation))
    # Check every simulation before setting anything, so a refusal leaves none mapped.
    for current in simulations:
        if not np.array_equal(stored_ids, np.asarray(current.populations["person"].ids)):
            raise ValueError(
                "the person table is not in the simulation's person order, "
                "so the stored WIC draw would attach to the wrong people"
            )
    for current in simulations:
        for period in periods:
            current.set_input(LIVE, period, draw)
        inputs = getattr(current, "input_variables", None)
        if isinstance(inputs, list) and LIVE not in inputs:
            current.input_variables = [*inputs, LIVE]
    return dict(RENAMES)
