# Cliff counts

We weight each count up to a national total. The ± figure in parentheses gives half
the width of its 95% interval, 1.96 standard errors from a bootstrap that resamples
source households (sampling error only).
PolicyEngine-US tests the two adults with the highest market income in each
household, so we count only adults as facing a cliff. For the share of workers, we
divide the adults facing a cliff who have earnings (wages plus self-employment
income above zero) by everyone with earnings, including people the model
doesn't test. We leave the Commodity Supplemental Food Program out of the 2025 rows
(see the last section). In the rows counting health coverage, we count the premium
tax credit twice, as the model does when it computes net income. In the table after
this one, we count it once, as we do in our headline counts; we give the reason in
METHODOLOGY.md.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers | Mean cliff gap |
|---|---|---|---|---|---|---|
| 2017 rules, cash and near-cash only | 0.69M (± 0.24M) | 0.46M (± 0.15M) | 1.74M (± 0.61M) | 0.61M (± 0.22M) | 0.34% | $603 |
| 2017 rules, counting health coverage, premium tax credit counted twice | 2.75M (± 0.44M) | 2.03M (± 0.32M) | 6.39M (± 1.04M) | 2.38M (± 0.40M) | 1.34% | $8,256 |
| 2025 rules, cash and near-cash only | 0.68M (± 0.21M) | 0.45M (± 0.14M) | 1.85M (± 0.63M) | 0.52M (± 0.16M) | 0.28% | $1,125 |
| 2025 rules, counting health coverage, premium tax credit counted twice | 3.10M (± 0.48M) | 2.44M (± 0.38M) | 7.38M (± 1.25M) | 2.60M (± 0.43M) | 1.38% | $11,589 |

## Counting the premium tax credit once

When it counts health coverage in net income, PolicyEngine-US adds the premium tax
credit and subtracts the premium net of that credit, so a change in the credit
counts twice.
In these rows, we count it once.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers |
|---|---|---|---|---|---|
| 2017 rules, counting health coverage, premium tax credit counted once | 2.68M (± 0.43M) | 1.98M (± 0.31M) | 6.20M (± 1.02M) | 2.33M (± 0.39M) | 1.31% |
| 2025 rules, counting health coverage, premium tax credit counted once | 3.08M (± 0.47M) | 2.42M (± 0.38M) | 7.33M (± 1.25M) | 2.59M (± 0.42M) | 1.38% |

## Adults facing a cliff when we value Medicaid differently

PolicyEngine-US holds state Medicaid spending for 2020 through 2023 only, so the
2017 runs spread 2020 spending and the 2025 runs 2023 spending. In each column, we
scale every enrollee's Medicaid value by the factor in its heading. In these rows, we count
the premium tax credit twice, as the model does.

| Configuration | x0.8 | x0.9 | x1 | x1.1 | x1.2 |
|---|---|---|---|---|---|
| 2017 rules, counting health coverage, premium tax credit counted twice | 2.71M | 2.73M | 2.75M | 2.75M | 2.75M |
| 2025 rules, counting health coverage, premium tax credit counted twice | 3.10M | 3.10M | 3.10M | 3.10M | 3.10M |

## Valuing Medicaid differently and counting the premium tax credit once

scripts/counted_once.py rebuilds each part of the runs counting health coverage,
reproduces their counted-once counts and the table above, and scales every
enrollee's Medicaid value by each column's factor.

| Configuration | x0.8 | x0.9 | x1 | x1.1 | x1.2 |
|---|---|---|---|---|---|
| 2017 rules, counting health coverage, premium tax credit counted once | 2.65M | 2.66M | 2.68M | 2.69M | 2.69M |
| 2025 rules, counting health coverage, premium tax credit counted once | 3.08M | 3.08M | 3.08M | 3.08M | 3.08M |

## The premium tax credit as the largest loss

Under 2017 rules, counting health coverage, with the credit counted once, losing the credit lowers net income most for 0.06M adults (28 in the sample, from 17 survey households, 2 of which supply half; 95% interval 0.01M to 0.13M). For 0.06M (26 in the sample), the raise lifts their tax unit's income from below 400% of the poverty line to 400% or more; 0.06M (26) fail the credit's income test after the raise, and 0.06M (26) lose their tax unit's whole credit.

