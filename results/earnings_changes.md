# Cliffs under other changes in earnings

Written by scripts/earnings_changes_summary.py from the parts that scripts/earnings_changes.py
writes; commit 30045d6. Each row repeats the cliff test with another change in the
earnings of each household's two highest-income adults. Under a raise we count the adults whose
household's net income falls; under a cut, the adults whose household's net income rises. A raise
in dollars reaches every measured adult; a cut in dollars, only adults whose earnings reach it; a
change in proportion to earnings, only adults with earnings. "Counting health coverage" counts
the premium tax credit once. Intervals: 95%, from resampling source households, sampling error only.
The +$1,000 rows reproduce the final runs. "Versus +$1,000" is each count minus the +$1,000
count, with a paired interval from the same resamples. "Moves $12 or less" counts the adults
flagged whose net income moves by $12 a year or less, the size of SNAP's rounding step.

## 2017 federal rules

Before health coverage:

| Change | Adults reached | Adults flagged | 95% interval | Share of adults reached | Share of workers | Versus +$1,000 | 95% interval | Moves $12 or less |
|---|---:|---:|---|---:|---:|---:|---|---:|
| +1,000 | 211.12M | 0.69M | 0.48M to 0.93M | 0.33% | 0.34% | +0k | +0k to +0k | 7k |
| -1,000 | 151.53M | 0.51M | 0.35M to 0.69M | 0.34% | 0.29% | -181k | -464k to +94k | 8k |
| +2,000 | 211.12M | 0.67M | 0.45M to 0.90M | 0.32% | 0.30% | -24k | -266k to +208k | 13k |
| -2,000 | 149.20M | 0.47M | 0.32M to 0.64M | 0.31% | 0.26% | -223k | -500k to +44k | 2k |
| +5,000 | 211.12M | 0.30M | 0.18M to 0.44M | 0.14% | 0.13% | -392k | -647k to -149k | 7k |
| -5,000 | 143.08M | 0.23M | 0.12M to 0.35M | 0.16% | 0.13% | -466k | -715k to -225k | 16k |
| +1% | 154.28M | 0.50M | 0.35M to 0.66M | 0.33% | 0.28% | -189k | -447k to +52k | 134k |
| -1% | 154.28M | 0.53M | 0.38M to 0.70M | 0.34% | 0.30% | -160k | -439k to +113k | 124k |
| +10% | 154.28M | 0.43M | 0.29M to 0.59M | 0.28% | 0.24% | -257k | -487k to -44k | 40k |
| -10% | 154.28M | 0.46M | 0.31M to 0.64M | 0.30% | 0.26% | -230k | -508k to +36k | 17k |

Counting health coverage:

| Change | Adults reached | Adults flagged | 95% interval | Share of adults reached | Share of workers | Versus +$1,000 | 95% interval | Moves $12 or less |
|---|---:|---:|---|---:|---:|---:|---|---:|
| +1,000 | 211.12M | 2.68M | 2.25M to 3.11M | 1.27% | 1.31% | +0k | +0k to +0k | 15k |
| -1,000 | 151.53M | 2.22M | 1.87M to 2.59M | 1.46% | 1.25% | -462k | -1,018k to +105k | 8k |
| +2,000 | 211.12M | 4.39M | 3.82M to 4.96M | 2.08% | 2.13% | +1,712k | +1,312k to +2,124k | 13k |
| -2,000 | 149.20M | 3.66M | 3.19M to 4.16M | 2.45% | 2.06% | +983k | +358k to +1,618k | 2k |
| +5,000 | 211.12M | 9.42M | 8.59M to 10.27M | 4.46% | 4.48% | +6,737k | +5,963k to +7,545k | 28k |
| -5,000 | 143.08M | 7.21M | 6.50M to 7.95M | 5.04% | 4.05% | +4,530k | +3,720k to +5,383k | 3k |
| +1% | 154.28M | 0.83M | 0.64M to 1.04M | 0.54% | 0.47% | -1,851k | -2,257k to -1,446k | 127k |
| -1% | 154.28M | 0.97M | 0.77M to 1.20M | 0.63% | 0.55% | -1,705k | -2,189k to -1,231k | 124k |
| +10% | 154.28M | 3.38M | 2.94M to 3.83M | 2.19% | 1.90% | +698k | +337k to +1,054k | 40k |
| -10% | 154.28M | 3.88M | 3.42M to 4.35M | 2.51% | 2.18% | +1,197k | +589k to +1,806k | 17k |


Households and their members:

