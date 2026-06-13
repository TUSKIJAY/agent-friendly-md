#!/usr/bin/env python3
"""v1.0 golden-example quality checks for ZHCAEJ4/TAA5212-style documents."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import golden_quality as GQ  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402

LEFT_RE = re.compile(r"\\left\b")
RIGHT_RE = re.compile(r"\\right\b")
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _balanced(latex: str) -> bool:
    return bool(latex.strip()) and latex.count("{") == latex.count("}") and len(LEFT_RE.findall(latex)) == len(RIGHT_RE.findall(latex))


def _confidence(block: dict) -> float:
    try:
        return float(block.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _requires_issue_tracking(block: dict) -> bool:
    content = block.get("content") if isinstance(block.get("content"), dict) else {}
    if content.get("likely_noise"):
        return False
    return bool(block.get("needs_review") or _confidence(block) < 0.8)


def _markdown_link_errors(job_root: Path) -> list[str]:
    files = [job_root / P.OUTPUT_MAIN] if (job_root / P.OUTPUT_MAIN).is_file() else []
    parts = job_root / P.OUTPUT_PARTS
    if parts.is_dir():
        files.extend(sorted(parts.glob("*.md")))
    errors: list[str] = []
    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in MD_LINK_RE.findall(text):
            if re.match(r"^[a-z]+://", target) or target.startswith("#"):
                continue
            local = target.split("#", 1)[0]
            if local and not (md.parent / local).exists():
                errors.append(f"{md.name}->{local}")
    return errors


def build_report(job_root: Path, baseline: Path | None, expect: set[str]) -> dict:
    blocks = IR.read_blocks(job_root)
    main_path = job_root / P.OUTPUT_MAIN
    main_text = main_path.read_text(encoding="utf-8")
    issues = ISS.read_issues(job_root / P.REVIEW_ISSUES)[0] if (job_root / P.REVIEW_ISSUES).is_file() else []
    unresolved_ids = {i.get("source_block_id") for i in ISS.unresolved_entries(issues)}
    figures = [b for b in blocks if b.get("type") == "figure"]
    formulas = [b for b in blocks if b.get("type") == "formula"]
    registers = [
        b for b in blocks if b.get("type") == "table"
        and (b.get("table") or {}).get("audit", {}).get("hard_table_type") == "register"
    ]
    metrics = GQ.md_metrics(main_text)
    title = GQ.title_report(main_text)
    toc_items = GQ.toc_items(main_text)
    toc_required = metrics["headings"] > 1 or any(b.get("type") == "heading" for b in blocks)
    toc_coherence = GQ.toc_coherence_report(main_text)
    opening_noise = GQ.opening_noise_report(main_text)
    baseline_comparison = GQ.baseline_compare(main_text, baseline)
    checks = {
        "main_present": main_path.is_file(),
        "main_has_h1": metrics["h1"] >= 1,
        "main_has_meaningful_title": title["ok"],
        "main_has_summary_block": bool(GQ.SUMMARY_RE.search(main_text)),
        "main_has_nonempty_toc": not toc_required or bool(toc_items),
        "toc_structurally_coherent": toc_coherence["ok"],
        "opening_noise_density_ok": opening_noise["ok"],
        "main_has_source_anchors": metrics["source_anchors"] > 0,
        "main_has_no_placeholders": metrics["placeholders"] == 0,
        "figures_expected": "figure" not in expect or bool(figures),
        "figure_assets_complete": all((job_root / (b.get("figure") or {}).get("asset_file", "")).is_file() for b in figures),
        "figure_descriptions_complete": all((b.get("figure") or {}).get("caption") and (b.get("figure") or {}).get("description") for b in figures),
        "formulas_expected": "formula" not in expect or bool(formulas),
        "formulas_latex_balanced": all(_balanced(str((b.get("formula") or {}).get("latex") or "")) for b in formulas),
        "register_tables_expected": "register" not in expect or bool(registers),
        "register_tables_audited": all((b.get("table") or {}).get("audit", {}).get("hard_column_check") == "pass" for b in registers),
    }
    markdown_link_errors = _markdown_link_errors(job_root)
    checks["markdown_links_resolve"] = not markdown_link_errors
    low_conf = [b for b in blocks if _requires_issue_tracking(b)]
    checks["low_confidence_tracked"] = all(b.get("id") in unresolved_ids for b in low_conf)
    checks["baseline_criteria_pass"] = (
        baseline_comparison is None or baseline_comparison.get("status") == "pass"
    )
    failed = [name for name, ok in checks.items() if not ok]
    score = (len(checks) - len(failed)) / len(checks)
    return {
        "schema_version": "agent-friendly-md-golden-quality/0.1",
        "created_at": js.now_iso(),
        "status": "fail" if failed else "pass",
        "score": round(score, 3),
        "checks": checks,
        "failed_checks": failed,
        "counts": {
            "blocks": len(blocks),
            "figures": len(figures),
            "formulas": len(formulas),
            "register_tables": len(registers),
            "low_confidence": len(low_conf),
            "issues": len(issues),
            "markdown_link_errors": len(markdown_link_errors),
            "toc_items": len(toc_items),
        },
        "structure_quality": {
            "title": title,
            "toc_required": toc_required,
            "toc_coherence": toc_coherence,
            "opening_noise": opening_noise,
        },
        "baseline_comparison": baseline_comparison,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Check golden-example quality.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--baseline-md", default=None)
    ap.add_argument("--expect", action="append", choices=["figure", "formula", "register"], default=[])
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    baseline = Path(args.baseline_md).expanduser().resolve() if args.baseline_md else None
    try:
        report = build_report(job_root, baseline, set(args.expect))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] golden quality check failed: {e}", file=sys.stderr)
        return 1
    out = job_root / "review" / "golden_quality.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] golden quality: {report['status']} score={report['score']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
