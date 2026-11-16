# Paper rendering

The default `manuscript.pdf` uses PolicyEngine's canonical `pe-doc` template.
Run `uv run python build_policyengine.py` from `paper/` after rebuilding the
filled manuscript and figures. The builder checks the wordmark, embedded
fonts, links and pagination, and copies the branded PDF/HTML from
`policyengine/`. It preserves the article body from the abstract onward and
keeps the separate journal files in `submission/`.

## Figures

Run `uv run python build_figures.py` from `paper/` to draw all six article
figures from the saved household calculations and aggregate snapshots. This
Matplotlib renderer performs no tax-benefit simulation. It writes 300-dpi
PNGs, SVGs and the source/output hash receipt in
`checks/figure-provenance.json`. Both PDF editions embed the PNGs; the journal
DOCX keeps its tables editable. See `README.md` for the separate household
model rerun command and frozen-scenario limits.

## Journal edition

The journal manuscript uses Times New Roman 11pt, 1.5 line spacing and 1.5-inch
margins, with Arial 10pt editable tables and Times New Roman 10pt notes. It uses
six data-based Matplotlib figures, alongside editable tables. The Word source
contains the specified font names; the PDF must embed those actual fonts
rather than a replacement. `software-assistance.json` records AI assistance
with code and manuscript preparation.

`build_submission.py` converts filled Markdown and embeds figure PNGs with
Pandoc, then applies Word styles and table geometry through python-docx 1.2.0.
The exact Python dependency
set appears in `uv.lock`. Pandoc 3.11 generated this version. Font licensing
belongs to the font provider; the replication ZIP does not distribute Microsoft
or Apple fonts. Install a licensed Times New Roman font before rendering.

The supplied PDF was rendered using the Codex bundled headless LibreOffice
runtime, with a separate temporary profile. On macOS that renderer required an
explicit task-local Fontconfig file including
`/System/Library/Fonts/Supplemental` to find Times New Roman. A DOCX font-name
check alone does not detect substitution. Verify the resulting PDF using
`pdffonts` and inspect its page images.

The host-specific runtime paths and private render configuration do not enter
statistical estimates. They are not required to rebuild the numerical tables or
Word source or plotted values. Any equivalent renderer must preserve the
journal's typography, spacing, margins, equations, figure captions and table
layout; PDF bytes can differ across renderers and installed fonts. Render the
updated DOCX to `submission/manuscript.pdf`, then run
`uv run python validate_paper.py` from `paper/`. Inspect all page images at
native resolution for clipped tables, figures, captions and missing glyphs.
