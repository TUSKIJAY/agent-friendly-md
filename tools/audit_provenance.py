#!/usr/bin/env python3
"""Phase 4 audit: provenance depth plus comments/revisions preservation."""
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

FOUND_BY = "audit_provenance.py"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:48] or "item"


def _anchor_complete(anchor: dict | None) -> bool:
    if not isinstance(anchor, dict):
        return False
    kind = anchor.get("kind")
    keys = IR.ANCHOR_REQUIRED_KEYS.get(kind)
    return bool(keys) and all(anchor.get(k) is not None for k in keys)


def _issue(issue_id: str, source_block_id: str, anchor: dict | None,
           text: str, action: str) -> dict:
    return ISS.new_issue(
        issue_id=issue_id,
        severity="major",
        category="provenance",
        source_block_id=source_block_id,
        source_anchor=anchors.format_anchor(anchor),
        issue=text,
        required_action=action,
        found_by=FOUND_BY,
    )


def _read_comment_file(path: Path) -> tuple[list[dict], list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [], [f"{path.name}: {e}"]
    if not text.strip():
        return [], []
    if path.suffix == ".jsonl":
        items, errors = [], []
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{path.name}:{line_no}: {e}")
                continue
            if isinstance(obj, dict):
                obj["_origin"] = f"{path.name}:{line_no}"
                items.append(obj)
        return items, errors
    if path.suffix == ".json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return [], [f"{path.name}: {e}"]
        if isinstance(obj, list):
            rows = obj
        elif isinstance(obj, dict):
            rows = list(obj.get("comments", []) or []) + list(obj.get("revisions", []) or [])
        else:
            rows = []
        items = [row for row in rows if isinstance(row, dict)]
        for idx, item in enumerate(items, 1):
            item["_origin"] = f"{path.name}:{idx}"
        return items, []
    return [{"id": path.stem, "text": text.strip(), "_origin": path.name}], []


def _comment_items(job_root: Path) -> tuple[list[dict], list[str]]:
    comments_dir = job_root / "extracted" / "comments"
    if not comments_dir.is_dir():
        return [], []
    items, errors = [], []
    for path in sorted(p for p in comments_dir.iterdir() if p.is_file()):
        loaded, errs = _read_comment_file(path)
        items.extend(loaded)
        errors.extend(errs)
    return items, errors


def audit(job_root: Path, blocks: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for block in blocks:
        if block.get("type") not in ("table", "figure", "formula"):
            continue
        if not _anchor_complete(block.get("source_anchor")):
            findings.append(_issue(
                f"provenance_{block.get('id', 'missing')}_anchor_incomplete",
                str(block.get("id", "")),
                block.get("source_anchor"),
                "High-value block has an incomplete source_anchor.",
                "Rebuild provenance so the block can be traced to a page, slide, sheet range, or Word paragraph.",
            ))
    comments, parse_errors = _comment_items(job_root)
    for err in parse_errors:
        findings.append(_issue(
            f"provenance_comments_{_slug(err)}_parse_error",
            "",
            None,
            f"Comment/revision artifact is unreadable: {err}",
            "Repair the extracted comment/revision artifact or rerun extraction.",
        ))
    for idx, item in enumerate(comments, 1):
        origin = str(item.get("_origin") or item.get("id") or idx)
        anchor = item.get("source_anchor")
        if not str(item.get("text") or item.get("comment") or item.get("revision") or "").strip():
            findings.append(_issue(
                f"provenance_comment_{_slug(origin)}_text_missing", "", anchor,
                "Comment/revision item has no preserved text.",
                "Recover the comment/revision text from the source Word document.",
            ))
        if not _anchor_complete(anchor):
            findings.append(_issue(
                f"provenance_comment_{_slug(origin)}_anchor_missing", "", anchor,
                "Comment/revision item is missing a complete source_anchor.",
                "Preserve its Word heading/paragraph anchor or page anchor before packaging.",
            ))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Audit provenance and write review/issues.jsonl.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        blocks = IR.read_blocks(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1
    findings = audit(job_root, blocks)
    issues, errors = ISS.upsert_generated(job_root / P.REVIEW_ISSUES, FOUND_BY, findings)
    (job_root / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved(ISS.unresolved_entries(issues)), encoding="utf-8")
    print(f"[ok] audit_provenance: findings={len(findings)}")
    if errors:
        print(f"[warn] preserved existing issue parse errors: {errors[:3]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
