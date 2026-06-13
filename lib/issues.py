"""review/issues.jsonl schema helpers for unresolved projections."""
from __future__ import annotations

import json
from pathlib import Path

from lib import jobstate as js

SEVERITIES = ("blocker", "major", "minor", "info")
STATUSES = ("open", "accepted", "fixed")
CATEGORIES = ("ocr", "table", "formula", "figure", "provenance", "source_conflict", "rendering")
REQUIRED_FIELDS = (
    "id", "severity", "status", "accepted_by", "accepted_reason",
    "source_block_id", "source_anchor", "category", "issue",
    "required_action", "found_by", "created_at",
)


def read_issues(path: str | Path) -> tuple[list[dict], list[str]]:
    """Read JSONL issues, returning parsed entries plus line-level errors."""
    issues: list[dict] = []
    errors: list[str] = []
    p = Path(path)
    with p.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"line {n}: {e}")
                continue
            if not isinstance(item, dict):
                errors.append(f"line {n}: issue must be an object")
                continue
            issues.append(item)
    return issues, errors


def unresolved_entries(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i.get("status") != "fixed"]


def write_issues(path: str | Path, issues: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for item in issues:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def new_issue(*, issue_id: str, severity: str, category: str, source_block_id: str,
              source_anchor: str, issue: str, required_action: str,
              found_by: str) -> dict:
    return {
        "id": issue_id,
        "severity": severity,
        "status": "open",
        "accepted_by": "",
        "accepted_reason": "",
        "source_block_id": source_block_id,
        "source_anchor": source_anchor,
        "category": category,
        "issue": issue,
        "required_action": required_action,
        "found_by": found_by,
        "created_at": js.now_iso(),
    }


def upsert_generated(path: str | Path, found_by: str, generated: list[dict]) -> tuple[list[dict], list[str]]:
    existing, errors = read_issues(path) if Path(path).is_file() else ([], [])
    if errors:
        return existing, errors
    by_id = {str(i.get("id")): i for i in existing if i.get("id")}
    generated_by_id = {str(i["id"]): i for i in generated}
    result = [i for i in existing if i.get("found_by") != found_by]
    for old in [i for i in existing if i.get("found_by") == found_by]:
        old_id = str(old.get("id", ""))
        if old_id not in generated_by_id:
            fixed = dict(old)
            fixed["status"] = "fixed"
            fixed["accepted_by"] = ""
            fixed["accepted_reason"] = ""
            result.append(fixed)
    for new in generated:
        old = by_id.get(str(new["id"]))
        if old and old.get("found_by") == found_by:
            merged = dict(new)
            if old.get("status") == "accepted":
                merged["status"] = "accepted"
                merged["accepted_by"] = old.get("accepted_by", "")
                merged["accepted_reason"] = old.get("accepted_reason", "")
            merged["created_at"] = old.get("created_at") or new["created_at"]
            result.append(merged)
        else:
            result.append(new)
    write_issues(path, result)
    return result, errors


def render_unresolved(entries: list[dict]) -> str:
    lines = ["# Unresolved", ""]
    if not entries:
        lines.append("_No unresolved issues._")
        return "\n".join(lines) + "\n"
    for item in entries:
        lines.extend([
            f"## {item.get('id', '<missing-id>')}",
            "",
            f"- severity: {item.get('severity', '')}",
            f"- status: {item.get('status', '')}",
            f"- accepted_by: {item.get('accepted_by', '')}",
            f"- accepted_reason: {item.get('accepted_reason', '')}",
            f"- source_block_id: {item.get('source_block_id', '')}",
            f"- source_anchor: {item.get('source_anchor', '')}",
            f"- category: {item.get('category', '')}",
            f"- issue: {item.get('issue', '')}",
            f"- required_action: {item.get('required_action', '')}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