| Change | Before: households | Before: members | Counting health: households | Counting health: members |
|---|---:|---:|---:|---:|
| +1,000 | 0.46M | 1.74M | 1.98M | 6.20M |
| -1,000 | 0.42M | 1.63M | 1.86M | 6.41M |
| +2,000 | 0.43M | 1.84M | 3.22M | 10.22M |
| -2,000 | 0.35M | 1.46M | 3.05M | 10.29M |
| +5,000 | 0.23M | 0.77M | 7.15M | 21.67M |
| -5,000 | 0.19M | 0.77M | 6.03M | 20.34M |
| +1% | 0.49M | 1.52M | 0.80M | 2.51M |
| -1% | 0.49M | 1.89M | 0.87M | 3.16M |
| +10% | 0.43M | 1.57M | 3.07M | 10.85M |
| -10% | 0.44M | 1.71M | 3.54M | 12.75M |

Either side, for each raise and the cut of the same size (adults whose household loses from
the raise or gains from the cut):

| Sizes | Before health coverage | 95% interval | Counting health coverage | 95% interval |
|---|---:|---|---:|---|
| +1,000 / -1,000 | 1.17M | 0.90M to 1.45M | 4.84M | 4.27M to 5.40M |
| +2,000 / -2,000 | 1.10M | 0.84M to 1.39M | 7.90M | 7.12M to 8.67M |
| +5,000 / -5,000 | 0.50M | 0.35M to 0.69M | 16.25M | 15.16M to 17.37M |
| +1% / -1% | 0.98M | 0.77M to 1.21M | 1.74M | 1.46M to 2.06M |
| +10% / -10% | 0.86M | 0.65M to 1.09M | 7.06M | 6.41M to 7.72M |

Raise against the cut of the same size: the raise's count minus the cut's, then the raise
counted only among the adults the cut reaches, minus the cut (paired 95% intervals):

| Sizes | Measure | Raise minus cut | 95% interval | Raise where the cut reaches | Minus cut | 95% interval |
|---|---|---:|---|---:|---:|---|
| +1,000 / -1,000 | before health coverage | +181k | -94k to +464k | 0.60M | +89k | -173k to +363k |
| +1,000 / -1,000 | counting health coverage | +462k | -105k to +1,018k | 2.31M | +90k | -435k to +614k |
| +2,000 / -2,000 | before health coverage | +199k | -76k to +469k | 0.52M | +51k | -198k to +284k |
| +2,000 / -2,000 | counting health coverage | +730k | +17k to +1,452k | 3.70M | +38k | -627k to +708k |
| +5,000 / -5,000 | before health coverage | +74k | -91k to +240k | 0.21M | -16k | -165k to +133k |
| +5,000 / -5,000 | counting health coverage | +2,207k | +1,170k to +3,307k | 7.42M | +206k | -749k to +1,177k |
| +1% / -1% | before health coverage | -29k | -250k to +185k | 0.50M | -29k | -250k to +185k |
| +1% / -1% | counting health coverage | -146k | -444k to +134k | 0.83M | -146k | -444k to +134k |
| +10% / -10% | before health coverage | -27k | -248k to +188k | 0.43M | -27k | -248k to +188k |
| +10% / -10% | counting health coverage | -499k | -1,104k to +102k | 3.38M | -499k | -1,104k to +102k |

400% of the poverty line (adults whose tax unit crosses it with the change):

| Change | Cross 400% | Lose (raise) or gain (cut) the whole credit | Of those crossing, cliff counting health | 95% interval | Credit moves most, all adults on a cliff | 95% interval |
|---|---:|---:|---:|---|---:|---|
| +1,000 | 1,669k (689) | 94k (32) | 60k (26) | 8k to 127k | 60k (28) | 8k to 127k |
| -1,000 | 1,133k (438) | 46k (16) | 46k (18) | 2k to 106k | 58k (19) | 7k to 120k |
| +2,000 | 3,141k (1352) | 151k (57) | 117k (47) | 18k to 245k | 117k (47) | 18k to 245k |
| -2,000 | 2,322k (881) | 137k (32) | 140k (34) | 50k to 249k | 124k (30) | 39k to 229k |
| +5,000 | 7,609k (3503) | 459k (152) | 172k (89) | 76k to 288k | 172k (88) | 76k to 288k |
| -5,000 | 5,202k (2114) | 347k (86) | 206k (59) | 101k to 327k | 189k (55) | 87k to 308k |
| +1% | 495k (179) | 13k (8) | 13k (8) | 0k to 35k | 23k (18) | 1k to 53k |
| -1% | 422k (186) | 43k (9) | 56k (10) | 6k to 120k | 57k (25) | 6k to 123k |
| +10% | 4,066k (1771) | 297k (83) | 85k (41) | 27k to 157k | 72k (38) | 19k to 141k |
| -10% | 4,526k (1939) | 245k (68) | 158k (44) | 78k to 258k | 141k (41) | 65k to 233k |