Under 2025 rules, counting health coverage, with the credit counted once, losing the credit lowers net income most for none of the adults facing a cliff.


## Medicaid's value against the spending it spreads ($ billions)

| Configuration | Medicaid value, full sample | State spending | Gap |
|---|---|---|---|
| 2017 rules, counting health coverage | 661.5 | 661.5 | 0.000% |
| 2025 rules, counting health coverage | 880.0 | 880.0 | 0.000% |

## What lowers net income most, for adults facing a cliff

scripts/driver_intervals.py gives each count and share a 95% interval: the 2.5th and
97.5th percentiles over 5,000 resamples of Microcosm's source households (sampling
error only). The last column counts the survey households that carry each count,
and in parentheses the fewest of them that supply half of it.

**2017 rules, cash and near-cash only**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| Reduced-price school meals | 0.24M | 0.12M to 0.38M | 34% | 19% to 50% | 88 (5) |
| TANF | 0.11M | 0.03M to 0.21M | 16% | 5% to 29% | 17 (3) |
| WIC | 0.08M | 0.00M to 0.21M | 12% | 0.2% to 27% | 15 (1) |
| SNAP | 0.07M | 0.01M to 0.14M | 9% | 1% to 20% | 32 (2) |
| Free school meals | 0.06M | 0.02M to 0.12M | 9% | 3% to 18% | 38 (3) |
| Taxes | 0.06M | 0.00M to 0.13M | 8% | 0.6% to 18% | 9 (2) |
| State benefits | 0.05M | 0.01M to 0.10M | 7% | 1% to 16% | 6 (2) |
| Refundable tax credits | 0.03M | 0.00M to 0.07M | 4% | <0.1% to 11% | 8 (1) |
| SSI | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |
| Housing assistance | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |

**2017 rules, counting health coverage, premium tax credit counted twice**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| Medicaid | 1.84M | 1.48M to 2.20M | 67% | 59% to 74% | 680 (37) |
| Reduced-price school meals | 0.25M | 0.13M to 0.39M | 9% | 5% to 14% | 92 (5) |
| Medicare Savings Programs | 0.15M | 0.05M to 0.28M | 5% | 2% to 10% | 39 (3) |
| ACA premium tax credit | 0.11M | 0.04M to 0.21M | 4% | 1% to 8% | 27 (3) |
| TANF | 0.11M | 0.04M to 0.21M | 4% | 1% to 8% | 18 (3) |
| SNAP | 0.07M | 0.01M to 0.14M | 2% | 0.4% to 5% | 31 (2) |
| Free school meals | 0.06M | 0.02M to 0.12M | 2% | 0.8% to 4% | 40 (3) |
| Taxes | 0.06M | 0.00M to 0.13M | 2% | 0.2% to 5% | 10 (2) |
| CHIP | 0.04M | 0.00M to 0.08M | 1% | 0.1% to 3% | 18 (2) |
| State benefits | 0.04M | 0.00M to 0.08M | 1% | <0.1% to 3% | 6 (2) |
| WIC | 0.01M | 0.00M to 0.03M | 0.4% | <0.1% to 1% | 6 (1) |
| Refundable tax credits | 0.01M | 0.00M to 0.03M | 0.4% | <0.1% to 1% | 10 (1) |
| CHIP premium | 0.01M | 0.00M to 0.02M | 0.3% | 0% to 1% | 1 (1) |
| Marketplace premium (net of credit) | 0.00M | 0.00M to 0.00M | <0.1% | <0.1% to <0.1% | 4 (1) |
| SSI | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |
| Housing assistance | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |

