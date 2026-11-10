# Cliff counts

Each count is a weighted national total. Parentheses give 95% intervals
from a bootstrap that resamples source households (sampling error only).
PolicyEngine-US tests the two adults with the highest market income in each
household, so everyone counted as facing a cliff is an adult. Share of workers
divides the adults facing a cliff who have earnings (wages plus self-employment
income above zero) by everyone with earnings, including people the model
doesn't test. The 2025 rows leave out the Commodity Supplemental Food Program
(see the last section). The rows counting health coverage count the premium tax
credit twice, as the model does; the next table counts it once.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers | Mean cliff gap |
|---|---|---|---|---|---|---|
| 2017 rules, cash and near-cash only | 0.70M (± 0.24M) | 0.47M (± 0.15M) | 1.76M (± 0.61M) | 0.61M (± 0.22M) | 0.34% | $608 |
| 2017 rules, counting health coverage | 2.75M (± 0.44M) | 2.03M (± 0.32M) | 6.39M (± 1.04M) | 2.38M (± 0.40M) | 1.34% | $8,268 |
| 2025 rules, cash and near-cash only | 0.69M (± 0.21M) | 0.45M (± 0.14M) | 1.85M (± 0.63M) | 0.52M (± 0.16M) | 0.28% | $1,135 |
| 2025 rules, counting health coverage | 3.10M (± 0.48M) | 2.44M (± 0.38M) | 7.38M (± 1.25M) | 2.60M (± 0.43M) | 1.38% | $11,594 |

## Premium tax credit counted once

PolicyEngine-US's health-inclusive net income adds the premium tax credit and
subtracts the premium net of that credit, so a change in the credit counts twice.
These rows count it once.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers |
|---|---|---|---|---|---|
| 2017 rules, counting health coverage | 2.68M (± 0.43M) | 1.98M (± 0.31M) | 6.20M (± 1.02M) | 2.33M (± 0.39M) | 1.31% |
| 2025 rules, counting health coverage | 3.08M (± 0.47M) | 2.42M (± 0.38M) | 7.33M (± 1.25M) | 2.59M (± 0.42M) | 1.38% |

## Adults facing a cliff with Medicaid valued differently

PolicyEngine-US holds state Medicaid spending for 2020 through 2023 only, so the
2017 runs spread 2020 spending and the 2025 runs 2023 spending. Each column
scales every enrollee's Medicaid value by the factor shown. These rows count the
premium tax credit twice, as the model does.

| Configuration | x0.8 | x0.9 | x1 | x1.1 | x1.2 |
|---|---|---|---|---|---|
| 2017 rules, counting health coverage | 2.71M | 2.73M | 2.75M | 2.75M | 2.76M |
| 2025 rules, counting health coverage | 3.10M | 3.10M | 3.10M | 3.10M | 3.10M |

## Medicaid's value against the spending it spreads ($ billions)

| Configuration | Medicaid value, full sample | State spending | Gap |
|---|---|---|---|
| 2017 rules, counting health coverage | 661.5 | 661.5 | 0.000% |
| 2025 rules, counting health coverage | 880.0 | 880.0 | 0.000% |

## What lowers net income most, for adults facing a cliff

**2017 rules, cash and near-cash only**

| Largest loss | Adults | Share |
|---|---|---|
| Reduced-price school meals | 0.24M | 34% |
| TANF | 0.11M | 15% |
| WIC | 0.09M | 13% |
| SNAP | 0.07M | 9% |
| Free school meals | 0.06M | 9% |
| Taxes | 0.06M | 8% |
| State benefits | 0.05M | 7% |
| Refundable tax credits | 0.03M | 4% |
| SSI | 0.00M | 0% |
| Housing assistance | 0.00M | 0% |

**2017 rules, counting health coverage**

| Largest loss | Adults | Share |
|---|---|---|
| Medicaid | 1.84M | 67% |
| Reduced-price school meals | 0.25M | 9% |
| msp_cost | 0.15M | 5% |
| ACA premium tax credit | 0.11M | 4% |
| TANF | 0.11M | 4% |
| SNAP | 0.07M | 2% |
| Free school meals | 0.06M | 2% |
| Taxes | 0.06M | 2% |
| CHIP | 0.04M | 1% |
| State benefits | 0.04M | 1% |
| WIC | 0.01M | 0% |
| Refundable tax credits | 0.01M | 0% |
| CHIP premium | 0.01M | 0% |
| Marketplace premium (net of credit) | 0.00M | 0% |
| SSI | 0.00M | 0% |
| Housing assistance | 0.00M | 0% |

**2017 rules, counting health coverage, premium tax credit counted once**

| Largest loss | Adults | Share |
|---|---|---|
| Medicaid | 1.83M | 68% |
| Reduced-price school meals | 0.24M | 9% |
| msp_cost | 0.15M | 5% |
| TANF | 0.11M | 4% |
| SNAP | 0.07M | 2% |
| Free school meals | 0.06M | 2% |
| ACA premium tax credit | 0.06M | 2% |
| Taxes | 0.06M | 2% |
| CHIP | 0.04M | 2% |
| State benefits | 0.04M | 1% |
| WIC | 0.01M | 0% |
| Refundable tax credits | 0.01M | 0% |
| CHIP premium | 0.01M | 0% |
| SSI | 0.00M | 0% |
| Housing assistance | 0.00M | 0% |

**2025 rules, cash and near-cash only**

| Largest loss | Adults | Share |
|---|---|---|
| SNAP | 0.19M | 28% |
| TANF | 0.11M | 16% |
| Free school meals | 0.11M | 15% |
| Reduced-price school meals | 0.08M | 12% |
| Refundable tax credits | 0.07M | 10% |
| WIC | 0.06M | 8% |
| Taxes | 0.05M | 7% |
| SSI | 0.02M | 2% |
| State benefits | 0.02M | 2% |

