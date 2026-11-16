"""Check paper integrity without running a tax-benefit simulation."""

import hashlib
import json
import re
from pathlib import Path

from build_assets import verify
from pypdf import PdfReader

root = Path(__file__).resolve().parent
checks = verify()
manuscript = (root / "manuscript.md").read_text()
template = (root / "manuscript.tmpl.md").read_text()
values = json.loads((root / "template_values.json").read_text())
expected = re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", lambda m: values[m.group(1)], template)
assert manuscript == expected, "Filled source differs from the canonical template"
assert "{{" not in manuscript and "[[" not in manuscript
for private_pattern in (
    r"(?i)\bclient\b",
    r"(?i)\bfee\b",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
):
    assert not re.search(private_pattern, manuscript), (
        "Private commercial context found"
    )
assert "Appendix B describes the implications" in manuscript
assert "frozen 2025 model scenario" in manuscript
assert (
    "Setting a simulation year to 2017 therefore does not reconstruct missing 2017 law"
    in manuscript
)
assert "own-year nominal dollars" in manuscript
metrics = json.loads((root / "paper_metrics.json").read_text())
for year in ("2017", "2025"):
    for size in (1000, 2000, 5000):
        for resource in ("cash", "health"):
            rate = metrics[f"worker_rate_{year}_{size}_{resource}"]
            assert (
                rate["operation"]
                == "divide two aggregates from the same completed scenario"
            )
source_cache = {}
for key, metric in metrics.items():
    if not key.startswith("archive:"):
        continue
    source = metric["source"]
    if source not in source_cache:
        source_cache[source] = json.loads((root / "inputs" / source).read_text())
    item = source_cache[source]
    for part in metric["json_pointer"].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        item = item[int(part)] if isinstance(item, list) else item[part]
    assert item == metric["value"], f"Unresolvable metric provenance: {key}"
assert any("either_side" in key for key in metrics)
assert any("net_income_moves_12_or_less" in key for key in metrics)
assert any("medicaid_value_scaled_counted_once" in key for key in metrics)
assert any("precision_summary.json" in key for key in metrics)
pdf = root / "submission" / "manuscript.pdf"
assert pdf.stat().st_mtime >= (root / "manuscript.md").stat().st_mtime, (
    "PDF predates source"
)
reader = PdfReader(pdf)
text = "\n".join(page.extract_text() or "" for page in reader.pages)
assert 12 <= len(reader.pages) <= 60
assert re.search(r"(?m)^Cliffs\s*$", reader.pages[0].extract_text() or "")
assert 'title: "Cliffs"' in manuscript
assert reader.metadata.title == "Cliffs"
assert "commissioned related benefit-cliff analysis" in text and "Funding and competing interests" in text
assert "Appendix C" in text and "References" in text
assert "{{" not in text and "[[" not in text
figures = re.findall(r"!\[[^\]]*\]\((figures/[^)]+)\)", manuscript)
assert len(figures) == 6 and len(set(figures)) == 6
assert re.findall(r"\*\*Figure ([A-Z]?\d+):", manuscript) == [
    "1",
    "2",
    "3",
    "4",
    "5",
    "B1",
]
figure_receipt = json.loads((root / "checks/figure-provenance.json").read_text())
figure_inputs = {
    "household-curves/paper_household_curves.json",
    "results/earnings_changes.json",
    "robustness/ijm_saved_robustness.json",
}
assert set(figure_receipt["input_sources"]) == figure_inputs
for source, expected_hash in figure_receipt["input_sources"].items():
    assert (
        hashlib.sha256((root / "inputs" / source).read_bytes()).hexdigest()
        == expected_hash
    )
assert (
    figure_receipt["household_source_sha256"]
    == figure_receipt["input_sources"]["household-curves/paper_household_curves.json"]
)
for name, expected_hash in figure_receipt["files"].items():
    assert (
        hashlib.sha256((root / "figures" / name).read_bytes()).hexdigest()
        == expected_hash
    )
assert (
    figure_receipt["figure_source_sha256"]
    == hashlib.sha256((root / "build_figures.py").read_bytes()).hexdigest()
)
for figure in figures:
    assert (root / figure).is_file()
    assert (root / figure).read_bytes() == (root / "policyengine" / figure).read_bytes()
for label in ("Figure 1", "Figure 2", "Figure 3", "Figure 4", "Figure 5", "Figure B1"):
    assert label in text, f"Figure caption missing from PDF: {label}"
abstract = manuscript.split("## Abstract", 1)[1].split("**Keywords:**", 1)[0]
assert len(abstract.split()) <= 250
keywords = manuscript.split("**Keywords:**", 1)[1].split("\n", 1)[0].split(",")
assert len(keywords) <= 4
assert len(manuscript.split()) < 15000
assert re.findall(r"\*\*Table ([A-Z]?\d+):", manuscript) == [
    "1",
    "2",
    "3",
    "4",
    "5",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
]
assert manuscript.index("## References") < manuscript.index("## Appendix A")
assert "Ghenis, M., & Woodruff, N." in manuscript
assert "�" not in text, "Replacement glyph in PDF text"
assert all(len(page.extract_text() or "") > 250 for page in reader.pages), (
    "Unexpected nearly empty page"
)
branded_pdf = root / "manuscript.pdf"
branded_receipt = json.loads((root / "checks/pe-format.json").read_text())
assert (
    branded_receipt["canonical_source_sha256"]
    == hashlib.sha256(manuscript.encode()).hexdigest()
)
assert (
    branded_receipt["journal_pdf_sha256"]
    == hashlib.sha256(pdf.read_bytes()).hexdigest()
)
assert (
    branded_receipt["branded_pdf_sha256"]
    == hashlib.sha256(branded_pdf.read_bytes()).hexdigest()
)
assert branded_pdf.read_bytes() == (root / "policyengine/manuscript.pdf").read_bytes()
branded_reader = PdfReader(branded_pdf)
branded_text = "\n".join(page.extract_text() or "" for page in branded_reader.pages)
for label in ("Figure 1", "Figure 2", "Figure 3", "Figure 4", "Figure 5", "Figure B1"):
    assert label in branded_text, f"Figure caption missing from branded PDF: {label}"
report = checks | {
    "manuscript_sha256": hashlib.sha256(manuscript.encode()).hexdigest(),
    "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
    "pdf_pages": len(reader.pages),
    "metric_records": len(metrics),
    "template_matches": True,
    "figures_verified": len(figures),
    "branded_pdf_sha256": branded_receipt["branded_pdf_sha256"],
    "branded_pdf_pages": len(branded_reader.pages),
    "private_client_context_absent": True,
    "status": "PASS",
}
(root / "checks" / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
