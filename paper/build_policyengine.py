"""Render the canonical paper with PolicyEngine's pe-doc PDF template.

Only the title block and presentation metadata differ from the article source.
Journal-format artifacts in submission/ remain separate.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "policyengine"


def build() -> None:
    """Derive branded source, render it, and verify the official template."""
    original = (ROOT / "manuscript.md").read_text()
    front, body = re.match(r"^---\n(.*?)\n---\n(.*)$", original, re.DOTALL).groups()
    meta = yaml.safe_load(front)
    article = body[body.index("## Abstract") :]
    options = {
        "kind": "proposal",
        "title": meta["title"],
        "author": meta["author"],
        "lang": meta["lang"],
        "pe-doc": {
            "source_notes": False,
            "split_tables": True,
            "budget_widths": False,
            "psl_foundation": False,
            "max_pages": 40,
        },
    }
    title = f"# {meta['title']}\n\n"
    byline = f"{meta['author']} · PolicyEngine · 12 November 2026\n\n"
    rendered_source = (
        "---\n"
        + yaml.safe_dump(options, sort_keys=False)
        + "---\n\n"
        + title
        + byline
        + article
    )
    OUT.mkdir(exist_ok=True)
    # Keep relative figure references identical in both document sources.
    figure_directory = OUT / "figures"
    figure_directory.mkdir(exist_ok=True)
    for figure in (ROOT / "figures").glob("*.png"):
        (figure_directory / figure.name).write_bytes(figure.read_bytes())
    target = OUT / "manuscript.md"
    target.write_text(rendered_source)
    assert (
        target.read_text().split("## Abstract", 1)[1]
        == original.split("## Abstract", 1)[1]
    )
    subprocess.run(
        ["pe-doc", "build", str(target), "--formats", "html,pdf"], check=True
    )
    subprocess.run(["pe-doc", "check", str(target)], check=True)
    for suffix in ("pdf", "html"):
        (ROOT / f"manuscript.{suffix}").write_bytes(
            (OUT / f"manuscript.{suffix}").read_bytes()
        )
    report = {
        "article_body_identical": True,
        "canonical_source_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "branded_source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "branded_pdf_sha256": hashlib.sha256(
            (OUT / "manuscript.pdf").read_bytes()
        ).hexdigest(),
        "journal_pdf_sha256": hashlib.sha256(
            (ROOT / "submission/manuscript.pdf").read_bytes()
        ).hexdigest(),
        "renderer": subprocess.check_output(["pe-doc", "--version"], text=True).strip(),
        "pe_doc_check": "PASS",
    }
    (ROOT / "checks/pe-format.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    build()
