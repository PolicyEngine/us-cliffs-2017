"""Cliff tests with other changes in earnings: larger raises, raises in
proportion to earnings, and cuts.

PolicyEngine-US tests for a cliff with one change, a $1,000 raise
(``simulation.marginal_tax_rate_delta``) for each of the two highest-income
adults in a household. This module runs the same test with any change, in
dollars or as a share of the adult's earnings, upward or downward:

- an adult *faces a cliff* under a raise when their household's net income
  falls with it;
- under a cut, the mirror image: the household's net income rises when the
  adult earns less.

Both say net income moves the opposite way to earnings, so one rule covers
them: ``change * d_net < 0``.

A raise in dollars goes to every measured adult, as the model's own test does,
whether or not they have earnings. A cut in dollars goes only to adults whose
earnings reach it, and a change in proportion to earnings only to adults with
earnings, so neither leaves anyone with negative earnings. "Earnings" here are
the positive parts of wages and both kinds of self-employment income, the
amounts PolicyEngine-US's ``earnings_increments`` splits a change across: each
part moves in proportion to its share, so a cut no larger than the total
leaves every part at zero or above.

For each change, :func:`decompose_change` builds the same branches as
cliffs2017.decompose (PolicyEngine-US's ``create_perturbed_branch`` and
``earnings_increments``, one branch per measured rank) and records the change
in every part of household net income, plus the base and changed values of
person-level variables the caller names (the premium tax credit's income
fraction, for instance). With the change set to the model's $1,000 raise it
reproduces cliffs2017.decompose exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cliffs2017.decompose import MARKETPLACE_PREMIUM, NET, components, household_values

EARNINGS = ("employment_income", "self_employment_income", "sstb_self_employment_income")


@dataclass(frozen=True)
class Change:
    """A change in earnings: ``amount`` dollars, or ``share`` of the adult's earnings."""

    amount: float = 0.0
    share: float = 0.0

    def __post_init__(self):
        if (self.amount == 0) == (self.share == 0):
            raise ValueError("a change is a nonzero amount or a nonzero share, not both")
        if not -1 < self.share < 1:
            raise ValueError("a share must lie strictly between -1 and 1")

    @property
    def sign(self) -> int:
        return 1 if (self.amount or self.share) > 0 else -1

    @property
    def label(self) -> str:
        if self.amount:
            return f"{self.amount:+,.0f}"
        return f"{self.share * 100:+g}%"

    @property
    def key(self) -> str:
        """A name safe for files and JSON keys: raise_1000, cut_5000, raise_1pct."""
        word = "raise" if self.sign > 0 else "cut"
        if self.amount:
            return f"{word}_{abs(self.amount):g}"
        return f"{word}_{abs(self.share) * 100:g}pct"


def parse(text: str) -> Change:
    """'+1000', '-5000', '+1%' or '-10%' as a Change."""
    match = re.fullmatch(r"([+-])(\d+(?:\.\d+)?)(%?)", text.strip().replace(",", ""))
    if not match:
        raise ValueError(f"not a change: {text!r} (write +1000, -5000, +1% or -10%)")
    sign = 1 if match.group(1) == "+" else -1
    value = float(match.group(2))
    if match.group(3):
        return Change(share=sign * value / 100)
    return Change(amount=sign * value)


def positive_earnings(employment, self_employment, sstb_self_employment) -> np.ndarray:
    """The earnings a change splits across: the positive part of each kind, summed."""
    return (
        np.maximum(0, np.asarray(employment, dtype=float))
        + np.maximum(0, np.asarray(self_employment, dtype=float))
        + np.maximum(0, np.asarray(sstb_self_employment, dtype=float))
    )


def person_changes(change: Change, measured: np.ndarray, earnings: np.ndarray) -> np.ndarray:
    """Each person's change in earnings: zero for everyone the test leaves out.

    ``measured`` flags the adults the test measures and ``earnings`` holds each
    person's positive earnings (:func:`positive_earnings`).
    """
    measured = np.asarray(measured, dtype=bool)
    earnings = np.asarray(earnings, dtype=float)
    if change.share:
        return np.where(measured & (earnings > 0), change.share * earnings, 0.0)
    if change.amount > 0:
        return np.where(measured, change.amount, 0.0)
    return np.where(measured & (earnings >= -change.amount), change.amount, 0.0)


