#!/usr/bin/env python3
"""Phase 4 gate: verify special audits were run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "4_audit"
REQUIRED_TOOLS = {
    "tools/audit_tables.py",
    "tools/audit_formulas.py",
    "tools/audit_assets.py",
    "tools/audit_provenance.py",
}


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    path = job_root / P.REVIEW_AUDIT_SUMMARY
    checks.append(Check("audit_summary_present", path.is_file(), message=str(path)))
    if not path.is_file():
        return checks
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        checks.append(Check("audit_summary_parseable", False, message=str(e)))
        return checks
    checks.append(Check("audit_schema", summary.get("schema_version") == "agent-friendly-md-audit-summary/0.1",
                        message=str(summary.get("schema_version"))))
    tools = summary.get("tools") if isinstance(summary.get("tools"), list) else []
    seen = {t.get("tool") for t in tools if isinstance(t, dict)}
    missing = sorted(REQUIRED_TOOLS - seen)
    checks.append(Check("all_special_audits_ran", not missing,
                        message="all present" if not missing else f"missing: {missing}"))
    bad_exit = [t for t in tools if isinstance(t, dict) and t.get("exit_code") not in (0, 2)]
    checks.append(Check("audit_tool_exits_ok", not bad_exit,
                        message="ok" if not bad_exit else f"bad exits: {bad_exit[:3]}"))
    parse_errors = summary.get("parse_errors") or []
    checks.append(Check("audit_issue_file_parseable", not parse_errors,
                        message="ok" if not parse_errors else f"{parse_errors[:3]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate Phase 4 audit summary")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_audit_summary", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_audit_summary", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
