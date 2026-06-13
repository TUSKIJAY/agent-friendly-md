#!/usr/bin/env python3
"""Phase 4: run all special audits and write audit_summary.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import subproc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"
AUDIT_TOOLS = [
    "tools/audit_tables.py",
    "tools/audit_formulas.py",
    "tools/audit_assets.py",
    "tools/audit_provenance.py",
]


def _run(tool: str, job_root: Path) -> dict:
    result = subproc.run_text(
        [sys.executable, str(WRAPPER), tool, "--job", str(job_root)],
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return {"tool": tool, "exit_code": result.returncode}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run Phase 4 special audits.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    results = [_run(tool, job_root) for tool in AUDIT_TOOLS]
    issues_path = job_root / P.REVIEW_ISSUES
    issues, parse_errors = ISS.read_issues(issues_path) if issues_path.is_file() else ([], ["review/issues.jsonl missing"])
    summary = {
        "schema_version": "agent-friendly-md-audit-summary/0.1",
        "created_at": js.now_iso(),
        "phase": "4_audit",
        "tools": results,
        "issue_count": len(issues),
        "parse_errors": parse_errors,
    }
    (job_root / P.REVIEW_AUDIT_SUMMARY).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if any(r["exit_code"] == 1 for r in results) or parse_errors:
        return 1
    if any(r["exit_code"] == 2 for r in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
