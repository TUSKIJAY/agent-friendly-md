"""Markdown structural quality helpers for golden-example checks."""
from __future__ import annotations

import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\[VISION_PLACEHOLDER_[^\]]*\]|\[TODO\]|\[未解析:[^\]]+\]|�")
TITLE_RE = re.compile(r"(?m)^title:\s*(.+?)\s*$")
H1_RE = re.compile(r"(?m)^# (.+?)\s*$")
SUMMARY_RE = re.compile(r"(?m)^>\s*\*\*摘要\*\*")
TOC_RE = re.compile(r"^#{2,3}\s*(目录|分卷目录)\s*$")
TOC_ITEM_RE = re.compile(r"^\s*-\s+\[[^\]]+\]\([^)]+\)")
SOURCE_ANCHOR_RE = re.compile(r"〔源 [^〕]+〕")
GENERIC_TITLES = {
    "", "pdf", "doc", "docx", "document", "file", "md", "markdown", "ppt", "pptx",
    "txt", "untitled", "unknown", "xlsx", "文档", "文件", "未命名",
}
NOISE_PATTERNS = (
    re.compile(r"^(pdf|docx?|document|table of contents|目录)$", re.IGNORECASE),
    re.compile(r"^(第\s*)?\d+\s*(页|/)\s*\d*$", re.IGNORECASE),
    re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^\d+(\.\d+)*\s+.{2,80}\s+\.{0,}\s*\d{1,4}$"),
    re.compile(r"^[\w.-]+\.pdf$", re.IGNORECASE),
    re.compile(r"^(confidential|copyright|www\.)", re.IGNORECASE),
)


def md_metrics(text: str) -> dict:
    return {
        "h1": len(re.findall(r"(?m)^# ", text)),
        "headings": len(re.findall(r"(?m)^#{1,6} ", text)),
        "source_anchors": text.count("〔源 "),
        "tables": len(re.findall(r"(?m)^\|.*\|$", text)),
        "image_refs": text.count("!["),
        "formula_markers": text.count("$$") + len(re.findall(r"\\\(.+?\\\)", text)),
        "placeholders": len(PLACEHOLDER_RE.findall(text)),
    }


def _clean_title(value: str) -> str:
    title = SOURCE_ANCHOR_RE.sub("", value).strip()
    title = re.sub(r"<[^>]+>", "", title).strip()
    return title.strip("'\" ")


def _is_generic_title(value: str) -> bool:
    title = _clean_title(value)
    normalized = re.sub(r"[\s_\-.:：/\\]+", "", title).lower()
    return normalized in GENERIC_TITLES or len(normalized) <= 1


def title_report(text: str) -> dict:
    front = ""
    m = TITLE_RE.search(text)
    if m:
        front = _clean_title(m.group(1))
    h1 = ""
    for heading in H1_RE.findall(text):
        cand = _clean_title(heading)
        if cand:
            h1 = cand
            break
    return {
        "front_matter_title": front,
        "first_h1": h1,
        "ok": (not front or not _is_generic_title(front)) and bool(h1) and not _is_generic_title(h1),
    }


def toc_items(text: str) -> list[str]:
    items: list[str] = []
    in_toc = False
    for line in text.splitlines():
        stripped = line.strip()
        if TOC_RE.match(stripped):
            in_toc = True
            continue
        if not in_toc:
            continue
        if stripped == "---" or (stripped.startswith("#") and not TOC_RE.match(stripped)):
            break
        if TOC_ITEM_RE.match(stripped):
            items.append(stripped)
    return items


# A "heading" that is really a figure/diagram/device label, e.g. "6 to 4 Mux",
# "图 3", "Table 2". A number-prefixed label like this must not be promoted to a
# section heading (compile_structure) nor sit at the top level of the TOC: it is
# the exact pathology that let ZHCAEJ4 score 1.0 with "6 to 4 Mux" as its first
# TOC entry. Patterns are deliberately conservative (no bare ASCII "x"/":" which
# would mis-fire on "x86" / clock times) to avoid demoting real sections.
CAPTION_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"\d+\s+to\s+\d+\b"                                            # "6 to 4 Mux"
    r"|\d+\s*×\s*\d+\b"                                            # "4 × 4"
    r"|(?:图|表|公式|图表|fig\.?|figure|table|equation|scheme)\s*\d"  # figure/table captions
    r")",
    re.IGNORECASE,
)
TOC_ITEM_TEXT_RE = re.compile(r"^-\s+\[([^\]]+)\]")
SECTION_NUM_RE = re.compile(r"^(\d+)(?:[.\s]|$)")


def is_caption_label(text: str) -> bool:
    """True when ``text`` looks like a figure/device caption, not a section."""
    return bool(CAPTION_LABEL_RE.match(text.strip()))