**2017 rules, counting health coverage, premium tax credit counted once**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| Medicaid | 1.83M | 1.48M to 2.20M | 68% | 61% to 75% | 679 (37) |
| Reduced-price school meals | 0.24M | 0.12M to 0.38M | 9% | 5% to 14% | 88 (5) |
| Medicare Savings Programs | 0.15M | 0.05M to 0.28M | 5% | 2% to 10% | 39 (3) |
| TANF | 0.11M | 0.03M to 0.21M | 4% | 1% to 8% | 17 (3) |
| SNAP | 0.07M | 0.01M to 0.14M | 2% | 0.4% to 5% | 31 (2) |
| Free school meals | 0.06M | 0.02M to 0.12M | 2% | 0.8% to 4% | 39 (3) |
| ACA premium tax credit | 0.06M | 0.01M to 0.13M | 2% | 0.3% to 5% | 17 (2) |
| Taxes | 0.06M | 0.00M to 0.13M | 2% | 0.2% to 5% | 9 (2) |
| CHIP | 0.04M | 0.01M to 0.09M | 2% | 0.3% to 4% | 19 (2) |
| State benefits | 0.04M | 0.00M to 0.08M | 1% | <0.1% to 3% | 5 (2) |
| WIC | 0.01M | 0.00M to 0.03M | 0.4% | <0.1% to 1% | 5 (1) |
| Refundable tax credits | 0.01M | 0.00M to 0.03M | 0.4% | <0.1% to 1% | 6 (1) |
| CHIP premium | 0.01M | 0.00M to 0.02M | 0.3% | 0% to 1% | 1 (1) |
| SSI | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |
| Housing assistance | 0.00M | 0.00M to 0.00M | <0.1% | 0% to <0.1% | 1 (1) |

**2025 rules, cash and near-cash only**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| SNAP | 0.19M | 0.09M to 0.30M | 28% | 15% to 41% | 73 (5) |
| TANF | 0.11M | 0.03M to 0.21M | 16% | 5% to 29% | 12 (3) |
| Free school meals | 0.11M | 0.02M to 0.23M | 16% | 4% to 30% | 59 (2) |
| Reduced-price school meals | 0.08M | 0.03M to 0.14M | 12% | 4% to 21% | 55 (3) |
| Refundable tax credits | 0.07M | 0.02M to 0.13M | 10% | 3% to 18% | 31 (3) |
| WIC | 0.05M | 0.01M to 0.11M | 8% | 2% to 16% | 20 (2) |
| Taxes | 0.05M | 0.00M to 0.12M | 7% | <0.1% to 16% | 15 (2) |
| SSI | 0.02M | 0.00M to 0.04M | 2% | 0% to 7% | 2 (1) |
| State benefits | 0.02M | 0.00M to 0.05M | 2% | <0.1% to 7% | 8 (1) |

**2025 rules, counting health coverage, premium tax credit counted twice**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| Medicaid | 2.24M | 1.82M to 2.67M | 72% | 65% to 78% | 535 (43) |
| SNAP | 0.18M | 0.09M to 0.29M | 6% | 3% to 9% | 67 (5) |
| Medicare Savings Programs | 0.14M | 0.05M to 0.25M | 4% | 2% to 8% | 30 (3) |
| TANF | 0.12M | 0.04M to 0.22M | 4% | 1% to 7% | 13 (3) |
| Free school meals | 0.11M | 0.02M to 0.23M | 3% | 0.8% to 7% | 59 (2) |
| Refundable tax credits | 0.08M | 0.03M to 0.15M | 3% | 0.9% to 5% | 34 (3) |
| Reduced-price school meals | 0.08M | 0.03M to 0.14M | 3% | 1% to 5% | 56 (3) |
| CHIP | 0.05M | 0.01M to 0.10M | 2% | 0.4% to 3% | 17 (3) |
| Taxes | 0.05M | 0.00M to 0.12M | 2% | <0.1% to 4% | 15 (2) |
| CHIP premium | 0.02M | 0.00M to 0.07M | 0.7% | 0% to 2% | 2 (1) |
| WIC | 0.02M | 0.00M to 0.04M | 0.5% | <0.1% to 1% | 5 (1) |
| State benefits | 0.02M | 0.00M to 0.05M | 0.5% | <0.1% to 2% | 7 (1) |
| SSI | 0.01M | 0.00M to 0.04M | 0.4% | 0% to 1% | 1 (1) |

**2025 rules, counting health coverage, premium tax credit counted once**