Sample adults in parentheses.

The part that moves net income most against the change, before health coverage (share of the count):

| Change | First | Second | Third |
|---|---|---|---|
| +1,000 | reduced_price_school_meals 34% | tanf 16% | wic 12% |
| -1,000 | reduced_price_school_meals 42% | free_school_meals 15% | snap 11% |
| +2,000 | reduced_price_school_meals 45% | free_school_meals 14% | snap 13% |
| -2,000 | reduced_price_school_meals 32% | free_school_meals 16% | snap 15% |
| +5,000 | tanf 37% | snap 24% | ssi 19% |
| -5,000 | ssi 29% | snap 26% | tanf 17% |
| +1% | household_tax_before_refundable_credits 34% | snap 20% | reduced_price_school_meals 16% |
| -1% | household_tax_before_refundable_credits 22% | free_school_meals 18% | reduced_price_school_meals 14% |
| +10% | reduced_price_school_meals 26% | household_tax_before_refundable_credits 23% | snap 13% |
| -10% | household_tax_before_refundable_credits 22% | reduced_price_school_meals 21% | snap 17% |

The part that moves net income most against the change, counting health coverage (share of the count):

| Change | First | Second | Third |
|---|---|---|---|
| +1,000 | medicaid_cost 68% | reduced_price_school_meals 9% | msp_cost 5% |
| -1,000 | medicaid_cost 68% | reduced_price_school_meals 10% | msp_cost 6% |
| +2,000 | medicaid_cost 71% | msp_cost 9% | reduced_price_school_meals 7% |
| -2,000 | medicaid_cost 79% | msp_cost 5% | reduced_price_school_meals 4% |
| +5,000 | medicaid_cost 91% | msp_cost 2% | chip 2% |
| -5,000 | medicaid_cost 92% | assigned_aca_ptc 3% | chip 2% |
| +1% | medicaid_cost 38% | household_tax_before_refundable_credits 21% | snap 12% |
| -1% | medicaid_cost 32% | household_tax_before_refundable_credits 12% | free_school_meals 10% |
| +10% | medicaid_cost 80% | msp_cost 4% | reduced_price_school_meals 3% |
| -10% | medicaid_cost 80% | msp_cost 4% | assigned_aca_ptc 4% |

## 2025 rules

Before health coverage:

| Change | Adults reached | Adults flagged | 95% interval | Share of adults reached | Share of workers | Versus +$1,000 | 95% interval | Moves $12 or less |
|---|---:|---:|---|---:|---:|---:|---|---:|
| +1,000 | 222.97M | 0.68M | 0.49M to 0.90M | 0.31% | 0.28% | +0k | +0k to +0k | 0k |
| -1,000 | 160.67M | 0.72M | 0.51M to 0.94M | 0.45% | 0.38% | +35k | -234k to +304k | 16k |
| +2,000 | 222.97M | 0.89M | 0.63M to 1.18M | 0.40% | 0.36% | +206k | -11k to +450k | 0k |
| -2,000 | 158.81M | 0.65M | 0.46M to 0.85M | 0.41% | 0.34% | -36k | -267k to +203k | 10k |
| +5,000 | 222.97M | 0.63M | 0.44M to 0.84M | 0.28% | 0.28% | -51k | -301k to +197k | 5k |
| -5,000 | 154.00M | 0.33M | 0.20M to 0.47M | 0.21% | 0.18% | -353k | -577k to -146k | 0k |
| +1% | 162.91M | 0.58M | 0.42M to 0.76M | 0.35% | 0.31% | -106k | -306k to +96k | 105k |
| -1% | 162.91M | 0.55M | 0.39M to 0.73M | 0.34% | 0.29% | -133k | -381k to +112k | 83k |
| +10% | 162.91M | 0.58M | 0.43M to 0.75M | 0.36% | 0.31% | -100k | -296k to +83k | 8k |
| -10% | 162.91M | 0.42M | 0.28M to 0.58M | 0.26% | 0.23% | -260k | -469k to -54k | 0k |

Counting health coverage:

