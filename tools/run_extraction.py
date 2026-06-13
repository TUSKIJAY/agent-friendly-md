#!/usr/bin/env python3
"""Phase 1 — Extraction (v0.2): drive the doc-to-agent-markdown backend.

    python3 scripts/run_python.py tools/run_extraction.py --job "<job-dir>"

Runs the backend extractor on the job's source, then maps its outputs into the
job bundle per PLAN §3:

  <name>_skeleton.md      -> extracted/text/<name>_skeleton.md
  <name>_extract_meta.json-> extracted/extract_meta.json (paths rewritten to bundle-relative)
  page_*.png              -> extracted/pages/
  other images            -> extracted/images/

It also writes review/imported_quality_report.md from the extractor stats and
seeds the Agent-authored slots (review/vision_cache.json, review/cleaning_decisions.json,
ir/summary.seed.md) if absent. It does NOT confirm the document profile — that is
validate_extraction.py's job (PLAN §6 / review-003 minor 8).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import backend as bk  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import subproc  # noqa: E402


def _count_dups(value) -> int:
    return len(value) if isinstance(value, (dict, list)) else 0


def _find_skeleton(workdir: Path) -> Path | None:
    hits = sorted(workdir.glob("*_skeleton.md"))
    return hits[0] if hits else None


def _find_meta(workdir: Path) -> Path | None:
    hits = sorted(workdir.glob("*_extract_meta.json"))
    return hits[0] if hits else None


def _map_images(image_dir: Path, images_dst: Path, pages_dst: Path) -> tuple[int, int]:
    n_img = n_page = 0
    if not image_dir.is_dir():
        return 0, 0
    for f in sorted(image_dir.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("page_"):
            shutil.copy2(f, pages_dst / f.name)
            n_page += 1
        else:
            shutil.copy2(f, images_dst / f.name)
            n_img += 1
    return n_img, n_page


def _seed_slots(job_root: Path) -> None:
    seeds = {
        P.REVIEW_VISION_CACHE: "",  # JSONL, one desc per line — filled by vision step
        P.REVIEW_CLEANING: "{}\n",
        P.IR_SUMMARY_SEED: "<!-- 摘要种子：通读骨架后写 200-300 字，组装时作为 main.md 摘要 -->\n",
    }
    for rel, content in seeds.items():
        p = job_root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


def _reset_dirs(job_root: Path) -> None:
    """Clear regenerated outputs so a re-run never leaves stale images/skeletons."""
    for rel in (P.EXTRACTED_TEXT, P.EXTRACTED_IMAGES, P.EXTRACTED_PAGES):
        d = job_root / rel
        if d.is_dir():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)


def _quality_report(job_root: Path, meta: dict, n_img: int, n_page: int, console: str) -> None:
    stats = meta.get("structured_stats", {})
    lines = [
        "# Imported Quality Report (backend extraction)",
        "",
        f"- extractor_version: {meta.get('extractor_version')}",
        f"- source_format: {meta.get('source_format')}",
        f"- image_count (meta): {meta.get('image_count')}",
        f"- mapped images: {n_img}  | mapped page renders: {n_page}",
        f"- placeholder_count: {meta.get('placeholder_count')}",
        f"- duplicate_images: {_count_dups(meta.get('duplicate_images'))}",
        f"- structured_stats: {json.dumps(stats, ensure_ascii=False)}",
        "",
        "## extractor console",
        "",
        "```",
        console.strip(),
        "```",
    ]
    (job_root / "review" / "imported_quality_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Phase 1 extraction via backend.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--backend", default=None, help="override backend dir (else AFM_BACKEND_DIR or default)")
    ap.add_argument("--force-page-render", action="store_true")
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--keep-formulas", action="store_true")
    ap.add_argument("--no-pdf-headings", action="store_true")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    state = js.load_state(job_root)
    sources = state.get("source_files") or []
    if not sources:
        print("[error] STATE has no source_files", file=sys.stderr)
        return 2
    source = job_root / sources[0]
    if not source.is_file():
        print(f"[error] source missing: {source}", file=sys.stderr)
        return 2

    ok, detail = bk.check_available(args.backend)
    if not ok:
        print(f"[error] {detail}", file=sys.stderr)
        return 2

    extra: list[str] = []
    if args.force_page_render:
        extra.append("--force-page-render")
    if args.max_rows is not None:
        extra += ["--max-rows", str(args.max_rows)]
    if args.keep_formulas:
        extra.append("--keep-formulas")
    if args.no_pdf_headings:
        extra.append("--no-pdf-headings")

    workdir = Path(tempfile.mkdtemp(prefix="afm_extract_"))
    try:
        proc = subproc.run_text(
            [sys.executable, str(bk.extractor_path(args.backend)), str(source), "-o", str(workdir), *extra],
            capture_output=True,
        )
        console = proc.stdout + proc.stderr
        if proc.returncode != 0:
            print(console, file=sys.stderr)
            print(f"[error] backend extractor failed (rc={proc.returncode})", file=sys.stderr)
            return 1

        skeleton = _find_skeleton(workdir)
        meta_file = _find_meta(workdir)
        if skeleton is None or meta_file is None:
            print(f"[error] backend produced no skeleton/meta in {workdir}", file=sys.stderr)
            return 1
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[error] backend extract_meta is unreadable: {e}", file=sys.stderr)
            return 1

        # clear regenerated dirs, then map outputs into the bundle
        _reset_dirs(job_root)
        dst_skeleton = job_root / P.EXTRACTED_TEXT / skeleton.name
        shutil.copy2(skeleton, dst_skeleton)

        images_dst = job_root / P.EXTRACTED_IMAGES
        pages_dst = job_root / P.EXTRACTED_PAGES
        image_dir = Path(meta.get("image_dir") or (workdir / "extracted_images"))
        n_img, n_page = _map_images(image_dir, images_dst, pages_dst)

        # rewrite meta paths to bundle-relative, keep original under backend_*
        meta["backend_skeleton_file"] = meta.get("skeleton_file")
        meta["backend_image_dir"] = meta.get("image_dir")
        meta["skeleton_file"] = f"{P.EXTRACTED_TEXT}/{skeleton.name}"
        meta["image_dir"] = P.EXTRACTED_IMAGES
        meta["pages_dir"] = P.EXTRACTED_PAGES
        meta["mapped_image_count"] = n_img
        meta["mapped_page_count"] = n_page
        (job_root / P.EXTRACT_META).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        _quality_report(job_root, meta, n_img, n_page, console)
        _seed_slots(job_root)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"[ok] extraction mapped into bundle: {job_root}")
    print(f"     skeleton : extracted/text/{dst_skeleton.name}")
    print(f"     images   : {n_img}  pages: {n_page}")
    print(f"     meta     : extracted/extract_meta.json")
    print("     next: run the Phase 1 gate ->")
    print(f'       {sys.executable} scripts/run_python.py validators/validate_extraction.py --job "{job_root}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