def _toc_entries(text: str) -> list[tuple[int, str]]:
    """Parse the 目录 block into ``(indent, link_text)`` pairs (indent preserved
    so nesting depth survives — ``toc_items`` strips it)."""
    rows: list[tuple[int, str]] = []
    in_toc = False
    for line in text.splitlines():
        stripped = line.strip()
        if TOC_RE.match(stripped):
            in_toc = True
            continue
        if not in_toc:
            continue
        if stripped == "---" or (stripped.startswith("#") and not TOC_RE.match(stripped)):
            break
        if TOC_ITEM_RE.match(stripped):
            indent = len(line) - len(line.lstrip(" "))
            m = TOC_ITEM_TEXT_RE.match(stripped)
            rows.append((indent, m.group(1).strip() if m else ""))
    return rows


def toc_coherence_report(text: str) -> dict:
    """Flag a structurally-broken TOC: a figure/device label promoted to the top
    level, or top-level numbered sections that are not monotonic. Top level is
    the minimum indent actually present, so it is robust to the list indent width.
    """
    rows = _toc_entries(text)
    if not rows:
        return {"checked": False, "ok": True, "issues": [], "top_level": []}
    min_indent = min(indent for indent, _ in rows)
    top = [titletext for indent, titletext in rows if indent == min_indent]
    issues: list[dict] = []

    labels = [t for t in top if is_caption_label(t)]
    if labels:
        issues.append({"kind": "caption_label_at_top_level", "items": labels[:5]})

    nums: list[int] = []
    for t in top:
        m = SECTION_NUM_RE.match(t)
        if m:
            nums.append(int(m.group(1)))
    # Flag a number that goes BACKWARDS but isn't a legitimate restart-to-1
    # (main sections 1,2,3 then appendices 1,2 → [1,2,3,1,2] is valid structure,
    # not disorder). The ZHCAEJ4 "6 then 3" pathology still trips this, and is
    # independently caught by caption_label_at_top_level.
    descending = [(a, b) for a, b in zip(nums, nums[1:]) if b < a and b != 1]
    if descending:
        issues.append({"kind": "nonmonotonic_section_numbers", "sequence": nums})

    return {"checked": True, "ok": not issues, "issues": issues, "top_level": top[:12]}


def _strip_front_matter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for idx, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[idx + 1:])
    return text


def _noise_candidate_lines(text: str) -> list[str]:
    kept: list[str] = []
    skip_summary = False
    skip_toc = False
    for line in _strip_front_matter(text).splitlines():
        stripped = line.strip()
        if SUMMARY_RE.match(stripped):
            skip_summary = True
            continue
        if skip_summary:
            if stripped.startswith(">") or not stripped:
                continue
            skip_summary = False
        if TOC_RE.match(stripped):
            skip_toc = True
            continue
        if skip_toc:
            if stripped == "---":
                skip_toc = False
            continue
        if stripped == "---" or not stripped:
            continue
        kept.append(stripped)
    return kept


def _is_noise_line(line: str) -> bool:
    if line.startswith("![") or line.startswith("|") or line.startswith("$$"):
        return False
    clean = SOURCE_ANCHOR_RE.sub("", line)
    clean = re.sub(r"^[#>\-* ]+", "", clean).strip()
    clean = clean.strip("`*_ ")
    return any(p.search(clean) for p in NOISE_PATTERNS)


def opening_noise_report(text: str) -> dict:
    lines = _noise_candidate_lines(text)[:40]
    noisy = [line for line in lines if _is_noise_line(line)]
    density = len(noisy) / len(lines) if lines else 0.0
    return {
        "sample_size": len(lines),
        "noisy_count": len(noisy),
        "density": round(density, 3),
        "noisy_lines": noisy[:8],
        "ok": len(noisy) < 3 or density < 0.18,
    }


def baseline_compare(main_text: str, baseline: Path | None) -> dict | None:
    if baseline is None:
        return None
    base_text = baseline.read_text(encoding="utf-8", errors="replace")
    main = md_metrics(main_text)
    base = md_metrics(base_text)
    structural_total = main["headings"] + main["tables"] + main["image_refs"] + main["formula_markers"]
    baseline_total = base["headings"] + base["tables"] + base["image_refs"] + base["formula_markers"]
    criteria = {
        "workflow_has_source_traceability": (
            main["source_anchors"] > 0
            and main["source_anchors"] >= max(1, base["source_anchors"] // 2)
        ),
        "workflow_structure_floor": structural_total >= max(1, min(baseline_total, 5)),
        "workflow_placeholders_not_worse": main["placeholders"] <= base["placeholders"],
    }
    return {
        "baseline": baseline.name,  # basename only — no absolute path in the report
        "workflow": main,
        "baseline_metrics": base,
        "delta": {k: main[k] - base.get(k, 0) for k in main},
        "criteria": criteria,
        "status": "pass" if all(criteria.values()) else "fail",
    }