| Change | Adults reached | Adults flagged | 95% interval | Share of adults reached | Share of workers | Versus +$1,000 | 95% interval | Moves $12 or less |
|---|---:|---:|---|---:|---:|---:|---|---:|
| +1,000 | 222.97M | 3.08M | 2.62M to 3.58M | 1.38% | 1.38% | +0k | +0k to +0k | 0k |
| -1,000 | 160.67M | 1.84M | 1.50M to 2.22M | 1.15% | 0.98% | -1,235k | -1,807k to -649k | 16k |
| +2,000 | 222.97M | 4.89M | 4.28M to 5.53M | 2.19% | 2.11% | +1,808k | +1,415k to +2,208k | 0k |
| -2,000 | 158.81M | 2.98M | 2.54M to 3.43M | 1.88% | 1.59% | -101k | -718k to +518k | 17k |
| +5,000 | 222.97M | 9.74M | 8.87M to 10.66M | 4.37% | 4.29% | +6,659k | +5,929k to +7,413k | 17k |
| -5,000 | 154.00M | 5.51M | 4.89M to 6.16M | 3.58% | 2.93% | +2,428k | +1,662k to +3,192k | 0k |
| +1% | 162.91M | 0.96M | 0.75M to 1.19M | 0.59% | 0.51% | -2,119k | -2,584k to -1,691k | 94k |
| -1% | 162.91M | 0.97M | 0.74M to 1.22M | 0.60% | 0.52% | -2,110k | -2,634k to -1,591k | 100k |
| +10% | 162.91M | 4.82M | 4.28M to 5.38M | 2.96% | 2.56% | +1,737k | +1,319k to +2,131k | 8k |
| -10% | 162.91M | 3.66M | 3.20M to 4.16M | 2.25% | 1.95% | +586k | -55k to +1,247k | 0k |


Households and their members:

| Change | Before: households | Before: members | Counting health: households | Counting health: members |
|---|---:|---:|---:|---:|
| +1,000 | 0.45M | 1.85M | 2.42M | 7.33M |
| -1,000 | 0.62M | 2.09M | 1.56M | 4.85M |
| +2,000 | 0.55M | 2.18M | 3.76M | 11.67M |
| -2,000 | 0.55M | 2.03M | 2.58M | 8.14M |
| +5,000 | 0.42M | 1.74M | 7.51M | 23.05M |
| -5,000 | 0.28M | 1.24M | 4.80M | 15.65M |
| +1% | 0.54M | 2.01M | 0.89M | 3.20M |
| -1% | 0.53M | 1.60M | 0.92M | 2.79M |
| +10% | 0.55M | 2.30M | 4.45M | 15.30M |
| -10% | 0.39M | 1.68M | 3.38M | 11.78M |

Either side, for each raise and the cut of the same size (adults whose household loses from
the raise or gains from the cut):

| Sizes | Before health coverage | 95% interval | Counting health coverage | 95% interval |
|---|---:|---|---:|---|
| +1,000 / -1,000 | 1.30M | 1.02M to 1.59M | 4.81M | 4.21M to 5.43M |
| +2,000 / -2,000 | 1.38M | 1.07M to 1.72M | 7.62M | 6.89M to 8.38M |
| +5,000 / -5,000 | 0.92M | 0.69M to 1.17M | 14.72M | 13.63M to 15.81M |
| +1% / -1% | 1.03M | 0.82M to 1.28M | 1.83M | 1.53M to 2.16M |
| +10% / -10% | 0.91M | 0.70M to 1.13M | 8.07M | 7.37M to 8.81M |

Raise against the cut of the same size: the raise's count minus the cut's, then the raise
counted only among the adults the cut reaches, minus the cut (paired 95% intervals):

| Sizes | Measure | Raise minus cut | 95% interval | Raise where the cut reaches | Minus cut | 95% interval |
|---|---|---:|---|---:|---:|---|
| +1,000 / -1,000 | before health coverage | -35k | -304k to +234k | 0.52M | -199k | -451k to +40k |
| +1,000 / -1,000 | counting health coverage | +1,235k | +649k to +1,807k | 2.56M | +713k | +171k to +1,235k |
| +2,000 / -2,000 | before health coverage | +241k | -52k to +543k | 0.67M | +25k | -231k to +285k |
| +2,000 / -2,000 | counting health coverage | +1,909k | +1,151k to +2,643k | 3.92M | +941k | +274k to +1,595k |
| +5,000 / -5,000 | before health coverage | +302k | +76k to +541k | 0.51M | +181k | -25k to +391k |
| +5,000 / -5,000 | counting health coverage | +4,231k | +3,170k to +5,262k | 7.81M | +2,304k | +1,373k to +3,223k |
| +1% / -1% | before health coverage | +27k | -197k to +251k | 0.58M | +27k | -197k to +251k |
| +1% / -1% | counting health coverage | -9k | -317k to +296k | 0.96M | -9k | -317k to +296k |
| +10% / -10% | before health coverage | +160k | -33k to +345k | 0.58M | +160k | -33k to +345k |
| +10% / -10% | counting health coverage | +1,152k | +479k to +1,835k | 4.82M | +1,152k | +479k to +1,835k |

