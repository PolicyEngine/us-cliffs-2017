# Correction to our April 2025 cliff estimates

PolicyEngine, November 2026

## What we said

In April 2025 we estimated, for 2025:

- 7.4 million people face a cliff: their household's net income would fall if they earned $1,000 more;
- they live in 4.4 million households with 13.8 million people in all;
- 3.5% of workers face a cliff, before counting health coverage.

## What was wrong

A bug in the model version we ran, PolicyEngine-US 1.251.1 with policyengine-core 3.16.6, inflated the count of people facing a cliff about ninefold.

To test for a cliff, the model copies each household, raises one adult's earnings by $1,000 in the copy, and recomputes net income. Three variables in that version drew random numbers when the model ran on survey data: whether a person passes SSI's asset test (40% did), whether they would claim WIC, and whether they meet WIC's nutritional risk test. Each draw's random seed included a count of earlier draws, and the copy inherited that count. So the copy drew all three again with different seeds. In the copy, people lost SSI or WIC for reasons that had nothing to do with the raise, and the model read each loss as a cliff.

## How we know

We rebuilt the April 2025 environment: PolicyEngine-US 1.251.1 (commit c379969db9), policyengine-core 3.16.6 and the enhanced CPS 2024 file of that time (Hugging Face revision da98b4fa). The scripts are in [april2025/](april2025/).

| | People facing a cliff | Their households | People in those households | Share of workers |
|---|---|---|---|---|
| April 2025 figures | 7,360,124 | 4,382,835 | 13,811,117 | |
| Rerun of the April 2025 model | 7,360,124 | 4,382,835 | 13,811,117 | 2.33% |
| Same model, $0 raise | 10,531,402 | 6,003,770 | 20,459,159 | |
| Same model, random draws held fixed | 823,699 | 479,129 | 1,890,271 | 0.34% |

- **The rerun matches the April figures exactly.**
- **A raise of $0 should find no cliffs.** The April 2025 code finds 10.5 million, more than with the $1,000 raise. The redraws alone move household net income for 19.8 million of the 234 million adults the model tests.
- **Holding the draws fixed removes 89% of the count.** With the three variables fixed at their first draws, the same model and data find 0.82 million people facing a cliff, in 0.48 million households with 1.89 million people.
- **The losses came from SSI and WIC.** As published, SSI was the program whose loss lowered net income most for 5.7 million of the 7.4 million, and WIC for another 0.5 million. With the draws held, SNAP leads (378,000) followed by reduced-price school meals (346,000), and SSI drops to 32,000.

The rerun gives 4.04 million workers facing a cliff, 2.33% of the 174 million people with earnings. None of the 21 pairings of count and base we tried in that run gives 3.5%; the closest, people facing a cliff as a share of the adults the model tests, gives 3.14%. With the draws held, 0.34% of workers face a cliff.

## What changed in the model

In current PolicyEngine-US, the SSI asset test compares a person's countable resources with the limit, WIC's nutritional risk test reads an input, and the WIC claim draw no longer exists. policyengine-core now raises an error if any formula draws a random number, so a copied household can't redraw anything. The copy keeps every input and recomputes everything else, so it matches a fresh simulation of the same household with higher earnings; the tests in this repository check that.

## Corrected figures

[results/summary.md](results/summary.md) gives the current model's counts for 2025 and 2017, with and without health coverage. They differ from the "draws held" row above because the data changed (Microcosm replaced the enhanced CPS) and the model changed over the 18 months between versions; we haven't broken that difference down.
