"""Package the paper and reproducible aggregate exhibits, excluding environments."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent
dest = root.parent / "benefit-cliffs-working-paper.zip"
included = []
with ZipFile(dest, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(p in {".venv", "__pycache__", ".ruff_cache"} for p in relative.parts):
            continue
        if relative.parts[0] == "checks" and path.suffix not in {".json", ".md"}:
            continue
        if path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        archive.write(path, Path("benefit-cliffs-working-paper") / relative)
        included.append(str(relative))
record = {
    "archive": dest.name,
    "bytes": dest.stat().st_size,
    "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
    "files": included,
}
(root.parent / "paper-package.json").write_text(json.dumps(record, indent=2) + "\n")
print(
    json.dumps(
        {k: v for k, v in record.items() if k != "files"}
        | {"file_count": len(included)}
    )
)
