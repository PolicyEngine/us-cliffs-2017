# Correction to our April 2025 cliff estimates

PolicyEngine, November 2026

## What we said

In April 2025 we estimated that, in 2025, 7.4 million people would see their household's net income fall if they earned $1,000 more. We estimated that they lived in 4.4 million households with 13.8 million people in all, and that 3.5% of workers faced such a cliff before counting health coverage.

## What went wrong

A bug in the model version we ran, PolicyEngine-US 1.251.1 with policyengine-core 3.16.6, inflated the count of people facing a cliff about ninefold.

To test for a cliff, the model copies each household, raises one adult's earnings by $1,000 in the copy, and recomputes net income. It tests the two adults with the highest market income in each household, so every person it counts is an adult. Three variables in that version drew random numbers when the model ran on survey data: whether a person passes SSI's asset test (each person had a 40% chance), whether they would claim WIC, and whether they meet WIC's nutritional risk test. Each draw's random seed included a count of earlier draws, and the copy inherited that count, so it drew all three again with different seeds. In the copy, people lost SSI or WIC for reasons that had nothing to do with the raise, and the model read each loss as a cliff.

## How we know

We rebuilt the model and data current on the day of the estimate: PolicyEngine-US 1.251.1 (commit c379969db9, the main branch on 16 April 2025), policyengine-core 3.16.6 and the enhanced CPS 2024 file (Hugging Face revision da98b4fa, the last upload before the estimate). The scripts are in [april2025/](april2025/).

| | Adults facing a cliff | Their households | People in those households | Share of workers facing a cliff |
|---|---|---|---|---|
| April 2025 estimate | 7.4 million | 4.4 million | 13.8 million | 3.5% |
| Rerun of the April 2025 model | 7.36 million | 4.38 million | 13.81 million | 2.33% |
| Same model, $0 raise | 10.53 million | 6.00 million | 20.46 million | |
| Same model, $0 raise, random draws held fixed | {NULL_HELD_ADULTS} | {NULL_HELD_HOUSEHOLDS} | {NULL_HELD_PEOPLE} | |
| Same model, random draws held fixed | about 0.8 million | about 0.5 million | about 1.9 million | 0.34% |

- **The rerun reproduces our April 2025 calculation** of 7,360,124 adults, 4,382,835 households and 13,811,117 people to within one person.
- **A raise of $0 should find no cliffs.** The April 2025 code finds 10.5 million, more than with the $1,000 raise, because the raise's own gain in net income absorbs the smaller spurious losses. The redraws alone move household net income for 19.8 million of the 234 million adults the model tests. With the draws held fixed, a $0 raise {NULL_HELD_SENTENCE}.
- **Holding the draws fixed removes about 89% of the count.** The same model and data then find about 0.8 million adults facing a cliff, in about 0.5 million households with 1.9 million people. Few survey households carry that count: {HELD_SAMPLE_ADULTS} sample adults in {HELD_SAMPLE_HOUSEHOLDS} households, two of which supply {HELD_TOP2_SHARE} of the weighted total. Its 95% interval runs from {HELD_LO} to {HELD_HI} million adults, and the published count exceeds it by a factor of {RATIO_LO} to {RATIO_HI}. The count describes the April 2025 model without the bug; the current model's counts below are our corrected estimates.
- **The spurious losses came from SSI and WIC.** As published, SSI was the program whose loss lowered net income most for 5.7 million of the 7.4 million adults, and WIC for another 0.5 million.

The rerun gives 4.04 million workers facing a cliff, 2.33% of the 174 million people with earnings. None of the 21 pairings of count and base we tried in that run gives 3.5%; the closest, adults facing a cliff as a share of the adults the model tests, gives 3.14%. With the draws held, 0.34% of workers face a cliff.

## What changed in the model

In current PolicyEngine-US, the SSI asset test compares a person's countable resources with the limit, WIC's nutritional risk test reads an input, and the WIC claim draw no longer exists. policyengine-core now raises an error if any formula draws a random number, so a copied household can't redraw anything. The copy keeps every input and recomputes everything else, so it matches a fresh simulation of the same household with higher earnings; the tests in this repository check that.

## Corrected figures

[results/summary.md](results/summary.md) gives the current model's counts for 2025 and 2017, with and without health coverage. They differ from the "draws held fixed" row above because the data changed (Microcosm replaced the enhanced CPS) and the model changed over the 18 months between versions; we haven't broken that difference down.
