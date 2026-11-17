"""Fill generated exhibits and verified aggregate values into the manuscript."""

import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
text = (root / "manuscript.tmpl.md").read_text()
values = json.loads((root / "template_values.json").read_text())


def replace(match):
    key = match.group(1)
    if key not in values:
        raise ValueError(f"Missing manuscript value: {key}")
    return values[key]


text = re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", replace, text)
if "{{" in text or "[[" in text:
    raise ValueError("Unfilled placeholder")
(root / "manuscript.md").write_text(text)
print(
    f"Filled manuscript: {len(text.split()):,} whitespace-delimited words including tables and references"
)
