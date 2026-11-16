# PolicyEngine paper edition

`manuscript.pdf` uses the canonical PolicyEngine pe-doc wordmark, Inter fonts
and palette. It presents the same article body as the canonical manuscript.
`../build_policyengine.py` derives this source and renders it through pe-doc.

```sh
uv run --project .. python ../build_policyengine.py
pe-doc check manuscript.md
```

The `proposal` front-matter kind selects pe-doc's general branded document
layout; this artifact is a research paper. The journal-format PDF and editable
Word source remain in `../submission/`.