**2025 rules, counting health coverage**

| Largest loss | Adults | Share |
|---|---|---|
| Medicaid | 2.24M | 72% |
| SNAP | 0.18M | 6% |
| msp_cost | 0.14M | 4% |
| TANF | 0.12M | 4% |
| Free school meals | 0.11M | 3% |
| Refundable tax credits | 0.08M | 3% |
| Reduced-price school meals | 0.08M | 3% |
| CHIP | 0.05M | 2% |
| Taxes | 0.05M | 2% |
| CHIP premium | 0.02M | 1% |
| WIC | 0.02M | 1% |
| State benefits | 0.02M | 0% |
| SSI | 0.01M | 0% |

**2025 rules, counting health coverage, premium tax credit counted once**

| Largest loss | Adults | Share |
|---|---|---|
| Medicaid | 2.24M | 73% |
| SNAP | 0.18M | 6% |
| msp_cost | 0.14M | 4% |
| TANF | 0.11M | 4% |
| Free school meals | 0.11M | 3% |
| Reduced-price school meals | 0.08M | 3% |
| Refundable tax credits | 0.07M | 2% |
| CHIP | 0.05M | 2% |
| Taxes | 0.05M | 2% |
| CHIP premium | 0.02M | 1% |
| WIC | 0.02M | 1% |
| State benefits | 0.02M | 0% |
| SSI | 0.01M | 0% |

## Program totals in each run ($ billions)

| Program | 2017 rules, cash and near-cash only | 2017 rules, counting health coverage | 2025 rules, cash and near-cash only | 2025 rules, counting health coverage |
|---|---|---|---|---|
| household_net_income | 10,740.0 | 11,417.3 | 16,375.5 | 17,323.1 |
| household_benefits | 1,327.8 | 2,033.3 | 1,950.1 | 2,917.5 |
| aca_ptc | 80.3 | 80.3 | 170.0 | 170.0 |
| eitc | 56.8 | 56.8 | 68.9 | 68.9 |
| snap | 56.4 | 56.4 | 98.8 | 98.8 |
| ssi | 42.1 | 42.1 | 55.5 | 55.5 |
| assigned_aca_ptc | 25.6 | 25.6 | 60.6 | 60.6 |
| refundable_ctc | 22.8 | 22.8 | 40.1 | 40.1 |
| free_school_meals | 14.4 | 14.4 | 31.7 | 31.7 |
| chip | 9.0 | 9.0 | 11.8 | 11.8 |
| wic | 6.9 | 6.9 | 11.5 | 11.5 |
| housing_assistance | 5.5 | 5.5 | 5.7 | 5.7 |
| household_state_benefits | 5.0 | 5.0 | 7.0 | 7.0 |
| tanf | 3.3 | 3.3 | 5.4 | 5.4 |
| reduced_price_school_meals | 2.8 | 2.8 | 1.7 | 1.7 |
| household_head_start_benefits | 0.0 | 0.0 | 0.0 | 0.0 |
| medicaid_cost | – | 661.5 | – | 880.0 |

The runs without health coverage leave out Medicaid's value: they don't hold
Medicaid's full-sample state totals, and their net income leaves Medicaid out.

## Counting the Commodity Supplemental Food Program

From 2024, PolicyEngine-US counts the Commodity Supplemental Food Program (CSFP) in
household benefits and gives its food package to everyone the program's rules admit.
Weighted up from a 25% household sample, the model gives 8.4 million people a package in 2025, at $5.0 billion. It values each package at $601, which divides the program's 2025 cost of $425 million by its 707,000 participants.
A 2017 run reads the model's earlier list, which has no CSFP, so the main rows leave CSFP
out of 2025 as well (cliffs2017/benefits.py). These rows count it as the model does.

| Configuration | Adults facing a cliff | Their households | Household members | Workers facing a cliff | Share of workers |
|---|---|---|---|---|---|
| 2025 rules, cash and near-cash only, leaving CSFP out | 0.69M (± 0.21M) | 0.45M (± 0.14M) | 1.85M (± 0.63M) | 0.52M (± 0.16M) | 0.28% |
| 2025 rules, cash and near-cash only, counting CSFP | 0.85M (± 0.23M) | 0.55M (± 0.15M) | 2.05M (± 0.64M) | 0.58M (± 0.17M) | 0.31% |
| 2025 rules, counting health coverage, leaving CSFP out | 3.10M (± 0.48M) | 2.44M (± 0.38M) | 7.38M (± 1.25M) | 2.60M (± 0.43M) | 1.38% |
| 2025 rules, counting health coverage, counting CSFP | 3.27M (± 0.48M) | 2.53M (± 0.38M) | 7.58M (± 1.25M) | 2.65M (± 0.43M) | 1.41% |
| 2025 rules, counting health coverage, leaving CSFP out, premium tax credit counted once | 3.08M (± 0.47M) | 2.42M (± 0.38M) | 7.33M (± 1.25M) | 2.59M (± 0.42M) | 1.38% |
| 2025 rules, counting health coverage, counting CSFP, premium tax credit counted once | 3.25M (± 0.48M) | 2.52M (± 0.38M) | 7.53M (± 1.24M) | 2.64M (± 0.43M) | 1.41% |

Counting CSFP, losing it lowers net income most for 0.17M of the 0.85M adults facing a cliff under 2025 rules, cash and near-cash only.

Counting CSFP, losing it lowers net income most for 0.17M of the 3.27M adults facing a cliff under 2025 rules, counting health coverage.
