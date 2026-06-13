"""Render IR blocks to Agent-friendly Markdown (PLAN §2/§10).

Major blocks (heading/table/figure/formula/code) carry a 〔源 …〕 anchor; plain
paragraphs inherit their section heading's anchor. Blocks flagged likely_noise
are dropped from the output (they remain in the IR for provenance — never lost).
Undescribed figures emit a [未解析: …] marker so nothing is silently incomplete.
"""
from __future__ import annotations

import re
from pathlib import Path

from .anchors import format_anchor

ANCHORED = {"heading", "table", "figure", "formula", "code"}
# keep word chars + CJK + space + hyphen; everything else dropped (GFM-style)
_NON_SLUG = re.compile(r"[^\w一-鿿 -]")


def _yaml_str(value) -> str:
    """Double-quote + escape a scalar so colons/newlines can't break YAML."""
    s = str(value)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in str(text).splitlines())


def render_front_matter(meta: dict, profile: dict, counts: dict, split: bool) -> str:
    lines = [
        "---",
        "schema: agent-friendly-md/0.1",
        "generated_by: agent-friendly-md",
        f"title: {_yaml_str(meta.get('title', ''))}",
        f"source_file: {_yaml_str(meta.get('source_file', ''))}",
        f"document_type: {_yaml_str(meta.get('source_type', ''))}",
        f"risk_level: {_yaml_str(profile.get('risk_level', ''))}",
        "counts:",
        f"  blocks: {counts.get('block_count', 0)}",
        f"  tables: {counts.get('table_count', 0)}",
        f"  figures: {counts.get('figure_count', 0)}",
        f"  formulas: {counts.get('formula_count', 0)}",
        f"split: {str(split).lower()}",
        "---",
    ]
    return "\n".join(lines)


def gfm_slug(text: str) -> str:
    s = _NON_SLUG.sub("", text.strip().lower())
    return s.replace(" ", "-") or "section"


def assign_heading_slugs(blocks: list[dict]) -> dict[str, str]:
    """block_id -> unique slug (deduped, GFM-style). Deterministic per block list."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for b in blocks:
        if b["type"] != "heading":
            continue
        base = gfm_slug(b["heading"]["text"])
        n = seen.get(base, 0)
        seen[base] = n + 1
        out[b["id"]] = base if n == 0 else f"{base}-{n}"
    return out


def render_toc(blocks: list[dict]) -> str:
    slugs = assign_heading_slugs(blocks)
    out = ["## 目录", ""]
    for b in blocks:
        if b["type"] != "heading":
            continue
        lvl = b["heading"]["level"]
        out.append(f"{'  ' * (lvl - 1)}- [{b['heading']['text']}](#{slugs[b['id']]})")
    return "\n".join(out)


def render_table_markdown(t: dict) -> str:
    rows_data = t.get("rows") or []
    cols = t.get("columns") or []
    if not cols:  # no header columns -> size from widest row, don't drop cells
        cols = [""] * max((len(r) for r in rows_data), default=1)
    head = "| " + " | ".join(c or " " for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for row in rows_data:
        cells = []
        for c in row:
            if not isinstance(c, dict):
                raise TypeError("table cell must be an object")
            span = int(c.get("colspan", 1) or 1)
            span = span if span > 0 else 1
            text = (c.get("text") or "").replace("\n", " ").replace("|", "\\|")
            cells.extend([text, *([""] * (span - 1))])
        cells = (cells + [""] * len(cols))[:len(cols)]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *rows])


def render_block(block: dict, *, assets_prefix: str = "assets", heading_slug: str | None = None) -> str | None:
    btype = block["type"]
    anchor = format_anchor(block.get("source_anchor")) if btype in ANCHORED else ""
    suffix = f"　{anchor}" if anchor else ""

    if btype == "heading":
        h = block["heading"]
        aid = f'<a id="{heading_slug}"></a>\n' if heading_slug else ""
        return f"{aid}{'#' * h['level']} {h['text']}{suffix}"

    if btype == "para":
        content = block.get("content") or {}
        if content.get("likely_noise"):
            return None  # dropped from output; retained in IR
        text = content.get("text", "")
        return text

    if btype == "list":
        content = block.get("content") or {}
        ordered = content.get("ordered")
        items = content.get("items") or []
        return "\n".join(f"{i + 1}. {it}" if ordered else f"- {it}" for i, it in enumerate(items))

    if btype == "table":
        t = block["table"]
        parts = []
        if block.get("title"):
            parts.append(f"*{block['title']}*")
        if t.get("continues_from"):
            parts.append("> **审计注**：本表为跨页续表。")
        parts.append(render_table_markdown(t))
        if anchor:
            parts.append(f"*{anchor}*")
        return "\n\n".join(parts)

    if btype == "figure":
        f = block["figure"]
        if f.get("likely_noise") or block.get("likely_noise"):
            return None
        name = Path(f.get("asset_file") or "").name
        cap = f.get("caption") or f.get("figure_no") or name
        out = [f"![{cap}]({assets_prefix}/{name})"]
        label = f.get("figure_no") or cap
        out.append(f"**{label}**{suffix}" if label else suffix.strip())
        desc = f.get("description")
        if desc:
            out.append(_blockquote(desc))
        else:
            out.append("> [未解析: 图片说明 — 需视觉描述]")
        for ev in (f.get("estimated_values") or []):
            out.append(f"> **编者注**：{ev.get('label')} ≈ {ev.get('value')}（{ev.get('basis', '图上估读')}）")
        return "\n\n".join(p for p in out if p.strip())

    if btype == "formula":
        f = block["formula"]
        eq = f" *(公式 {f['equation_no']})*" if f.get("equation_no") else ""
        note = "\n\n> **审计注**：公式待视觉校对。" if f.get("visual_check") == "needs_review" else ""
        return f"$$\n{f.get('latex', '')}\n$${eq}{(' ' + anchor) if anchor else ''}{note}"

    if btype == "code":
        c = block["code"]
        lang = c.get("language") or ""
        return f"```{lang}\n{c.get('text', '')}\n```{(chr(10) + chr(10) + '*' + anchor + '*') if anchor else ''}"

    return None
