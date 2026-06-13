#!/usr/bin/env python3
"""Phase 3 — Semantic Compile: cross-page table linking (v0.5).

    python3 scripts/run_python.py tools/normalize_tables.py --job "<job-dir>"

Links consecutive table blocks that share the same column signature (a table
split across pages): sets continues_from / continues_to rather than physically
merging, so per-page provenance is preserved while assembly can render them as
one. Re-runs are idempotent (re-derives links from scratch).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import report  # noqa: E402


def _page_of(block: dict):
    """Location key as (kind, value); None only when no location at all.

    Explicit None check so a 0-valued page/slide is not treated as missing.
    """
    a = block.get("source_anchor") or {}
    for k in ("page", "slide", "sheet"):
        v = a.get(k)
        if v is not None:
            return (k, v)
    return None


def link_continued_tables(blocks: list[dict]) -> int:
    tables = [b for b in blocks if b["type"] == "table"]
    # reset prior links so re-runs are idempotent
    for t in tables:
        t["table"]["continues_from"] = None
        t["table"]["continues_to"] = None
    linked = 0
    for a, b in zip(tables, tables[1:]):
        same_cols = a["table"]["columns"] == b["table"]["columns"] and a["table"]["columns"]
        # a continuation: identical header on a different page/slide/sheet
        if same_cols and _page_of(a) != _page_of(b):
            a["table"]["continues_to"] = b["id"]
            b["table"]["continues_from"] = a["id"]
            linked += 1
    return linked


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Link cross-page continued tables.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / IR.IR_BLOCKS).is_file():
        print("[error] no IR; run build_ir first", file=sys.stderr)
        return 2
    try:
        blocks, doc = IR.load_ir(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1

    n = link_continued_tables(blocks)
    IR.save_all(job_root, blocks, doc)

    report.upsert_section(
        job_root / "review" / "semantic_compile.md", "Semantic Compile", "normalize_tables",
        f"- cross-page table links created: {n}")

    print(f"[ok] normalize_tables: cross-page links={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
