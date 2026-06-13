#!/usr/bin/env python3
"""Phase 4 audit: figure/chart/screenshot asset completeness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import anchors  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import paths as P  # noqa: E402

FOUND_BY = "audit_assets.py"


def _issue(block: dict, code: str, severity: str, text: str, action: str) -> dict:
    return ISS.new_issue(
        issue_id=f"figure_{block.get('id', 'missing')}_{code}",
        severity=severity,
        category="figure",
        source_block_id=str(block.get("id", "")),
        source_anchor=anchors.format_anchor(block.get("source_anchor")),
        issue=text,
        required_action=action,
        found_by=FOUND_BY,
    )


def _estimated_values_need_basis(fig: dict) -> bool:
    values = fig.get("estimated_values") or []
    if not isinstance(values, list):
        return True
    for item in values:
        if not isinstance(item, dict) or item.get("basis") != "图上估读":
            return True
    return False


def audit_blocks(blocks: list[dict], job_root: Path) -> list[dict]:
    findings: list[dict] = []
    for block in [b for b in blocks if b.get("type") == "figure"]:
        fig = block.get("figure") or {}
        audit = fig.setdefault("audit", {})
        likely_noise = bool(fig.get("likely_noise") or block.get("likely_noise"))
        asset_file = fig.get("asset_file") or ""
        exists = bool(asset_file) and (job_root / asset_file).is_file()
        audit["asset_exists"] = exists
        audit["caption_present"] = bool(str(fig.get("caption") or "").strip())
        audit["description_present"] = bool(str(fig.get("description") or "").strip())
        audit["likely_noise"] = likely_noise
        if not exists:
            findings.append(_issue(
                block, "asset_missing", "major",
                f"Figure asset file is missing or not declared: {asset_file or '<empty>'}.",
                "Restore the extracted image asset or fix figure.asset_file/asset_id.",
            ))
        if not audit["caption_present"] and not likely_noise:
            findings.append(_issue(
                block, "caption_missing", "minor",
                "Figure has no caption.",
                "Recover the source caption or add an editor note explaining why it is absent.",
            ))
        if not audit["description_present"] and not likely_noise:
            findings.append(_issue(
                block, "description_missing", "major",
                "Figure/chart/screenshot has no semantic description.",
                "Use the visual review step to write figure.description from the source image.",
            ))
        if _estimated_values_need_basis(fig) and not likely_noise:
            findings.append(_issue(
                block, "estimated_value_basis_missing", "major",
                "At least one estimated figure value is missing basis='图上估读'.",
                "Mark every visually estimated value with basis='图上估读'.",
            ))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Audit figure assets and write review/issues.jsonl.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        blocks, doc = IR.load_ir(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1
    findings = audit_blocks(blocks, job_root)
    IR.save_all(job_root, blocks, doc)
    issues, errors = ISS.upsert_generated(job_root / P.REVIEW_ISSUES, FOUND_BY, findings)
    (job_root / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved(ISS.unresolved_entries(issues)), encoding="utf-8")
    print(f"[ok] audit_assets: findings={len(findings)}")
    if errors:
        print(f"[warn] preserved existing issue parse errors: {errors[:3]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