| Largest loss | Adults | 95% interval | Share | 95% interval | Survey households |
|---|---|---|---|---|---|
| Medicaid | 2.24M | 1.82M to 2.67M | 73% | 66% to 79% | 535 (43) |
| SNAP | 0.18M | 0.09M to 0.29M | 6% | 3% to 9% | 67 (5) |
| Medicare Savings Programs | 0.14M | 0.05M to 0.25M | 4% | 2% to 8% | 30 (3) |
| TANF | 0.11M | 0.03M to 0.21M | 4% | 1% to 7% | 12 (3) |
| Free school meals | 0.11M | 0.02M to 0.23M | 3% | 0.8% to 7% | 58 (2) |
| Reduced-price school meals | 0.08M | 0.03M to 0.14M | 3% | 1% to 5% | 56 (3) |
| Refundable tax credits | 0.07M | 0.02M to 0.13M | 2% | 0.7% to 4% | 32 (3) |
| CHIP | 0.05M | 0.01M to 0.10M | 2% | 0.4% to 3% | 18 (3) |
| Taxes | 0.05M | 0.00M to 0.12M | 2% | <0.1% to 4% | 15 (2) |
| CHIP premium | 0.02M | 0.00M to 0.07M | 0.7% | 0% to 2% | 2 (1) |
| WIC | 0.02M | 0.00M to 0.04M | 0.5% | <0.1% to 1% | 5 (1) |
| State benefits | 0.02M | 0.00M to 0.05M | 0.5% | <0.1% to 2% | 7 (1) |
| SSI | 0.01M | 0.00M to 0.04M | 0.4% | 0% to 1% | 1 (1) |

## Cliffs that rest on benefits the model gives to everyone eligible

Microcosm supplies take-up for SNAP, SSI, TANF, WIC, housing assistance, Head Start,
Medicaid, Medicare, the ACA premium tax credit and the EITC.
We set WIC take-up from the draw Microcosm stores, as policyengine.py does
(cliffs2017/wic_take_up.py). PolicyEngine-US gives free and reduced-price school meals,
most state child care subsidies, CHIP, Medicare Savings Programs and several state
health programs to everyone eligible. It counts school meals for every K-12 child in an
eligible family on all 180 school days. In each cell, scripts/take_up_bounds.py counts
the adults facing a cliff whose cliff would disappear if that benefit didn't change
with the raise. If some families don't take up these benefits, only some of the cliffs
in each cell would disappear. The state benefits column also holds state supplements
to SSI. Some states pay these only to SSI recipients, so those supplements follow
Microcosm's SSI take-up, and the column overstates the cliffs that rest on full
take-up. When a raise
ends Medicaid for someone in a household, the model can start their CHIP or Medicare
Savings Program instead. A household that didn't take that coverage up would lose the
offset, so the model can also miss cliffs. The per-person files hold only cliff rows,
so we can't count those. In the rows counting health coverage, we count the premium
tax credit once.

| Configuration | Adults facing a cliff | School meals | State benefits | CHIP | Medicare Savings Programs | State health programs | Any of these |
|---|---|---|---|---|---|---|---|
| 2017 rules, cash and near-cash only | 0.69M | 0.30M (44%) | 0.05M (7%) | – | – | – | 0.35M (51%) |
| 2017 rules, counting health coverage, premium tax credit counted once | 2.68M | 0.30M (11%) | 0.04M (1%) | 0.05M (2%) | 0.15M (5%) | 0.00M (0%) | 0.54M (20%) |
| 2025 rules, cash and near-cash only | 0.68M | 0.11M (16%) | 0.02M (2%) | – | – | – | 0.12M (18%) |
| 2025 rules, counting health coverage, premium tax credit counted once | 3.08M | 0.11M (4%) | 0.02M (0.5%) | 0.07M (2%) | 0.14M (4%) | 0.00M (0%) | 0.33M (11%) |

## Program totals in each run ($ billions)

