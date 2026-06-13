#!/usr/bin/env python3
"""Phase 4 gate: validate issues.jsonl and unresolved.md projection."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "4_audit"


def _missing_fields(issue: dict) -> list[str]:
    return [k for k in ISS.REQUIRED_FIELDS if k not in issue]


def _issue_id(issue: dict) -> str:
    return str(issue.get("id") or "<missing-id>")


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    issues_path = job_root / P.REVIEW_ISSUES
    unresolved_path = job_root / P.REVIEW_UNRESOLVED
    checks.append(Check("issues_present", issues_path.is_file(), message=str(issues_path)))
    checks.append(Check("unresolved_present", unresolved_path.is_file(), message=str(unresolved_path)))
    if not issues_path.is_file() or not unresolved_path.is_file():
        return checks
    try:
        issues, parse_errors = ISS.read_issues(issues_path)
        unresolved_text = unresolved_path.read_text(encoding="utf-8")
    except OSError as e:
        checks.append(Check("unresolved_io", False, message=str(e)))
        return checks

    checks.append(Check("issues_parseable", not parse_errors,
                        message="ok" if not parse_errors else f"{parse_errors[:3]}"))
    missing = [_issue_id(i) for i in issues if _missing_fields(i)]
    checks.append(Check("required_fields", not missing,
                        message="all present" if not missing else f"missing fields: {missing[:5]}"))
    ids = [i.get("id") for i in issues]
    duplicates = sorted({i for i in ids if i and ids.count(i) > 1})
    checks.append(Check("unique_ids", not duplicates,
                        message="unique" if not duplicates else f"duplicates: {duplicates[:5]}"))

    bad_severity = [_issue_id(i) for i in issues if i.get("severity") not in ISS.SEVERITIES]
    bad_status = [_issue_id(i) for i in issues if i.get("status") not in ISS.STATUSES]
    bad_category = [_issue_id(i) for i in issues if i.get("category") not in ISS.CATEGORIES]
    checks.append(Check("severity_enum", not bad_severity,
                        message="ok" if not bad_severity else f"bad: {bad_severity[:5]}"))
    checks.append(Check("status_enum", not bad_status,
                        message="ok" if not bad_status else f"bad: {bad_status[:5]}"))
    checks.append(Check("category_enum", not bad_category,
                        message="ok" if not bad_category else f"bad: {bad_category[:5]}"))

    unresolved = ISS.unresolved_entries(issues)
    missing_projection = [i["id"] for i in unresolved if i.get("id") and i["id"] not in unresolved_text]
    fixed_projected = [_issue_id(i) for i in issues
                       if i.get("status") == "fixed" and i.get("id") and str(i.get("id")) in unresolved_text]
    missing_issue_text = [i["id"] for i in unresolved
                          if i.get("id") and i.get("issue") and i["issue"] not in unresolved_text]
    expected_projection = ISS.render_unresolved(unresolved).strip()
    actual_projection = unresolved_text.strip()
    checks.append(Check("unresolved_ids_projected", not missing_projection,
                        message="all unresolved ids projected" if not missing_projection else f"missing: {missing_projection[:5]}"))
    checks.append(Check("fixed_ids_not_projected", not fixed_projected,
                        message="fixed issues absent" if not fixed_projected else f"fixed still shown: {fixed_projected[:5]}"))
    checks.append(Check("unresolved_issue_text_projected", not missing_issue_text,
                        message="issue text projected" if not missing_issue_text else f"missing text: {missing_issue_text[:5]}"))
    checks.append(Check("unresolved_projection_exact", actual_projection == expected_projection,
                        message="matches issues.jsonl projection" if actual_projection == expected_projection
                        else "review/unresolved.md differs from issues.jsonl projection"))

    blocker_open = [_issue_id(i) for i in issues if i.get("severity") == "blocker" and i.get("status") == "open"]
    blocker_bad_accept = [_issue_id(i) for i in issues
                          if i.get("severity") == "blocker" and i.get("status") == "accepted"
                          and not (i.get("accepted_by") and i.get("accepted_reason"))]
    major_open = [_issue_id(i) for i in issues if i.get("severity") == "major" and i.get("status") == "open"]
    checks.append(Check("no_open_blockers", not blocker_open,
                        message="no open blockers" if not blocker_open else f"open: {blocker_open[:5]}"))
    checks.append(Check("accepted_blockers_documented", not blocker_bad_accept,
                        message="accepted blockers documented" if not blocker_bad_accept else f"bad: {blocker_bad_accept[:5]}"))
    checks.append(Check("major_open_notes", not major_open, level="warn",
                        message="no open majors" if not major_open else f"open: {major_open[:5]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate unresolved issue files")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_unresolved", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_unresolved", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
