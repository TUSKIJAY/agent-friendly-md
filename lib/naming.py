"""Asset naming helpers (PLAN §10 / docs/ir-schema.md §6).

Asset filenames use only ASCII [a-z0-9._-], format <kind>_<source_ref>_<slug>.<ext>,
body <= 96 chars, collisions get a stable numeric suffix. Chinese captions that
can't be transliterated fall back to asset_<seq>.
"""
from __future__ import annotations

import re

# lowercase-alnum start, no trailing punctuation, and a real lowercase-alnum extension
ASSET_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\.[a-z0-9]+$")
MAX_NAME_BODY = 96  # filename body (excluding extension)

_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")


def ascii_slug(text: str | None, maxlen: int = 40) -> str:
    """Lowercase ASCII-word slug joined by '_'. Empty if no ASCII content."""
    if not text:
        return ""
    words = _ASCII_WORD.findall(text)
    slug = "_".join(w.lower() for w in words)
    return slug[:maxlen].strip("_")


def source_ref(anchor: dict | None) -> str:
    """Short source-location token for a filename: p006 / slide03 / sheet_x / doc."""
    a = anchor or {}
    kind = a.get("kind")
    if kind == "pdf_page" and a.get("page"):
        return f"p{int(a['page']):03d}"
    if kind == "slide" and a.get("slide"):
        return f"slide{int(a['slide']):02d}"
    if kind == "sheet_range" and a.get("sheet"):
        s = ascii_slug(a["sheet"]) or "sheet"
        return f"sheet_{s}"
    if kind == "docx_anchor" and a.get("page"):
        return f"p{int(a['page']):03d}"
    return "doc"


def asset_filename(kind: str, anchor: dict | None, slug: str | None,
                   seq: int, ext: str, existing: set[str]) -> str:
    """Build a §10-conformant, collision-free asset filename."""
    ref = source_ref(anchor)
    body_slug = ascii_slug(slug) or f"asset_{seq:03d}"
    ext = ext.lower().lstrip(".") or "png"
    body = f"{kind}_{ref}_{body_slug}"[:MAX_NAME_BODY]
    name = f"{body}.{ext}"
    if name not in existing:
        return name
    n = 2
    while True:
        suffix = f"_{n:02d}"
        cand_body = f"{body[:MAX_NAME_BODY - len(suffix)]}{suffix}"  # reserve room so suffix always fits
        cand = f"{cand_body}.{ext}"
        if cand not in existing:
            return cand
        n += 1


def is_valid_asset_name(name: str) -> bool:
    body = name.rsplit(".", 1)[0]
    return bool(ASSET_NAME_RE.match(name)) and len(body) <= MAX_NAME_BODY
