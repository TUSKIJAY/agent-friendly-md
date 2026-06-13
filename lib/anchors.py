"""Render a source_anchor as the human-readable 〔源 …〕 marker (PLAN §10).

PDF → 〔源 p.N〕, PPTX → 〔源 slide N〕, XLSX → 〔源 Sheet!A1:B2〕,
DOCX/MD → 〔源 p.N〕 or 〔源 <last heading> / paragraph N〕 when no page.
"""
from __future__ import annotations


def format_anchor(anchor: dict | None) -> str:
    a = anchor or {}
    kind = a.get("kind")
    if kind == "pdf_page":
        pg = a.get("page")
        return f"〔源 p.{pg}〕" if pg is not None else "〔源 PDF〕"
    if kind == "slide":
        s = a.get("slide")
        return f"〔源 slide {s}〕" if s is not None else "〔源 slide〕"
    if kind == "sheet_range":
        sheet = a.get("sheet") or "Sheet"
        rng = a.get("range")
        return f"〔源 {sheet}!{rng}〕" if rng else f"〔源 {sheet}〕"
    if kind in ("docx_anchor", "text_anchor"):
        if a.get("page") is not None:
            return f"〔源 p.{a['page']}〕"
        hp = a.get("heading_path") or []
        idx = a.get("paragraph_index") if "paragraph_index" in a else a.get("block_index")
        tail = hp[-1] if hp else "正文"
        return f"〔源 {tail} / 段 {idx}〕" if idx is not None else f"〔源 {tail}〕"
    return ""