400% of the poverty line (adults whose tax unit crosses it with the change):

Under these rules the 400% line ends no credit: PolicyEngine-US's gov.aca.ptc_income_eligibility
admits incomes above it from 2021 through 2025, and aca_required_contribution_percentage holds the
required contribution at 8.5% of income there. A credit that ends for these adults ends because
8.5% of the tax unit's income reaches its benchmark premium.

| Change | Cross 400% | Lose (raise) or gain (cut) the whole credit | Of those crossing, cliff counting health | 95% interval | Credit moves most, all adults on a cliff | 95% interval |
|---|---:|---:|---:|---|---:|---|
| +1,000 | 936k (475) | 0k (0) | 0k (0) | 0k to 0k | 0k (0) | 0k to 0k |
| -1,000 | 1,093k (337) | 0k (0) | 0k (0) | 0k to 0k | 0k (0) | 0k to 0k |
| +2,000 | 1,888k (976) | 0k (0) | 0k (0) | 0k to 0k | 0k (0) | 0k to 0k |
| -2,000 | 1,820k (646) | 0k (0) | 0k (0) | 0k to 0k | 0k (0) | 0k to 0k |
| +5,000 | 5,585k (2562) | 11k (2) | 11k (6) | 0k to 33k | 0k (0) | 0k to 0k |
| -5,000 | 4,141k (1614) | 0k (0) | 0k (2) | 0k to 0k | 0k (0) | 0k to 0k |
| +1% | 263k (158) | 0k (0) | 0k (0) | 0k to 0k | 2k (1) | 0k to 6k |
| -1% | 554k (198) | 0k (0) | 0k (0) | 0k to 0k | 13k (1) | 0k to 40k |
| +10% | 3,909k (1814) | 0k (1) | 11k (3) | 0k to 33k | 0k (0) | 0k to 0k |
| -10% | 4,666k (1928) | 0k (0) | 0k (4) | 0k to 0k | 0k (0) | 0k to 0k |

Sample adults in parentheses.

The part that moves net income most against the change, before health coverage (share of the count):

| Change | First | Second | Third |
|---|---|---|---|
| +1,000 | snap 28% | tanf 16% | free_school_meals 16% |
| -1,000 | free_school_meals 28% | reduced_price_school_meals 19% | snap 15% |
| +2,000 | snap 40% | tanf 20% | free_school_meals 16% |
| -2,000 | snap 28% | reduced_price_school_meals 24% | tanf 14% |
| +5,000 | snap 46% | tanf 22% | ssi 10% |
| -5,000 | snap 43% | tanf 16% | household_state_benefits 14% |
| +1% | snap 36% | household_tax_before_refundable_credits 16% | household_refundable_tax_credits 14% |
| -1% | snap 22% | free_school_meals 20% | household_tax_before_refundable_credits 16% |
| +10% | snap 50% | tanf 15% | reduced_price_school_meals 9% |
| -10% | snap 28% | tanf 19% | household_tax_before_refundable_credits 19% |

The part that moves net income most against the change, counting health coverage (share of the count):

| Change | First | Second | Third |
|---|---|---|---|
| +1,000 | medicaid_cost 73% | snap 6% | msp_cost 4% |
| -1,000 | medicaid_cost 57% | free_school_meals 11% | reduced_price_school_meals 8% |
| +2,000 | medicaid_cost 75% | msp_cost 7% | snap 6% |
| -2,000 | medicaid_cost 71% | snap 6% | msp_cost 6% |
| +5,000 | medicaid_cost 89% | msp_cost 4% | chip 2% |
| -5,000 | medicaid_cost 92% | snap 2% | chip 1% |
| +1% | medicaid_cost 41% | snap 22% | household_tax_before_refundable_credits 10% |
| -1% | medicaid_cost 34% | snap 12% | free_school_meals 11% |
| +10% | medicaid_cost 85% | snap 4% | chip 3% |
| -10% | medicaid_cost 85% | msp_cost 3% | snap 3% |

