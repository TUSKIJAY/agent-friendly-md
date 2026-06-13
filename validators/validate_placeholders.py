#!/usr/bin/env python3
"""Phase 5 gate: detect placeholders, TODOs, bad characters, and unresolved coverage."""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "5_assembly"
VISION_RE = re.compile(r"\[VISION_PLACEHOLDER_[^\]]+\]")
TODO_RE = re.compile(r"\[(?:TODO|todo)\]")
UNRESOLVED_RE = re.compile(r"\[未解析:[^\]]+\]")


def _markdown_files(job_root: Path) -> list[Path]:
    files = []
    main = job_root / P.OUTPUT_MAIN
    if main.is_file():
        files.append(main)
    parts_dir = job_root / P.OUTPUT_PARTS
    if parts_dir.is_dir():
        files.extend(sorted(parts_dir.glob("*.md")))
    return files


def _read_markdown(files: list[Path]) -> tuple[dict[Path, str], list[str]]:
    texts: dict[Path, str] = {}
    errors: list[str] = []
    for path in files:
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: {e}")
    return texts, errors


def _bad_controls(text: str) -> list[str]:
    bad = []
    for i, ch in enumerate(text):
        if ch in "\n\r\t":
            continue
        if unicodedata.category(ch) == "Cc":
            bad.append(f"U+{ord(ch):04X}@{i}")
    return bad


def _payload(marker: str) -> str:
    if marker.startswith("[未解析:"):
        return marker[len("[未解析:"):].rstrip("]").strip()
    if marker.startswith("[VISION_PLACEHOLDER_"):
        return marker[len("[VISION_PLACEHOLDER_"):].rstrip("]").strip()
    return marker.strip("[]")


def _documented(marker: str, entries: list[dict]) -> bool:
    payload = _payload(marker)
    for item in entries:
        text = "\n".join(str(item.get(k, "")) for k in ("id", "issue", "required_action"))
        if marker in text or (payload and payload in text):
            return True
    return False


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    files = _markdown_files(job_root)
    checks.append(Check("main_or_parts_present", bool(files), message=f"{len(files)} markdown file(s)"))
    unresolved_path = job_root / P.REVIEW_UNRESOLVED
    issues_path = job_root / P.REVIEW_ISSUES
    checks.append(Check("unresolved_present", unresolved_path.is_file(), message=str(unresolved_path)))
    checks.append(Check("issues_present", issues_path.is_file(), message=str(issues_path)))
    if not files:
        return checks
    texts, errors = _read_markdown(files)
    checks.append(Check("markdown_readable", not errors,
                        message="ok" if not errors else f"{errors[:3]}"))
    if errors:
        return checks
    entries: list[dict] = []
    if issues_path.is_file():
        try:
            issues, parse_errors = ISS.read_issues(issues_path)
            entries = ISS.unresolved_entries(issues)
            checks.append(Check("issues_parseable", not parse_errors,
                                message="ok" if not parse_errors else f"{parse_errors[:3]}"))
        except OSError as e:
            checks.append(Check("issues_readable", False, message=str(e)))

    vision, todos, pending, unresolved = [], [], [], []
    replacements, controls = [], []
    for path, text in texts.items():
        label = path.relative_to(job_root).as_posix()
        vision.extend(f"{label}: {m.group(0)}" for m in VISION_RE.finditer(text))
        todos.extend(f"{label}: {m.group(0)}" for m in TODO_RE.finditer(text))
        if "待补充" in text:
            pending.append(label)
        unresolved.extend(f"{label}: {m.group(0)}" for m in UNRESOLVED_RE.finditer(text))
        if "\ufffd" in text:
            replacements.append(label)
        bad = _bad_controls(text)
        if bad:
            controls.append(f"{label}: {bad[:3]}")

    marker_values = [item.split(": ", 1)[1] for item in [*vision, *unresolved] if ": " in item]
    undocumented = [m for m in marker_values if not _documented(m, entries)]
    checks.append(Check("no_vision_placeholders", not vision,
                        message="none" if not vision else f"{vision[:5]}"))
    checks.append(Check("no_todo_markers", not todos,
                        message="none" if not todos else f"{todos[:5]}"))
    checks.append(Check("no_pending_text", not pending,
                        message="none" if not pending else f"待补充 in {pending[:5]}"))
    checks.append(Check("no_replacement_char", not replacements,
                        message="none" if not replacements else f"U+FFFD in {replacements[:5]}"))
    checks.append(Check("no_control_chars", not controls,
                        message="none" if not controls else f"{controls[:5]}"))
    checks.append(Check("unresolved_markers_documented", not undocumented,
                        message="all documented" if not undocumented else f"missing: {undocumented[:5]}"))
    checks.append(Check("unresolved_markers_present", not unresolved, level="warn",
                        message="none" if not unresolved else f"{unresolved[:5]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate placeholders in assembled Markdown")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_placeholders", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_placeholders", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
