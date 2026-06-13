#!/usr/bin/env python3
"""Phase 3 — Semantic Compile: formula normalization (v0.5).

    python3 scripts/run_python.py tools/normalize_formulas.py --job "<job-dir>"

For each formula block: tidies the LaTeX (strips stray $ and whitespace), checks
brace/\\left-\\right balance, assigns a sequential equation_no where missing, and
sets visual_check (ok | needs_review). Unbalanced LaTeX is flagged for the
visual-proofing pass (v0.9), never silently "fixed".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import report  # noqa: E402

_LEFT = re.compile(r"\\left\b")
_RIGHT = re.compile(r"\\right\b")
# a single matched leading+trailing $/$$ pair, trailing one not escaped (\$)
_DELIMS = re.compile(r"^\${1,2}(.*?)(?<!\\)\${1,2}$", re.S)


def _strip_delims(latex: str) -> str:
    s = latex.strip()
    m = _DELIMS.match(s)
    return m.group(1).strip() if m else s


def _balanced(latex: str) -> bool:
    if latex.count("{") != latex.count("}"):
        return False
    if len(_LEFT.findall(latex)) != len(_RIGHT.findall(latex)):
        return False
    return True


def normalize_formulas(blocks: list[dict]) -> tuple[int, int]:
    formulas = [b for b in blocks if b["type"] == "formula"]
    has_no_number = all(not b["formula"].get("equation_no") for b in formulas)
    cleaned = flagged = 0
    seq = 0
    for b in formulas:
        f = b["formula"]
        latex = _strip_delims(f.get("latex") or "")
        if latex != f.get("latex"):
            cleaned += 1
        f["latex"] = latex
        if has_no_number:
            seq += 1
            f["equation_no"] = str(seq)
        ok = _balanced(latex) and bool(latex)
        f["visual_check"] = "ok" if ok else "needs_review"
        if not ok:
            b["needs_review"] = True
            flagged += 1
    return cleaned, flagged


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Normalize formulas.")
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

    n_clean, n_flag = normalize_formulas(blocks)
    IR.save_all(job_root, blocks, doc)

    report.upsert_section(
        job_root / "review" / "semantic_compile.md", "Semantic Compile", "normalize_formulas",
        f"- latex cleaned: {n_clean}\n- flagged for visual proofing (unbalanced/empty): {n_flag}")

    print(f"[ok] normalize_formulas: cleaned={n_clean}, flagged={n_flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
