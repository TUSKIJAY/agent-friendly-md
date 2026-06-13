#!/usr/bin/env python3
"""Produce a TEMPORARY output/main.md via the backend assembler (v0.2 bridge).

    python3 scripts/run_python.py tools/assemble_backend_md.py --job "<job-dir>"

This is a stop-gap so a job yields a readable main.md before the IR-based
assembler (assemble_agent_md.py, v0.6) exists. It feeds the backend assembler
the bundle's skeleton + vision cache + summary seed + cleaning decisions.
The result is NOT promoted/packaged — it is a Phase 1/v0.2 preview only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import backend as bk  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import subproc  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Temp main.md via backend assembler (v0.2 bridge).")
    ap.add_argument("--job", required=True)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--skip-undescribed", action="store_true",
                    help="silently drop undescribed image placeholders instead of [未解析]")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    _ = js.load_state(job_root)

    text_dir = job_root / P.EXTRACTED_TEXT
    skeletons = sorted(text_dir.glob("*_skeleton.md")) if text_dir.is_dir() else []
    if not skeletons:
        print("[error] no skeleton; run run_extraction.py first", file=sys.stderr)
        return 2
    skeleton = skeletons[0]
    vision_cache = job_root / P.REVIEW_VISION_CACHE
    summary = job_root / P.IR_SUMMARY_SEED
    clean = job_root / P.REVIEW_CLEANING
    out = job_root / P.OUTPUT_MAIN

    ok, detail = bk.check_available(args.backend)
    if not ok:
        print(f"[error] {detail}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable, str(bk.assembler_path(args.backend)),
        str(skeleton), str(vision_cache), str(out),
        "--summary-file", str(summary),
        "--clean-decisions", str(clean),
        "--force",
    ]
    if args.skip_undescribed:
        cmd.append("--skip-undescribed")

    proc = subproc.run_text(cmd, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        print(f"[error] backend assembler failed (rc={proc.returncode})", file=sys.stderr)
        return 1
    if proc.stdout.strip():
        print(proc.stdout.strip())
    print(f"[ok] TEMP main.md written: {out}")
    print("     (v0.2 bridge — not promoted/packaged; replaced by IR assembler in v0.6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
