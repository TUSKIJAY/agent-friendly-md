#!/usr/bin/env python3
"""Phase 4 audit: formula visual-proofing readiness."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import anchors  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import paths as P  # noqa: E402

FOUND_BY = "audit_formulas.py"
LEFT_RE = re.compile(r"\\left\b")
RIGHT_RE = re.compile(r"\\right\b")


def _balanced(latex: str) -> bool:
    return latex.count("{") == latex.count("}") and len(LEFT_RE.findall(latex)) == len(RIGHT_RE.findall(latex))


def _confidence(block: dict) -> float:
    try:
        return float(block.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _issue(block: dict, code: str, severity: str, text: str, action: str) -> dict:
    return ISS.new_issue(
        issue_id=f"formula_{block.get('id', 'missing')}_{code}",
        severity=severity,
        category="formula",
        source_block_id=str(block.get("id", "")),
        source_anchor=anchors.format_anchor(block.get("source_anchor")),
        issue=text,
        required_action=action,
        found_by=FOUND_BY,
    )


def audit_blocks(blocks: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for block in [b for b in blocks if b.get("type") == "formula"]:
        formula = block.get("formula") or {}
        latex = str(formula.get("latex") or "").strip()
        audit = formula.setdefault("audit", {})
        audit["latex_present"] = bool(latex)
        audit["balance_check"] = "pass" if latex and _balanced(latex) else "fail"
        audit["visual_check"] = formula.get("visual_check") or ""
        if not latex:
            findings.append(_issue(
                block, "empty_latex", "major",
                "Formula block has no LaTeX representation.",
                "Re-read the source formula and fill formula.latex before packaging.",
            ))
        elif not _balanced(latex):
            findings.append(_issue(
                block, "unbalanced_latex", "major",
                "Formula LaTeX has unbalanced braces or left/right delimiters.",
                "Compare against the rendered source and correct formula.latex.",
            ))
        if formula.get("visual_check") == "needs_review" or block.get("needs_review"):
            findings.append(_issue(
                block, "needs_visual_proof", "minor",
                "Formula is flagged for visual proofing.",
                "Open the source page and confirm the LaTeX matches the original formula.",
            ))
        if _confidence(block) < 0.8:
            findings.append(_issue(
                block, "low_confidence", "minor",
                "Formula block confidence is below 0.8.",
                "Review the source formula manually and either fix it or accept the residual risk.",
            ))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Audit formulas and write review/issues.jsonl.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        blocks, doc = IR.load_ir(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1
    findings = audit_blocks(blocks)
    IR.save_all(job_root, blocks, doc)
    issues, errors = ISS.upsert_generated(job_root / P.REVIEW_ISSUES, FOUND_BY, findings)
    (job_root / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved(ISS.unresolved_entries(issues)), encoding="utf-8")
    print(f"[ok] audit_formulas: findings={len(findings)}")
    if errors:
        print(f"[warn] preserved existing issue parse errors: {errors[:3]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