| Program | 2017 rules, cash and near-cash only | 2017 rules, counting health coverage | 2025 rules, cash and near-cash only | 2025 rules, counting health coverage |
|---|---|---|---|---|
| Household net income (household_net_income) | 10,737.2 | 11,414.5 | 16,370.6 | 17,318.2 |
| All household benefits (household_benefits) | 1,324.9 | 2,030.5 | 1,945.2 | 2,912.6 |
| ACA premium tax credit before take-up (aca_ptc) | 80.3 | 80.3 | 170.0 | 170.0 |
| EITC (eitc) | 56.8 | 56.8 | 68.9 | 68.9 |
| SNAP (snap) | 56.4 | 56.4 | 98.8 | 98.8 |
| SSI (ssi) | 42.1 | 42.1 | 55.5 | 55.5 |
| ACA premium tax credit after take-up (assigned_aca_ptc) | 25.6 | 25.6 | 60.6 | 60.6 |
| Refundable child tax credit (refundable_ctc) | 22.8 | 22.8 | 40.1 | 40.1 |
| Free school meals (free_school_meals) | 14.4 | 14.4 | 31.7 | 31.7 |
| CHIP (chip) | 9.0 | 9.0 | 11.8 | 11.8 |
| Housing assistance (housing_assistance) | 5.5 | 5.5 | 5.7 | 5.7 |
| State benefits (household_state_benefits) | 5.0 | 5.0 | 7.0 | 7.0 |
| WIC (wic) | 4.1 | 4.1 | 6.6 | 6.6 |
| TANF (tanf) | 3.3 | 3.3 | 5.4 | 5.4 |
| Reduced-price school meals (reduced_price_school_meals) | 2.8 | 2.8 | 1.7 | 1.7 |
| Head Start (household_head_start_benefits) | 0.0 | 0.0 | 0.0 | 0.0 |
| Medicaid (medicaid_cost) | – | 661.5 | – | 880.0 |

assigned_aca_ptc multiplies aca_ptc by takes_up_aca_if_eligible. When we count health
coverage, net income includes assigned_aca_ptc, which the tables above label the ACA
premium tax credit.

The runs without health coverage leave out Medicaid's value: they don't hold
Medicaid's full-sample state totals, and we leave Medicaid out of their net income.

## Counting the Commodity Supplemental Food Program

From 2024, PolicyEngine-US counts the Commodity Supplemental Food Program (CSFP) in
household benefits and gives its food package to everyone the program's rules admit.
Weighting up a 25% household sample, we find that the model gives 8.4 million people a package in 2025, at $5.0 billion. It values each package at $601, the program's 2025 cost of $425 million divided by its 707,000 participants.
A 2017 run reads the model's earlier list, which has no CSFP, so we leave CSFP out of
the main 2025 rows as well (cliffs2017/benefits.py). In these rows, we count it as the
model does.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers |
|---|---|---|---|---|---|
| 2025 rules, cash and near-cash only, leaving CSFP out | 0.68M (± 0.21M) | 0.45M (± 0.14M) | 1.85M (± 0.63M) | 0.52M (± 0.16M) | 0.28% |
| 2025 rules, cash and near-cash only, counting CSFP | 0.85M (± 0.23M) | 0.54M (± 0.15M) | 2.04M (± 0.64M) | 0.57M (± 0.17M) | 0.31% |
| 2025 rules, counting health coverage, premium tax credit counted twice, leaving CSFP out | 3.10M (± 0.48M) | 2.44M (± 0.38M) | 7.38M (± 1.25M) | 2.60M (± 0.43M) | 1.38% |
| 2025 rules, counting health coverage, premium tax credit counted twice, counting CSFP | 3.27M (± 0.48M) | 2.53M (± 0.38M) | 7.58M (± 1.25M) | 2.65M (± 0.43M) | 1.41% |
| 2025 rules, counting health coverage, premium tax credit counted once, leaving CSFP out | 3.08M (± 0.47M) | 2.42M (± 0.38M) | 7.33M (± 1.25M) | 2.59M (± 0.42M) | 1.38% |
| 2025 rules, counting health coverage, premium tax credit counted once, counting CSFP | 3.25M (± 0.48M) | 2.52M (± 0.38M) | 7.53M (± 1.24M) | 2.64M (± 0.43M) | 1.41% |

When we count CSFP, losing it lowers net income most for 0.17M of the 0.85M adults facing a cliff under 2025 rules, cash and near-cash only.

When we count CSFP, losing it lowers net income most for 0.17M of the 3.27M adults facing a cliff under 2025 rules, counting health coverage.
