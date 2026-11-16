"""Build IJM Word files from the canonical filled Markdown, using Pandoc.

Run with the bundled Codex document Python (python-docx), not the model venv.
No data analysis or plot generation occurs here.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "submission"
OUT.mkdir(exist_ok=True)


def format_doc(path):
    doc = Document(path)
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = section.bottom_margin = Inches(1.5)
        section.left_margin = section.right_margin = Inches(1.5)
        section.header_distance = section.footer_distance = Inches(0.6)
        footer = section.footer.paragraphs[0]
        footer.alignment = 1
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)
    for style in doc.styles:
        if style.type in (1, 2):
            style.font.name = "Times New Roman"
            style.font.size = Pt(11)
            style.font.color.rgb = RGBColor(0, 0, 0)
            if style.element.rPr is not None:
                fonts = style.element.rPr.find(qn("w:rFonts"))
                if fonts is not None:
                    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
                        fonts.set(qn("w:" + attr), "Times New Roman")
        if style.type == 1:
            style.paragraph_format.line_spacing = 1.5
            style.paragraph_format.space_after = Pt(6)
    doc.styles["Title"].font.size = Pt(12)
    doc.styles["Title"].font.bold = True
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        doc.styles[name].font.size = Pt(12 if name == "Heading 1" else 11)
        doc.styles[name].font.bold = True
        doc.styles[name].paragraph_format.keep_with_next = True
    in_references = False
    for p in doc.paragraphs:
        p.paragraph_format.widow_control = True
        if p.text == "References":
            in_references = True
        elif p.text.startswith("Appendix A"):
            in_references = False
        elif in_references and p.text:
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.first_line_indent = Inches(-0.5)
        if p.text.startswith(("Table ", "Figure ")) or (p.text.startswith("**Table ")):
            p.paragraph_format.keep_with_next = True
        if p._p.xpath(".//w:drawing"):
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.alignment = 1
        if p.text.startswith("Notes:") or p.text.startswith("Source:"):
            p.paragraph_format.line_spacing = 1.5
            for r in p.runs:
                r.font.size = Pt(10)
        match = re.match(r"^\((\d+)\)\s+(.+)$", p.text)
        if match:
            from docx.enum.text import WD_TAB_ALIGNMENT

            p.paragraph_format.left_indent = Inches(0)
            p.paragraph_format.right_indent = Inches(0)
            p.paragraph_format.tab_stops.add_tab_stop(
                Inches(2.75), WD_TAB_ALIGNMENT.CENTER
            )
            p.paragraph_format.tab_stops.add_tab_stop(
                Inches(5.5), WD_TAB_ALIGNMENT.RIGHT
            )
            p.clear()
            p.add_run("\t" + match.group(2) + "\t(" + match.group(1) + ")")
        for r in p.runs:
            r.font.name = "Times New Roman"
            r.font.color.rgb = RGBColor(0, 0, 0)
    if doc.paragraphs:
        doc.paragraphs[0].style = doc.styles["Title"]
        doc.core_properties.title = doc.paragraphs[0].text
    for table in doc.tables:
        table.autofit = False
        columns = len(table.columns)
        widths = {
            3: [1.2, 2.2, 2.1],
            4: [1, 1.3, 1.5, 1.7],
            5: [0.7, 0.9, 1.4, 1.2, 1.3],
            6: [0.6, 0.8, 1.05, 1, 1.05, 1],
            7: [0.6, 0.8, 0.85, 0.8, 0.75, 0.9, 0.8],
        }.get(columns, [5.5 / columns] * columns)
        for col, width in zip(table.columns, widths):
            col.width = Inches(width)
        props = table._tbl.tblPr
        total_width = props.find(qn("w:tblW"))
        total_width.set(qn("w:type"), "dxa")
        total_width.set(qn("w:w"), "7920")
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement("w:" + edge)
            for attr, val in (("val", "nil"), ("sz", "0"), ("color", "000000")):
                e.set(qn("w:" + attr), val)
            borders.append(e)
        props.append(borders)
        for j, row in enumerate(table.rows):
            if j == 0:
                repeat = OxmlElement("w:tblHeader")
                row._tr.get_or_add_trPr().append(repeat)
            # Keep rows intact; allow the table itself to span pages.
            keep = OxmlElement("w:cantSplit")
            row._tr.get_or_add_trPr().append(keep)
            for k, cell in enumerate(row.cells):
                cell.width = Inches(widths[k])
                cell.vertical_alignment = 1
                tcpr = cell._tc.get_or_add_tcPr()
                margins = OxmlElement("w:tcMar")
                for edge in ("top", "bottom", "left", "right"):
                    e = OxmlElement("w:" + edge)
                    e.set(qn("w:w"), "65")
                    e.set(qn("w:type"), "dxa")
                    margins.append(e)
                tcpr.append(margins)
                if j > 0 and re.match(r"^\d+\.\d+ \(", cell.text):
                    cell.text = cell.text.replace(" (", "\n(", 1)
                if j == 0:
                    text = cell.text.replace("Scenario", "Year")
                    for old, new in [
                        ("Cash adults (m)", "Cash\nadults (m)"),
                        ("Health adults (m)", "Health\nadults (m)"),
                        ("95% interval", "95%\ninterval"),
                        ("Tested workers (m)", "Tested workers\n(m)"),
                        ("Cash rate (%)", "Cash rate\n(%)"),
                        ("Health rate (%)", "Health rate\n(%)"),
                        ("Households (m)", "Households\n(m)"),
                        ("Members (m)", "Members\n(m)"),
                        ("Loss <=$12 (000s)", "Loss ≤$12\n(000s)"),
                        ("Share of flags (%)", "Share of flags\n(%)"),
                    ]:
                        text = text.replace(old, new)
                    cell.text = text
                for p in cell.paragraphs:
                    p.paragraph_format.line_spacing = 1.5
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.keep_with_next = False
                    p.alignment = (
                        0 if k == 0 or "Source" in table.rows[0].cells[0].text else 1
                    )
                    for r in p.runs:
                        r.font.name = "Arial"
                        r.font.size = Pt(10)
                        r.font.color.rgb = RGBColor(0, 0, 0)
                        if j == 0:
                            r.font.bold = True
    for shape in doc.inline_shapes:
        if shape.width > Inches(5.5):
            shape.height = round(shape.height * Inches(5.5) / shape.width)
            shape.width = Inches(5.5)
    doc.save(path)


def build(markdown, destination):
    with tempfile.TemporaryDirectory(prefix="ijm-docx-") as temp:
        source = Path(temp) / "source.md"
        source.write_text(markdown)
        subprocess.run(
            [
                "pandoc",
                str(source),
                "--from=markdown-implicit_figures",
                "--to=docx",
                "--standalone",
                "--resource-path",
                str(ROOT),
                "--output",
                str(destination),
            ],
            check=True,
        )
    format_doc(destination)


if __name__ == "__main__":
    source = (ROOT / "manuscript.md").read_text()
    source = re.sub(r"^---\n.*?\n---\n", "", source, flags=re.DOTALL)
    build(source, OUT / "manuscript.docx")
    print(OUT / "manuscript.docx")
