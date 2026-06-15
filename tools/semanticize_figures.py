#!/usr/bin/env python3
"""Phase 3 — Semantic Compile: backfill figure descriptions (v0.5).

    python3 scripts/run_python.py tools/semanticize_figures.py --job "<job-dir>"

Reads review/vision_cache.json (JSONL: {"file": "<asset filename>", "text": "..."},
written by the Agent's visual-description step after looking at extracted/images/)
and fills figure.description for matching assets. Figures still lacking a
description are flagged needs_review and reported (they block nothing here, but
surface in the audit). Idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import report  # noqa: E402

CAPTION_RE = re.compile(r"^\s*((图|Figure|Fig\.?)\s*[0-9A-Za-z][0-9A-Za-z.\-]*)\s*[:：.]\s*([^\n]+)")
AUTO_NOISE_REASONS = {
    "decorative_or_document_artifact",
    "duplicate_asset",
}
DOCUMENT_ARTIFACT_TERMS = (
    "logo", "brand", "品牌", "商标",
    "印章", "盖章", "签章", "专用章", "stamp", "seal",
    "水印", "装饰", "背景图", "背景水印", "不含数据",
    "decorative", "watermark",
)


def _confidence(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def load_vision_cache(job_root: Path) -> dict[str, str]:
    """basename -> description. Supports JSONL (preferred) and a flat dict."""
    cache: dict[str, str] = {}
    p = job_root / P.REVIEW_VISION_CACHE
    if not p.is_file():
        return cache
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return cache
    # JSONL is the backend contract: each line a {"file","text"} record. Parse it
    # first — a single-line JSONL file is itself a valid JSON dict and would be
    # misread by a flat-dict-first heuristic.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate a partial line; a fully corrupt file falls through to []
        if isinstance(rec, dict) and rec.get("file"):
            cache[Path(rec["file"]).name] = str(rec.get("text", ""))
    if cache:
        return cache
    # fallback: an old flat {filename: description} dict
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return {Path(k).name: str(v) for k, v in obj.items() if isinstance(v, str)}
    except json.JSONDecodeError:
        pass
    return cache


def backfill(blocks: list[dict], cache: dict[str, str]) -> tuple[int, int]:
    described = undescribed = 0
    for b in blocks:
        if b["type"] != "figure":
            continue
        fig = b["figure"]
        names = [Path(fig.get("asset_file") or "").name, Path(fig.get("original_asset_file") or "").name]
        desc = next((cache[name] for name in names if name and name in cache and cache[name].strip()), "")
        if desc:
            fig["description"] = desc
            if not fig.get("caption"):
                m = CAPTION_RE.match(desc)
                if m:
                    fig["figure_no"] = fig.get("figure_no") or m.group(1).strip()
                    fig["caption"] = f"{m.group(1).strip()}：{m.group(3).strip()}"
            b["confidence"] = max(_confidence(b.get("confidence")), 0.85)
            b["needs_review"] = False
            b["evidence_level"] = "agent_reviewed"
            described += 1
        else:
            if not fig.get("description"):
                b["needs_review"] = True
                undescribed += 1
    return described, undescribed


def _asset_sha256(job_root: Path, rel: str) -> str | None:
    path = job_root / rel
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _figure_text(fig: dict) -> str:
    return " ".join(str(fig.get(k) or "") for k in ("figure_no", "caption", "description")).lower()


def _is_document_artifact(fig: dict) -> bool:
    text = _figure_text(fig)
    return any(term.lower() in text for term in DOCUMENT_ARTIFACT_TERMS)


def mark_noise_figures(blocks: list[dict], job_root: Path) -> int:
    """Mark reader-facing figure noise while keeping IR/source provenance intact."""
    figure_blocks = [b for b in blocks if b.get("type") == "figure"]
    by_block: dict[str, str | None] = {}
    for block in figure_blocks:
        fig = block.get("figure") or {}
        sha = _asset_sha256(job_root, fig.get("asset_file") or "")
        by_block[block["id"]] = sha
        if fig.get("noise_reason") in AUTO_NOISE_REASONS:
            fig.pop("likely_noise", None)
            fig.pop("noise_reason", None)

    counts = Counter(sha for sha in by_block.values() if sha)
    seen: set[str] = set()
    marked = 0
    for block in figure_blocks:
        fig = block.get("figure") or {}
        sha = by_block.get(block["id"])
        reason = ""
        if _is_document_artifact(fig):
            reason = "decorative_or_document_artifact"
        elif sha and counts[sha] > 1 and sha in seen:
            reason = "duplicate_asset"

        if reason:
            fig["likely_noise"] = True
            fig["noise_reason"] = reason
            marked += 1
        if sha:
            seen.add(sha)
    return marked


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Backfill figure descriptions from vision cache.")
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

    cache = load_vision_cache(job_root)
    n_desc, n_undesc = backfill(blocks, cache)
    n_noise = mark_noise_figures(blocks, job_root)
    IR.save_all(job_root, blocks, doc)

    report.upsert_section(
        job_root / "review" / "semantic_compile.md", "Semantic Compile", "semanticize_figures",
        f"- descriptions backfilled: {n_desc}\n"
        f"- figures still undescribed (need vision): {n_undesc}\n"
        f"- figures marked as likely noise: {n_noise}")

    print(f"[ok] semanticize_figures: described={n_desc}, undescribed={n_undesc}, noise={n_noise}")
    if n_undesc:
        print(f"     {n_undesc} figure(s) need visual description — write review/vision_cache.json "
              "(JSONL: {{\"file\": \"<asset filename>\", \"text\": \"...\"}}) then re-run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
