# Vendored: doc-to-agent-markdown (Phase 1 extraction backend)

This directory is a **pinned snapshot** of the `doc-to-agent-markdown` skill, used
as the Phase 1 extraction/assembly backend (`lib/backend.py` resolves here by
default). It is vendored so the pipeline runs on a fresh clone of any machine —
without it, Phase 1 dies because the backend would otherwise live only on the
author's separate checkout.

## Snapshot provenance

| Field | Value |
| --- | --- |
| Source | `doc-to-agent-markdown` skill (separately maintained) |
| Snapshot date | 2026-06-13 |
| Files | `doc_to_md_extractor.py`, `doc_to_md_assembler.py`, `requirements.txt`, `SKILL.md` |

Snapshotted from the author's checkout. Because this duplicates a separately
maintained skill, **record the date above and the upstream SHA when you re-sync**
so drift is traceable.

### Pinned file hashes (sha256, snapshot 2026-06-13)

```
doc_to_md_extractor.py  868fbcc98a118232b2bfc5f8c382f8fdc39651a1d287068af39a7b1935acb414
doc_to_md_assembler.py  672799a8d8f2399154de8802ffd27bdbfa55fda45c253ad9d2a678692d9046b9
```

## What is NOT vendored

The backend's own `tests/` (and its `tests/_fixtures/`) are intentionally left
out — the `agent-friendly-md` integration tests build their own fixtures and only
require the extractor/assembler to be importable. The backend ships its own
regression suite upstream.

## Overriding the backend

The default points here, but resolution order in `lib/backend.py` is:

1. `--backend <dir>` CLI override,
2. `AFM_BACKEND_DIR` environment variable,
3. this vendored snapshot (`vendor/doc-to-agent-markdown/`).

Use #1/#2 to point at a newer working copy without editing code.

## Runtime dependencies

See `requirements.txt` here (mirrored into the repo-root `requirements.txt`):
`python-docx`, `PyMuPDF`, `openpyxl`, `python-pptx`, `Pillow`. `tools/doctor.py`
verifies both the backend's presence and these deps under the `extract` group.
