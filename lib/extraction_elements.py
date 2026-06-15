"""Normalized Phase 1 extraction elements.

The current backend emits a skeleton Markdown file plus extract_meta.json. This
module provides the compatibility element layer described by the native
extraction router plan: existing skeleton output is mapped into elements now,
while future native backends can write the same element shape directly.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import ir as IR
from . import paths as P
from .skeleton_parser import Parser

ELEMENT_SCHEMA_VERSION = "agent-extraction-elements/0.1"

ELEMENT_TYPES = (
    "heading", "paragraph", "list", "table", "formula", "image", "chart",
    "note", "comment", "code",
)
EVIDENCE_LEVELS = ("native", "ocr", "vlm", "agent_reviewed")
HIGH_PRECISION_ANCHOR_FIELDS = (
    "bbox",
    "backend_element_id",
    "layout_zone",
    "shape_id",
    "z_order",
    "placeholder_type",
    "range",
    "line_range",
    "cell_ref",
    "table_index",
    "table_name",
    "named_range",
    "formula_cell",
    "chart_id",
    "comment_id",
    "image_rel_id",
)

BLOCK_TO_ELEMENT_TYPE = {
    "heading": "heading",
    "para": "paragraph",
    "list": "list",
    "table": "table",
    "figure": "image",
    "formula": "formula",
    "code": "code",
}
ELEMENT_TO_BLOCK_TYPE = {
    "heading": "heading",
    "paragraph": "para",
    "list": "list",
    "table": "table",
    "image": "figure",
    "chart": "figure",
    "formula": "formula",
    "code": "code",
    "note": "para",
    "comment": "para",
}

UNAVAILABLE_FIELDS_BY_FORMAT = {
    ".pdf": [
        "source_anchor.bbox",
        "source_anchor.backend_element_id",
        "source_anchor.coverage",
        "source_anchor.layout_zone",
    ],
    ".pptx": [
        "source_anchor.shape_id",
        "source_anchor.shape_name",
        "source_anchor.bbox",
        "source_anchor.placeholder_type",
        "source_anchor.z_order",
        "source_anchor.paragraph_index",
        "source_anchor.cell_ref",
    ],
    ".xlsx": [
        "source_anchor.range",
        "source_anchor.table_name",
        "source_anchor.named_range",
        "source_anchor.formula_cell",
        "source_anchor.chart_id",
    ],
    ".docx": [
        "source_anchor.table_index",
        "source_anchor.cell_ref",
        "source_anchor.comment_id",
        "source_anchor.image_rel_id",
    ],
    ".md": ["source_anchor.line_range"],
    ".txt": ["source_anchor.line_range"],
}


def normalize_source_type(source_format: str | None) -> str:
    value = str(source_format or "").strip().lower()
    if value.startswith("."):
        value = value[1:]
    aliases = {"markdown": "md", "text": "txt"}
    return aliases.get(value, value or "unknown")


def format_key(source_format: str | None) -> str:
    value = normalize_source_type(source_format)
    return f".{value}" if value and value != "unknown" else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _content_from_block(block: dict) -> Any:
    btype = block.get("type")
    if btype == "table":
        return {"title": block.get("title"), "table": _clone(block.get("table") or {})}
    if btype == "figure":
        return {"figure": _clone(block.get("figure") or {})}
    subfield = IR.TYPE_SUBFIELD.get(btype)
    return _clone(block.get(subfield) if subfield else {})


def _fields_from_element(element: dict) -> dict:
    etype = element.get("element_type")
    btype = ELEMENT_TO_BLOCK_TYPE.get(etype)
    content = element.get("content")
    if btype == "table":
        if isinstance(content, dict) and "table" in content:
            fields = {"table": content.get("table") or {}}
            if content.get("title") is not None:
                fields["title"] = content.get("title")
            return fields
        return {"table": content or {}}
    if btype == "figure":
        if isinstance(content, dict) and "figure" in content:
            return {"figure": content.get("figure") or {}}
        return {"figure": content or {}}
    subfield = IR.TYPE_SUBFIELD.get(btype or "")
    return {subfield: content if content is not None else {}} if subfield else {}


def elements_from_blocks(
    blocks: list[dict],
    source_format: str | None,
    *,
    compatibility_source: str = "skeleton",
) -> list[dict]:
    source_type = normalize_source_type(source_format)
    unavailable = UNAVAILABLE_FIELDS_BY_FORMAT.get(format_key(source_format), [])
    elements: list[dict] = []
    for idx, block in enumerate(blocks, start=1):
        btype = block.get("type")
        etype = BLOCK_TO_ELEMENT_TYPE.get(btype)
        if not etype:
            continue
        native_metadata = {
            "compatibility_source": compatibility_source,
            "ir_block_type": btype,
            "unavailable": list(unavailable),
        }
        if block.get("source_zone"):
            native_metadata["source_zone"] = block.get("source_zone")
        elements.append({
            "schema_version": ELEMENT_SCHEMA_VERSION,
            "element_id": f"element_{idx:06d}",
            "source_type": source_type,
            "element_type": etype,
            "content": _content_from_block(block),
            "source_anchor": _clone(block.get("source_anchor") or {}),
            "native_metadata": native_metadata,
            "evidence_level": block.get("evidence_level") or "native",
            "confidence": block.get("confidence"),
            "needs_review": block.get("needs_review"),
        })
    return elements


def elements_from_skeleton(text: str, source_rel: str, source_format: str | None) -> list[dict]:
    parser = Parser(source_rel, source_format or Path(source_rel).suffix)
    parser.parse(text)
    return elements_from_blocks(parser.blocks, source_format, compatibility_source="skeleton")


def blocks_from_elements(elements: list[dict]) -> list[dict]:
    counters: dict[str, int] = defaultdict(int)
    blocks: list[dict] = []
    for element in elements:
        btype = ELEMENT_TO_BLOCK_TYPE.get(element.get("element_type"))
        if not btype:
            raise ValueError(f"unknown element_type: {element.get('element_type')!r}")
        counters[btype] += 1
        block_id = f"block_{btype}_{counters[btype]:03d}"
        native_metadata = element.get("native_metadata") or {}
        block = IR.new_block(
            block_id,
            btype,
            element.get("source_anchor") or {},
            confidence=float(element.get("confidence")),
            needs_review=bool(element.get("needs_review")),
            evidence_level=element.get("evidence_level") or "native",
            **_fields_from_element(element),
        )
        if native_metadata.get("source_zone"):
            block["source_zone"] = native_metadata.get("source_zone")
        if native_metadata:
            block["extraction_metadata"] = native_metadata
        blocks.append(block)
    return blocks


def write_elements(job_root: str | Path, elements: list[dict]) -> None:
    path = Path(job_root) / P.EXTRACT_ELEMENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for element in elements:
            fh.write(json.dumps(element, ensure_ascii=False) + "\n")


def read_elements(job_root: str | Path) -> list[dict]:
    path = Path(job_root) / P.EXTRACT_ELEMENTS
    elements: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                elements.append(json.loads(line))
    return elements


def element_text_blob(elements: list[dict]) -> str:
    parts: list[str] = []
    for element in elements:
        content = element.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, dict):
            parts.append(json.dumps(content, ensure_ascii=False))
    return "\n".join(parts)


def meta_patch(elements: list[dict], source_format: str | None) -> dict:
    type_stats = Counter(e.get("element_type") for e in elements)
    evidence_stats = Counter(e.get("evidence_level") for e in elements)
    anchored = sum(1 for e in elements if e.get("source_anchor"))
    compatibility = Counter(
        (e.get("native_metadata") or {}).get("compatibility_source", "unknown")
        for e in elements
    )
    return {
        "extraction_element_schema": ELEMENT_SCHEMA_VERSION,
        "elements_file": P.EXTRACT_ELEMENTS,
        "element_count": len(elements),
        "element_type_stats": dict(sorted(type_stats.items())),
        "evidence_level_stats": dict(sorted(evidence_stats.items())),
        "coverage": {
            "source_type": normalize_source_type(source_format),
            "elements_with_source_anchor": anchored,
            "elements_without_source_anchor": len(elements) - anchored,
            "compatibility_sources": dict(sorted(compatibility.items())),
            "high_precision_fields": "unavailable_when_not_emitted_by_backend",
        },
    }


def update_extract_meta(meta: dict, elements: list[dict], source_format: str | None) -> dict:
    patched = dict(meta)
    backend = patched.get("backend")
    if isinstance(backend, dict):
        backend_info = dict(backend)
    elif backend:
        backend_info = {"raw": backend}
    else:
        backend_info = {}
    backend_info.setdefault("name", "doc-to-agent-markdown")
    backend_info["element_output"] = "compatibility_shim"
    backend_info["element_schema"] = ELEMENT_SCHEMA_VERSION
    patched["backend"] = backend_info
    element_meta = meta_patch(elements, source_format)
    existing_coverage = patched.get("coverage") if isinstance(patched.get("coverage"), dict) else {}
    element_meta["coverage"] = {**existing_coverage, **element_meta["coverage"]}
    patched.update(element_meta)
    return patched
