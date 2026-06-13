#!/usr/bin/env python3
"""Phase 2 — IR Build (v0.3): compile the extracted skeleton into Document IR.

    python3 scripts/run_python.py tools/build_ir.py --job "<job-dir>"

Parses extracted/text/<name>_skeleton.md + extract_meta.json into:
  ir/blocks.jsonl        — block content (sole carrier)
  ir/document.ir.json    — metadata, stores, block_order, relations, stats
  ir/assets.index.json   — projection (regenerable from blocks)
  ir/provenance.json     — projection (regenerable from blocks)

Block parsing lives in lib/skeleton_parser.py; this tool orchestrates load →
parse → assemble document.ir.json + projections → write.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.skeleton_parser import Parser  # noqa: E402

_CJK = re.compile(r"[一-鿿]")
GENERIC_TITLES = {"", "pdf", "doc", "docx", "document", "file", "unknown", "文档", "文件"}


def _clean_title(text: str) -> str:
    line = re.sub(r"\s+", " ", str(text)).strip(" #\t")
    line = re.sub(r"<!--.*?-->", "", line).strip()
    return line[:160].strip()


def _generic_title(text: str) -> bool:
    norm = re.sub(r"[\s_\-.:：/\\]+", "", _clean_title(text)).lower()
    return norm in GENERIC_TITLES or len(norm) <= 1


def _title_from_blocks(blocks: list[dict], fallback: str) -> str:
    for b in blocks:
        if b.get("type") == "heading":
            title = _clean_title((b.get("heading") or {}).get("text", ""))
            if title and not _generic_title(title):
                return title
    for b in blocks:
        if b.get("type") != "para":
            continue
        text = _clean_title((b.get("content") or {}).get("text", ""))
        if not text or text.startswith(">") or "www." in text or len(text) > 140:
            continue
        if not _generic_title(text):
            return text
    return fallback if not _generic_title(fallback) else "document"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build Document IR from extraction.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    state = js.load_state(job_root)
    meta_file = job_root / P.EXTRACT_META
    if not meta_file.is_file():
        print("[error] no extracted/extract_meta.json; run run_extraction first", file=sys.stderr)
        return 2
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] extract_meta unreadable: {e}", file=sys.stderr)
        return 1
    skel = job_root / meta.get("skeleton_file", "")
    if not skel.is_file():
        cands = sorted((job_root / P.EXTRACTED_TEXT).glob("*_skeleton.md"))
        if not cands:
            print("[error] no skeleton found", file=sys.stderr)
            return 2
        skel = cands[0]
    text = skel.read_text(encoding="utf-8", errors="replace")

    source_rel = (state.get("source_files") or [""])[0]
    parser = Parser(source_rel, meta.get("source_format", Path(source_rel).suffix))
    parser.parse(text)
    blocks = parser.blocks

    fallback_title = Path(source_rel).stem or state["document_profile"].get("primary_type", "document")
    title = _title_from_blocks(blocks, fallback_title)
    relations = [{"from": b["id"], "to": b["figure"]["asset_id"], "type": "uses_asset"}
                 for b in blocks if b["type"] == "figure"]
    by_type: dict[str, int] = defaultdict(int)
    for b in blocks:
        by_type[b["type"]] += 1
    doc_ir = {
        "schema_version": IR.IR_SCHEMA_VERSION,
        "document_id": state["job_id"].rsplit("-", 1)[0],
        "metadata": {
            "title": title,
            "source_type": meta.get("source_format", "").lstrip("."),
            "source_file": source_rel,
            "language": "zh-CN" if _CJK.search(text) else "en",
        },
        "stores": {"blocks": "blocks.jsonl", "assets_index": "assets.index.json", "provenance": "provenance.json"},
        "block_order": [b["id"] for b in blocks],
        "relations": relations,
        "stats": {
            "block_count": len(blocks),
            "asset_count": len({b["figure"]["asset_id"] for b in blocks if b["type"] == "figure"}),
            "table_count": by_type["table"], "figure_count": by_type["figure"],
            "formula_count": by_type["formula"], "heading_count": by_type["heading"],
        },
    }

    IR.write_blocks(job_root, blocks)
    IR.write_json(job_root / IR.IR_DOC, doc_ir)
    IR.write_json(job_root / IR.IR_ASSETS_INDEX, IR.project_assets_index(blocks, job_root))
    IR.write_json(job_root / IR.IR_PROVENANCE, IR.project_provenance(blocks))

    print(f"[ok] IR built: {len(blocks)} blocks "
          f"(table={by_type['table']} figure={by_type['figure']} formula={by_type['formula']})")
    print("     ir/blocks.jsonl, document.ir.json, assets.index.json, provenance.json")
    print("     next: Phase 2 gates ->")
    print(f'       {sys.executable} scripts/run_python.py validators/validate_ir.py --job "{job_root}"')
    print(f'       {sys.executable} scripts/run_python.py validators/validate_provenance.py --job "{job_root}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
