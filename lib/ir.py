"""Document IR schema, IO, and projection logic (PLAN §9, docs/ir-schema.md).

``blocks.jsonl`` is the sole carrier of block content. ``assets.index.json`` and
``provenance.json`` are *projections* — regenerable from the blocks. The
projection functions live here so build_ir.py writes them and validate_ir.py
regenerates + compares with the SAME code, mechanically enforcing the contract.
"""
from __future__ import annotations

import json
from pathlib import Path

IR_SCHEMA_VERSION = "agent-document-ir/0.1"
ASSETS_INDEX_SCHEMA = "agent-ir-assets/0.1"
PROVENANCE_SCHEMA = "agent-ir-provenance/0.1"

BLOCK_TYPES = (
    "heading", "para", "list", "table", "figure", "formula", "code",
)
BLOCK_REQUIRED_FIELDS = ("id", "type", "source_anchor", "confidence", "needs_review")

# The structured sub-field each block type must carry (PLAN §9.1 "content 或结构化子字段").
TYPE_SUBFIELD = {
    "heading": "heading", "para": "content", "list": "content",
    "table": "table", "figure": "figure", "formula": "formula", "code": "code",
}

# Required keys per source_anchor kind (PLAN §9.2). Shared so build_ir (producer)
# and validate_provenance (checker) reference one vocabulary.
ANCHOR_REQUIRED_KEYS = {
    "pdf_page": ["source_file", "page"],
    "slide": ["source_file", "slide"],
    "sheet_range": ["source_file", "sheet"],
    "docx_anchor": ["source_file", "heading_path", "paragraph_index"],
    "text_anchor": ["source_file", "heading_path", "block_index"],
}
ANCHOR_KINDS = tuple(ANCHOR_REQUIRED_KEYS)

# bundle-relative IR file locations
IR_DOC = "ir/document.ir.json"
IR_BLOCKS = "ir/blocks.jsonl"
IR_ASSETS_INDEX = "ir/assets.index.json"
IR_PROVENANCE = "ir/provenance.json"


def new_block(block_id: str, btype: str, source_anchor: dict, *,
              confidence: float, needs_review: bool, **fields) -> dict:
    if btype not in BLOCK_TYPES:
        raise ValueError(f"unknown block type: {btype}")
    block = {
        "id": block_id,
        "type": btype,
        "source_anchor": source_anchor,
        "confidence": confidence,
        "needs_review": needs_review,
    }
    block.update(fields)
    return block


# ---- IO --------------------------------------------------------------------

def write_blocks(job_root: str | Path, blocks: list[dict]) -> None:
    p = Path(job_root) / IR_BLOCKS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for b in blocks:
            fh.write(json.dumps(b, ensure_ascii=False) + "\n")


def read_blocks(job_root: str | Path) -> list[dict]:
    p = Path(job_root) / IR_BLOCKS
    blocks: list[dict] = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                blocks.append(json.loads(line))
    return blocks


def write_json(path: str | Path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---- Projections (regenerable from blocks) ---------------------------------

def project_assets_index(blocks: list[dict], job_root: str | Path) -> dict:
    """asset_id -> {file, referenced_by, exists}, derived from figure blocks."""
    root = Path(job_root)
    assets: dict[str, dict] = {}
    for b in blocks:
        fig = b.get("figure")
        if not fig or not fig.get("asset_id"):
            continue
        aid = fig["asset_id"]
        entry = assets.setdefault(aid, {"file": fig.get("asset_file"), "referenced_by": [], "exists": False})
        entry["referenced_by"].append(b["id"])
    for aid, entry in assets.items():
        entry["referenced_by"].sort()
        entry["exists"] = bool(entry["file"]) and (root / entry["file"]).is_file()
    return {"schema_version": ASSETS_INDEX_SCHEMA, "assets": dict(sorted(assets.items()))}


def project_provenance(blocks: list[dict]) -> dict:
    """block_id -> source_anchor, for every block."""
    prov = {b["id"]: b.get("source_anchor") for b in blocks}
    return {"schema_version": PROVENANCE_SCHEMA, "blocks": dict(sorted(prov.items()))}


def canonical(data: dict) -> str:
    """Stable serialization for projection-equality checks."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


# ---- IR load/save (used by the Phase 2/3 transforms) -----------------------

def load_ir(job_root: str | Path) -> tuple[list[dict], dict]:
    blocks = read_blocks(job_root)
    doc = json.loads((Path(job_root) / IR_DOC).read_text(encoding="utf-8"))
    return blocks, doc


def recompute_stats(blocks: list[dict]) -> dict:
    by: dict[str, int] = {}
    for b in blocks:
        by[b["type"]] = by.get(b["type"], 0) + 1
    asset_ids = {b["figure"]["asset_id"] for b in blocks
                 if b["type"] == "figure" and (b.get("figure") or {}).get("asset_id")}
    return {
        "block_count": len(blocks),
        "asset_count": len(asset_ids),
        "table_count": by.get("table", 0), "figure_count": by.get("figure", 0),
        "formula_count": by.get("formula", 0), "heading_count": by.get("heading", 0),
    }


def save_all(job_root: str | Path, blocks: list[dict], doc: dict) -> None:
    """Write blocks + document.ir.json (stats refreshed) + both projections."""
    root = Path(job_root)
    doc["stats"] = recompute_stats(blocks)
    doc["block_order"] = [b["id"] for b in blocks]
    write_blocks(root, blocks)
    write_json(root / IR_DOC, doc)
    write_json(root / IR_ASSETS_INDEX, project_assets_index(blocks, root))
    write_json(root / IR_PROVENANCE, project_provenance(blocks))