def moves_against(change_values, d_net) -> np.ndarray:
    """Whether net income moves the opposite way to earnings: a cliff under a
    raise, a gain from a cut."""
    return np.asarray(change_values, dtype=float) * np.asarray(d_net, dtype=float) < 0


def decompose_change(
    simulation, period, change: Change, person_variables: tuple[str, ...] = ()
) -> pd.DataFrame:
    """One row per adult the change reaches: its size and the change in every part.

    Columns: ``person_index``, ``rank``, ``change`` (the adult's change in
    earnings), ``d_<part>`` for each part of household net income (signed so
    they add up to ``d_net``), ``d_parts``, ``d_net``, ``d_net_single_ptc``
    (the premium tax credit counted once, as cliffs2017.decompose defines it)
    and, for each name in ``person_variables``, ``base_<name>`` and
    ``alt_<name>``.
    """
    from policyengine_us.variables.household.marginal_tax_rate_helpers import (
        create_perturbed_branch,
        earnings_increments,
    )

    p = simulation.tax_benefit_system.parameters(period)
    adults = int(p.simulation.marginal_tax_rate_adults)
    parts = components(simulation, period)
    names = [name for name, _ in parts]
    person = simulation.populations["person"]
    household_index = np.asarray(simulation.populations["household"].members_entity_id)
    rank = np.asarray(simulation.calculate("adult_earnings_index", period))
    is_adult = np.asarray(simulation.calculate("is_adult", period)).astype(bool)
    earnings = positive_earnings(
        *(np.asarray(simulation.calculate(v, period)) for v in EARNINGS)
    )
    base = household_values(simulation, names + [NET], period)
    base_person = {
        v: np.asarray(simulation.calculate(v, period, map_to="person"), dtype=np.float64)
        for v in person_variables
    }
    rows = []
    for k in range(1, adults + 1):
        amounts = person_changes(change, is_adult & (rank == k), earnings)
        people = np.flatnonzero(amounts != 0)
        if len(people) == 0:
            continue
        name = f"cliffs2017_change_{change.key}_adult_{k}"
        branch = create_perturbed_branch(
            simulation, period, name, earnings_increments(person, period, amounts)
        )
        alt = household_values(branch, names + [NET], period)
        alt_person = {
            v: np.asarray(branch.calculate(v, period, map_to="person"), dtype=np.float64)
            for v in person_variables
        }
        del simulation.branches[name]
        households = household_index[people]
        frame = pd.DataFrame({"person_index": people, "rank": k, "change": amounts[people]})
        for variable, sign in parts:
            frame[f"d_{variable}"] = sign * (alt[variable] - base[variable])[households]
        frame["d_net"] = (alt[NET] - base[NET])[households]
        frame["d_parts"] = frame[[f"d_{v}" for v in names]].sum(axis=1)
        for v in person_variables:
            frame[f"base_{v}"] = base_person[v][people]
            frame[f"alt_{v}"] = alt_person[v][people]
        rows.append(frame)
    if not rows:
        raise ValueError(f"the change {change.label} reaches nobody")
    out = pd.concat(rows, ignore_index=True)
    premium = f"d_{MARKETPLACE_PREMIUM}"
    out["d_net_single_ptc"] = out["d_net"] - (out[premium] if premium in out else 0)
    return out


def health_parts(simulation, period) -> list[str]:
    """The ``d_`` columns that health coverage adds: its benefits and its costs."""
    p = simulation.tax_benefit_system.parameters(period)
    if not bool(p.gov.simulation.include_health_benefits_in_net_income):
        return []
    return [f"d_{v}" for v in p.gov.household.household_health_benefits] + [
        f"d_{v}" for v in p.gov.household.household_health_costs
    ]


def without_health(frame: pd.DataFrame, health_columns: list[str]) -> pd.Series:
    """The change in net income outside health coverage: every part but the health ones.

    In a run that counts health coverage, this is the change a run that doesn't
    count it computes, provided nothing outside health coverage depends on
    whether net income counts it (scripts/earnings_changes.py checks that
    against the committed runs).
    """
    keep = [
        c for c in frame.columns
        if c.startswith("d_") and c not in ("d_net", "d_parts", "d_net_single_ptc")
        and c not in health_columns
    ]
    return frame[keep].sum(axis=1)
