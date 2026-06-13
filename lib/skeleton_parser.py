"""Parse a backend skeleton (Markdown + meta comments) into IR blocks.

Grammar handled (doc-to-agent-markdown skeleton): headings, `## Slide N:`,
`## Sheet:`, markdown tables, ``` fences, inline/standalone $…$/$$…$$, lists,
blockquote placeholders (`> [图表:…]` etc.), `<!-- IMAGE: f -->` +
`[VISION_PLACEHOLDER_f]`, and `<!-- meta:page_start page=N -->` markers.

source_anchor strategy by format (PLAN §9.2): PDF→page, PPTX→slide, XLSX→sheet,
DOCX→heading_path+paragraph_index, MD/TXT→heading_path+block_index.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from . import ir as IR
from . import paths as P

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SLIDE = re.compile(r"^Slide\s+(\d+)\s*[:：]\s*(.*)$")
_SHEET = re.compile(r"^Sheet\s*[:：]\s*(.*)$")
_PAGE_START = re.compile(r"<!--\s*meta:page_start\s+page=(\d+)\s*-->")
_ZONE_START = re.compile(r"<!--\s*meta:zone\s+([a-z_]+)\s*-->")
_ZONE_END = re.compile(r"<!--\s*meta:zone_end\s*-->")
_IMAGE = re.compile(r"<!--\s*IMAGE:\s*(.+?)\s*-->")
_PLACEHOLDER = re.compile(r"^\[VISION_PLACEHOLDER_(.+?)\]\s*$")
_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")
_TABLE_SEP = re.compile(r"\|\s*:?-{3,}")
_LIST = re.compile(r"^\s*([-*+]|\d+\.)\s+(.*)$")
_FORMULA_ONLY = re.compile(r"^\s*\${1,2}[^$]+\${1,2}\s*$")
_EQUATION_NO = re.compile(r"^\(?(\d+)\)$")
_EQUATION_TRAIL = re.compile(r"\((\d+)\)\s*$")
_SUBSCRIPT = re.compile(r"([ab])(\d+)")
_Z_POWER = re.compile(r"z-([0-9A-Za-z]+)")
_PLACEHOLDER_TAG = re.compile(r"^>\s*\[([^\]:：]+)")  # > [图表: …] / > [文本框] / > [演讲者备注]


class Parser:
    def __init__(self, source_rel: str, source_format: str):
        self.source_rel = source_rel
        self.fmt = source_format.lower()
        self.ctx = {"page": None, "slide": None, "sheet": None, "heading_path": [], "zone": None}
        self.blocks: list[dict] = []
        self.counters: dict[str, int] = defaultdict(int)
        self.ordinal = 0

    def _id(self, btype: str) -> str:
        self.counters[btype] += 1
        return f"block_{btype}_{self.counters[btype]:03d}"

    def _anchor(self) -> dict:
        sf = self.source_rel
        if self.fmt == ".pdf":
            pg = self.ctx["page"]
            return {"kind": "pdf_page", "source_file": sf, "page": pg,
                    "page_label": (f"p.{pg}" if pg else None)}
        if self.fmt == ".pptx":
            return {"kind": "slide", "source_file": sf, "slide": self.ctx["slide"]}
        if self.fmt == ".xlsx":
            return {"kind": "sheet_range", "source_file": sf, "sheet": self.ctx["sheet"], "range": None}
        if self.fmt == ".docx":
            return {"kind": "docx_anchor", "source_file": sf, "page": None,
                    "heading_path": self._heading_titles, "paragraph_index": self.ordinal}
        return {"kind": "text_anchor", "source_file": sf,
                "heading_path": self._heading_titles, "block_index": self.ordinal}

    def _emit(self, btype: str, *, confidence: float, needs_review: bool, **fields) -> dict:
        self.ordinal += 1
        block = IR.new_block(self._id(btype), btype, self._anchor(),
                             confidence=confidence, needs_review=needs_review, **fields)
        if self.ctx.get("zone"):
            block["source_zone"] = self.ctx["zone"]
        self.blocks.append(block)
        return block

    def _heading(self, level: int, title: str) -> None:
        m = _SLIDE.match(title)
        if m:
            self.ctx["slide"] = int(m.group(1))
        m2 = _SHEET.match(title)
        if m2:
            self.ctx["sheet"] = m2.group(1).strip()
        hp = self.ctx["heading_path"]
        while hp and hp[-1][0] >= level:
            hp.pop()
        hp.append((level, title))
        self.ctx["heading_path"] = hp
        self._emit("heading", confidence=1.0, needs_review=False,
                   heading={"level": level, "text": title})

    @property
    def _heading_titles(self) -> list[str]:
        return [t for _, t in self.ctx["heading_path"]]

    def parse(self, text: str) -> None:
        lines = text.splitlines()
        i, n = 0, len(lines)
        while i < n:
            s = lines[i].strip()
            if not s:
                i += 1
                continue
            m = _PAGE_START.search(s)
            if m:
                self.ctx["page"] = int(m.group(1))
                i += 1
                continue
            mz = _ZONE_START.search(s)
            if mz:
                self.ctx["zone"] = mz.group(1)
                i += 1
                continue
            if _ZONE_END.search(s):
                self.ctx["zone"] = None
                i += 1
                continue
            mi = _IMAGE.search(s)
            if mi:
                i = self._consume_image(lines, i, mi.group(1))
                continue
            mp = _PLACEHOLDER.match(s)
            if mp:
                self._figure(mp.group(1))
                i += 1
                continue
            if _COMMENT.match(s):
                i += 1
                continue
            if s.startswith("```"):
                i = self._consume_code(lines, i)
                continue
            if s.startswith("|"):
                i = self._consume_table(lines, i)
                continue
            mh = _HEADING.match(s)
            if mh:
                self._heading(len(mh.group(1)), mh.group(2).strip())
                i += 1
                continue
            if _FORMULA_ONLY.match(s):
                self._emit("formula", confidence=0.9, needs_review=True,
                           formula={"equation_no": None, "latex": s.strip("$ "),
                                    "plain_text_source": s, "visual_check": "pending",
                                    "control_source": None})
                i += 1
                continue
            formula_end = self._formula_end_index(lines, i)
            if formula_end is not None:
                i = self._consume_numbered_formula(lines, i, formula_end)
                continue
            if _LIST.match(s):
                i = self._consume_list(lines, i)
                continue
            content = {"text": s, "quote": s.startswith(">")}
            ph = _PLACEHOLDER_TAG.match(s)
            if ph:
                content["placeholder_type"] = ph.group(1)  # 图表 / 文本框 / 演讲者备注
            self._emit("para", confidence=1.0, needs_review=False, content=content)
            i += 1

    def _consume_image(self, lines: list[str], i: int, raw: str) -> int:
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and _PLACEHOLDER.match(lines[j].strip()):
            j += 1  # swallow the placeholder line
        fname, meta = self._image_parts(raw)
        if meta.get("page_render") == "true":
            return j
        self._figure(fname, zone=meta.get("zone"))
        return j

    def _image_parts(self, raw: str) -> tuple[str, dict[str, str]]:
        parts = raw.split()
        meta = {}
        for token in parts[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                meta[key.strip()] = value.strip()
        return parts[0], meta

    def _figure(self, fname: str, zone: str | None = None) -> None:
        asset_id = f"asset_{Path(fname).stem}"
        block = self._emit("figure", confidence=0.5, needs_review=True,
                           figure={"figure_no": None, "caption": None, "asset_id": asset_id,
                                   "asset_file": f"{P.EXTRACTED_IMAGES}/{fname}",
                                   "description": None, "estimated_values": []})
        if zone:
            block["source_zone"] = zone

    def _formula_end_index(self, lines: list[str], i: int) -> int | None:
        start = lines[i].strip()
        if not re.match(r"^H\s*[zs]\s*=", start) or len(start) > 100:
            return None
        for j in range(i + 1, min(len(lines), i + 10)):
            s = lines[j].strip()
            if not s:
                continue
            if _HEADING.match(s) or s.startswith("|") or s.startswith("<!--"):
                return None
            if _EQUATION_NO.match(s):
                return j
            if _EQUATION_TRAIL.search(s):
                return j
        return None

    def _latex_text(self, text: str) -> str:
        s = text.replace("−", "-").replace(" ", " ")
        s = _SUBSCRIPT.sub(r"\1_{\2}", s)
        s = _Z_POWER.sub(r"z^{-\1}", s)
        return re.sub(r"\s+", " ", s).strip()

    def _consume_numbered_formula(self, lines: list[str], i: int, end: int) -> int:
        raw = [line.strip() for line in lines[i:end] if line.strip()]
        end_line = lines[end].strip()
        number_match = _EQUATION_NO.match(end_line) or _EQUATION_TRAIL.search(end_line)
        number = number_match.group(1)
        end_body = _EQUATION_TRAIL.sub("", end_line).strip()
        if end_body:
            raw.append(end_body)
        latex = self._latex_text(" ".join(raw))
        if len(raw) >= 3 and re.match(r"^H\s*z\s*=", raw[0]):
            numerator = self._latex_text(raw[1])
            denominator = self._latex_text(" ".join(raw[2:]))
            latex = f"H(z)=\\frac{{{numerator}}}{{{denominator}}}"
        self._emit("formula", confidence=0.75, needs_review=True,
                   formula={"equation_no": number, "latex": latex,
                            "plain_text_source": "\n".join(raw + [lines[end].strip()]),
                            "visual_check": "needs_review", "control_source": None})
        return end + 1

    def _consume_code(self, lines: list[str], i: int) -> int:
        lang = lines[i].strip()[3:].strip() or None
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith("```"):
            body.append(lines[j])
            j += 1
        self._emit("code", confidence=1.0, needs_review=False,
                   code={"language": lang, "text": "\n".join(body)})
        return j + 1 if j < len(lines) else j

    def _consume_list(self, lines: list[str], i: int) -> int:
        items: list[str] = []
        ordered = bool(re.match(r"^\s*\d+\.", lines[i]))
        j = i
        while j < len(lines):
            m = _LIST.match(lines[j].strip()) if lines[j].strip() else None
            if not m:
                break
            items.append(m.group(2).strip())
            j += 1
        self._emit("list", confidence=1.0, needs_review=False,
                   content={"items": items, "ordered": ordered})
        return j

    def _consume_table(self, lines: list[str], i: int) -> int:
        rows_raw: list[str] = []
        j = i
        while j < len(lines) and lines[j].strip().startswith("|"):
            rows_raw.append(lines[j].strip())
            j += 1
        sep_idx = next((k for k, r in enumerate(rows_raw) if _TABLE_SEP.search(r)), None)
        if sep_idx is None:
            self._emit("para", confidence=1.0, needs_review=False,
                       content={"text": "\n".join(rows_raw), "quote": False})
            return j

        def split_row(r: str) -> list[str]:
            return [c.strip() for c in r.strip().strip("|").split("|")]

        # header is the row above the separator; data is everything after it.
        # A separator at index 0 (no header row) is malformed -> flag for review.
        malformed_header = sep_idx == 0
        header_idx = sep_idx - 1 if sep_idx >= 1 else sep_idx
        header = split_row(rows_raw[header_idx])
        data = [split_row(r) for r in rows_raw[sep_idx + 1:]]
        pre_rows = rows_raw[:header_idx]  # caption rows: captured, never dropped
        title = " / ".join(" ".join(split_row(r)).strip() for r in pre_rows) or None
        cols = len(header)
        cell_rows = [[{"text": c, "rowspan": 1, "colspan": 1} for c in row] for row in data]
        hard = "pass" if all(len(r) == cols for r in data) else "fail"
        self._emit("table", confidence=0.95,
                   needs_review=(hard != "pass" or malformed_header or bool(pre_rows)),
                   title=title,
                   table={"columns": header, "header_rows": [], "rows": cell_rows,
                          "continues_from": None, "continues_to": None,
                          "audit": {"row_count": len(data), "column_count": cols, "hard_column_check": hard}})
        return j
