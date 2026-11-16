# Cliffs

Research article by Max Ghenis, PolicyEngine. The manuscript compares earnings
increments, health-resource accounting and units of counting in a frozen US
microsimulation. The main analysis uses a frozen 2025 model scenario; it does
not establish validated current-law effects. The appendix retains the mixed
2017-oriented sensitivity. All population results retain the selected-adult
coverage limits.

Read `manuscript.pdf` for the PolicyEngine-branded edition. The separate
`submission/manuscript.pdf` retains IJM formatting, and
`submission/manuscript.docx` supplies editable tables and embedded figure PNGs.
Edit `manuscript.tmpl.md`, not generated `manuscript.md`.

## Rebuild the PolicyEngine PDF

From `paper/`, after rebuilding the canonical manuscript and figures, run:

```sh
uv run python build_policyengine.py
```

This requires `pe-doc` on `PATH`. It uses PolicyEngine's canonical renderer and
checks its wordmark, fonts, links and pagination. The derived source lives in `policyengine/`; the
article body remains identical. The primary PDF/HTML use this edition, while
`submission/` retains the journal format.

## Rebuild the paper from saved inputs

Python 3.13, uv and Pandoc 3.11 are required. The lockfile fixes Python
packages. From `paper/`, rebuild tables, all six figures and Markdown without
microdata or a model run:

```sh
uv sync --frozen
uv run python build_assets.py
uv run python build_figures.py
uv run python fill_manuscript.py
uv run python build_submission.py
```

`build_submission.py` produces the journal DOCX. Render its PDF as described in
`RENDERING.md` before running `uv run python validate_paper.py`. Rebuild the
default PolicyEngine PDF with `uv run python build_policyengine.py`.

`build_figures.py` draws deterministic Matplotlib charts from verified saved
inputs; it computes no tax or benefit simulation. It writes PNG and SVG files
and `checks/figure-provenance.json`, recording source and output hashes. The
main figures are `household-single-2025`, `household-parent-2025`,
`household-endpoints-2025`, `increment-exposure` and
`health-valuation-exposure`. `household-aca-hybrid-2017` appears in the appendix.
The household snapshot contains 2,503 $100-grid points across three cases and
72 stored scalar checks. Straight lines connect evaluated points as visual
guides; the selected examples estimate no population prevalence.

`build_assets.py --include-figures` produces older two-scenario working-paper
plots; those are separate from the six article figures. `RENDERING.md`
documents fonts and both PDF renderers. Inspect every rendered page; a Word
font name alone does not establish that the PDF embeds that font.

## Regenerate the hypothetical-household calculations

This separate model step is not scheduled by `prepare_ijm_replication.py`.
From the repository root, use the simulation environment pinned in
`requirements-expanded.txt` (Python 3.13.13, PolicyEngine-US 2.116.0 and
PolicyEngine-core 3.34.10). Keep it separate from the paper's rendering
environment. On Max's machine, run through the required resource wrapper:

```sh
~/reviews/us-hub/scripts/heavy_run.sh paper-household-curves \
  .venv/bin/python scripts/paper_household_curves.py \
  --out results/paper_household_curves_rerun.json
```

Other sites should use an equivalent resource wrapper. The script runs one
worker, caps thread limits at two while preserving lower settings, and checks
the frozen package versions. It reads the saved national allocation totals in
`results/medicaid/totals_2017_p4_s0.json` and
`results/medicaid/totals_2025_p4_s0.json`; it loads no survey microdata.
It writes JSON and a companion Markdown summary, including household inputs,
component accounting checks, scalar comparisons and source/package identities.
Its default output is `results/paper_household_curves.json`; `--pilot` runs
exploratory sweeps rather than the final three-case calculation.

The article uses the separately hashed snapshot at
`inputs/household-curves/paper_household_curves.json`. A new run does not
replace that snapshot or its manifest automatically. Compare scientific
outputs and provenance before adopting a replacement; run timestamps and
runtime receipts can differ.

## Regenerate the underlying model results

The executable-source ZIP includes a self-contained Git bundle. Clone that
bundle at the exact branch and commit recorded in the package manifest before
using the preparer. A public repository clone at the same committed revision
also works. A plain source tree without Git metadata supports aggregate-only
rebuilding but cannot satisfy the simulation provenance checks.

From the committed source checkout:

```sh
python3 scripts/prepare_ijm_replication.py prepare /absolute/new/replication-directory
```

The destination must not already exist. Preparation copies committed source
into an independent Git checkout, separates archived comparison results, and
writes a serial `RUN.sh`. It does not execute the model or change the source
checkout. Read `PREPARE.json`, the generated command plan and `RUN.sh` before
starting the expensive stage. The runner installs the exact 83-package frozen
simulation environment with Python 3.13.13, verifies the public input bytes,
regenerates person-level intermediates, and compares original aggregates before
later summaries. It applies a narrowly verified source-tree equivalence proof
for the historical original runs; all original modules must retain identical
bytes and only the recorded, unused earnings-change module may differ.

The final saved-output postprocessor adds health revaluations, finite positive
raise unions and paired intervals. Its CSV inputs contain all selected adults,
including those without original losses. It does not read stored CSV weights;
MicroSeries and entity mapping apply calibrated weights. Full model execution
needs substantial memory (about 11 GB per original part) and time; the generated
plan runs one process at a time and preserves lower thread limits. On Max's
machine, the generated runner requires the configured heavy-run guard; other
researchers must explicitly supply a suitable resource wrapper.

Record-level CSVs are intermediate results and remain outside the public
package. The committed aggregates and paper inputs support direct comparison;
a successful aggregate build alone does not demonstrate a fresh national model
replication. `RUN_COMPLETED` records which comparisons actually passed.

## Data and provenance

- `inputs/manifest.json` hashes 90 archived files at source commit
  `ff0672e5f7f0728208599d988e9bd3cc2e195391`, including all 80 part/change
  aggregates and eight original-$1,000 replication flags.
- `public-inputs.json` gives the public finished microdata's resolved revisions,
  SHA-256 identifiers, byte counts and access classification. These inputs do
  not recreate the entire Microcosm build from upstream raw data.
- `paper_metrics.json` maps generated numerical values to source fields and
  records the derived-rate operations. Supplementary result snapshots carry a
  separate hash manifest.
- `inputs/household-curves/manifest.json` hashes the hypothetical-household
  snapshot and its simulation script; `checks/figure-provenance.json` hashes
  the six figures and their rendering source.
- `references.bib` and `literature-evidence.md` document verified primary
  literature and the conventions compared in the article.
- `software-assistance.json` records coding, analysis and writing assistance.
- `checks/validation.json` records artifact integrity and journal checks;
  local rendered-page images remain outside the distributable package.

The manuscript records PolicyEngine's general institutional support and
a client's commissioning of related analysis. The text is intended for CC BY
4.0 publication after author approval; analysis code retains the repository's
MIT license. The package contains no client correspondence or private review
transcripts. The manuscript has not been submitted to a journal.
