"""The premium tax credit moves health-inclusive net income twice.

METHODOLOGY.md says that, with health coverage counted, a $1 cut in the
credit of an enrollee who pays a premium lowers PolicyEngine-US's household
net income by $2, and that cliffs2017/decompose.py counts it once by leaving
out the change in the net premium. scripts/ptc_household.py computes one such
household; these tests pin the identities on it, so an upgrade that changes
how the model counts the credit fails here first.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ptc_household import compute  # noqa: E402

YEAR, STATE, EARNINGS, RAISE = 2025, "TX", 30_000, 1_000


@pytest.fixture(scope="module")
def changes():
    out = {}
    for health in (False, True):
        base = compute(YEAR, STATE, EARNINGS, health)
        raised = compute(YEAR, STATE, EARNINGS + RAISE, health)
        out[health] = {
            k: raised[k] - base[k] for k in base if isinstance(base[k], float)
        }
        out[health]["base"] = base
    return out


def test_household_is_a_premium_paying_enrollee(changes):
    base = changes[True]["base"]
    assert not base["is_medicaid_eligible"]
    assert 0 < base["assigned_aca_ptc"] < base["selected_marketplace_plan_premium_proxy"]
    assert changes[True]["aca_ptc"] < 0  # the raise cuts the credit


def test_without_health_coverage_the_credit_leaves_net_income_alone(changes):
    c = changes[False]
    assert c["household_net_income"] == pytest.approx(
        RAISE - c["household_tax_before_refundable_credits"], abs=0.01
    )


def test_with_health_coverage_the_credit_counts_twice(changes):
    c = changes[True]
    cut = c["assigned_aca_ptc"]
    assert c["household_health_benefits"] == pytest.approx(cut, abs=0.01)
    assert c["marketplace_net_premium"] == pytest.approx(-cut, abs=0.01)
    assert c["household_net_income"] - changes[False]["household_net_income"] == pytest.approx(
        2 * cut, abs=0.01
    )


def test_leaving_out_the_net_premium_counts_it_once(changes):
    c = changes[True]
    once = c["household_net_income"] + c["marketplace_net_premium"]
    assert once - changes[False]["household_net_income"] == pytest.approx(
        c["assigned_aca_ptc"], abs=0.01
    )


def test_model_marginal_rate_matches_the_double_count(changes):
    # marginal_tax_rate perturbs earnings by the same $1,000.
    c = changes[True]
    assert c["base"]["marginal_tax_rate"] == pytest.approx(
        1 - c["household_net_income"] / RAISE, abs=1e-4
    )
