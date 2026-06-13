#!/usr/bin/env python3
"""Phase 0 — Intake: create a stable job bundle for a source document (PLAN §5).

    python3 scripts/run_python.py tools/init_document_job.py --source "<file>"

Creates ``<jobs-root>/<slug>-<YYYYMMDD>/`` with the full directory skeleton,
copies the source in, writes a provisional STATE.json and a *draft*
output/manifest.json. It does not parse the document (that is Phase 1) — the
profile is provisional and confirmed later by validate_extraction.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# self-bootstrap so this runs via the wrapper or directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import jobstate as js  # noqa: E402

_ALLOWED = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def slugify(name: str) -> str:
    """ASCII lower slug; non-ASCII collapsed to hyphens. Empty -> 'doc'."""
    out: list[str] = []
    prev_dash = False
    for ch in name.lower():
        if ch in _ALLOWED:
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    slug = "".join(out).strip("-_")
    return slug or "doc"


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create a job bundle for a document.")
    ap.add_argument("--source", action="append", required=True,
                    help="source document (repeatable for multi-file jobs)")
    ap.add_argument("--jobs-root", default=None,
                    help="bundle parent dir (default: <source_dir>/.agent-friendly-md/jobs)")
    ap.add_argument("--slug", default=None, help="override the document slug")
    ap.add_argument("--date", default=None, help="override job date (YYYYMMDD)")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--max-sheets", type=int, default=None)
    ap.add_argument("--max-markdown-bytes", type=int, default=None)
    ap.add_argument("--max-blocks", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="reuse an existing job dir")
    return ap.parse_args(argv)


def resolve_sources(raw: list[str]) -> list[Path]:
    srcs: list[Path] = []
    for s in raw:
        p = Path(s).expanduser().resolve()
        if not p.is_file():
            print(f"[error] source not found: {s}", file=sys.stderr)
            raise SystemExit(2)
        srcs.append(p)
    return srcs


def split_overrides(args: argparse.Namespace) -> dict[str, int]:
    thr = dict(js.DEFAULT_SPLIT_THRESHOLDS)
    for cli_key, thr_key in (
        ("max_pages", "max_pages"),
        ("max_sheets", "max_sheets"),
        ("max_markdown_bytes", "max_markdown_bytes"),
        ("max_blocks", "max_blocks"),
    ):
        v = getattr(args, cli_key)
        if v is not None:
            thr[thr_key] = v
    return thr


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    sources = resolve_sources(args.source)
    primary = sources[0]

    slug = args.slug or slugify(primary.stem)
    date = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    job_id = f"{slug}-{date}"

    jobs_root = (Path(args.jobs_root).expanduser().resolve()
                 if args.jobs_root
                 else primary.parent / ".agent-friendly-md" / "jobs")
    job_root = jobs_root / job_id

    if job_root.exists() and not args.force:
        print(f"[error] job dir already exists: {job_root}\n"
              f"        pass --force to reuse, or --slug/--date to disambiguate.",
              file=sys.stderr)
        return 2

    P.ensure_skeleton(job_root)

    # copy sources in
    source_rels: list[str] = []
    for s in sources:
        dest = job_root / "source" / s.name
        shutil.copy2(s, dest)
        source_rels.append(f"source/{s.name}")

    thresholds = split_overrides(args)

    state = js.new_state(
        job_id=job_id,
        source_files=source_rels,
        job_root=str(job_root),
        primary_ext=primary.suffix,
        split_thresholds=thresholds,
    )
    js.save_state(job_root, state)

    draft = mf.new_draft(
        job_id=job_id,
        document_slug=slug,
        sources=[mf.source_entry(job_root, rel) for rel in source_rels],
        split_thresholds=thresholds,
    )
    (job_root / "output" / "manifest.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[ok] job bundle created: {job_root}")
    print(f"     job_id          : {job_id}")
    print(f"     primary_type    : {state['document_profile']['primary_type']}")
    print(f"     risk_level      : {state['document_profile']['risk_level']} (provisional)")
    print(f"     sources         : {', '.join(source_rels)}")
    print(f"     current_phase   : {state['current_phase']}")
    print("     next: run the Phase 0 gate ->")
    print(f'       {sys.executable} scripts/run_python.py validators/validate_state.py --job "{job_root}"')
    print(f'       {sys.executable} scripts/run_python.py validators/validate_manifest.py --job "{job_root}" --mode draft')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
