#!/usr/bin/env python3
"""Phase 3 — Semantic Compile: structure normalization (v0.5).

    python3 scripts/run_python.py tools/compile_structure.py --job "<job-dir>"

- normalizes heading levels to consecutive ranks (PDF font-size headings can be
  sparse, e.g. {1,3,5}); keeps the raw level under heading.raw_level,
- flags repeated paragraphs (headers/footers/page numbers appearing >=3 times)
  as likely noise — flagged, never silently dropped (assembly decides),
then rewrites the IR and appends to review/semantic_compile.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import golden_quality as GQ  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import report  # noqa: E402

NOISE_MIN_REPEATS = 3
SECTION_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.{2,80})$")
NOISE_ZONES = {"header", "footer"}


def promote_numbered_headings(blocks: list[dict]) -> int:
    promoted = 0
    for b in blocks:
        content = b.get("content") or {}
        text = (content.get("text") or "").strip()
        if b.get("type") != "para" or content.get("likely_noise") or content.get("quote"):
            continue
        if b.get("source_zone") in NOISE_ZONES or len(text) > 96 or "..." in text or "www." in text:
            continue
        # Don't promote a number-prefixed figure/device label ("6 to 4 Mux",
        # "图 3") to a section heading — that is the bug that put "6 to 4 Mux" at
        # the top of the ZHCAEJ4 TOC. golden_quality flags it; here we prevent it.
        if GQ.is_caption_label(text):
            continue
        m = SECTION_HEADING_RE.match(text)
        if not m:
            continue
        num, title = m.group(1), m.group(2).strip()
        # Reject number-prefixed PROSE that isn't a section heading. Bare integers
        # are the ambiguous case (years, listicles, quantities — "2024 was a good
        # year", "5 things you should know about security"); hierarchical numbers
        # ("2.1 …") rarely begin a sentence. Bias toward NOT promoting: a missed
        # promotion just leaves a paragraph (no content lost), whereas a false one
        # corrupts the heading tree / TOC / title.
        if "." not in num:
            if int(num) > 99:                  # implausible section number / a year
                continue
            if len(title.split()) >= 6:        # reads as a (wordy English) sentence
                continue
        if title[-1:] in "。．.!?！？":           # ends like a sentence
            continue
        level = min(6, num.count(".") + 1)
        b["type"] = "heading"
        b["heading"] = {"level": level, "text": text}
        b.pop("content", None)
        promoted += 1
    return promoted


def normalize_headings(blocks: list[dict]) -> int:
    levels = sorted({b["heading"]["level"] for b in blocks if b["type"] == "heading"})
    rank = {lv: i + 1 for i, lv in enumerate(levels)}
    changed = 0
    for b in blocks:
        if b["type"] != "heading":
            continue
        old = b["heading"]["level"]
        new = rank[old]
        if new != old:
            b["heading"]["raw_level"] = old
            b["heading"]["level"] = new
            changed += 1
    return changed


def flag_noise(blocks: list[dict]) -> int:
    texts = Counter()
    for b in blocks:
        content = b.get("content") or {}
        if b["type"] == "para" and not content.get("is_caption_for"):
            t = (content.get("text") or "").strip()
            if t:
                texts[t] += 1
    noisy = {t for t, n in texts.items() if n >= NOISE_MIN_REPEATS}
    flagged = 0
    for b in blocks:
        content = b.get("content") or {}
        text = (content.get("text") or "").strip()
        zone_noise = b.get("source_zone") in NOISE_ZONES or text.startswith("> [页面链接]")
        if (b["type"] == "para" and not content.get("is_caption_for")
                and (text in noisy or zone_noise)):
            content["likely_noise"] = True
            b["needs_review"] = True
            flagged += 1
    return flagged


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Normalize structure / flag noise.")
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

    n_noise = flag_noise(blocks)
    n_promoted = promote_numbered_headings(blocks)
    n_head = normalize_headings(blocks)
    IR.save_all(job_root, blocks, doc)

    report.upsert_section(
        job_root / "review" / "semantic_compile.md", "Semantic Compile", "compile_structure",
        f"- numbered headings promoted: {n_promoted}\n"
        f"- headings normalized: {n_head}\n"
        f"- paragraphs flagged as likely noise (>= {NOISE_MIN_REPEATS}x): {n_noise}")

    print(f"[ok] compile_structure: headings promoted={n_promoted}, normalized={n_head}, noise flagged={n_noise}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
