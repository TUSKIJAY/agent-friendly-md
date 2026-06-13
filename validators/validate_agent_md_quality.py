#!/usr/bin/env python3
"""Phase 5 gate: validate assembled Agent Markdown quality basics."""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "5_assembly"
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â€|â€™|â€œ|â€\x9d|ï¼|ä¸|å[\\x80-\\xff]?)")
FORMULA_RE = re.compile(r"\$\$\n.*?\n\$\$", re.DOTALL)


def _markdown_files(job_root: Path) -> list[Path]:
    main = job_root / P.OUTPUT_MAIN
    files = [main] if main.is_file() else []
    parts = job_root / P.OUTPUT_PARTS
    if parts.is_dir():
        files.extend(sorted(parts.glob("*.md")))
    return files


def _bad_controls(text: str) -> list[str]:
    bad = []
    for i, ch in enumerate(text):
        if ch in "\n\r\t":
            continue
        if unicodedata.category(ch) == "Cc":
            bad.append(f"U+{ord(ch):04X}@{i}")
    return bad


def _table_separator_offsets(text: str) -> list[int]:
    offsets = []
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "---" in stripped:
            offsets.append(pos)
        pos += len(line)
    return offsets


def _table_section_has_anchor(text: str, offset: int) -> bool:
    next_heading = re.search(r"\n#{1,6}\s+\S", text[offset + 1:])
    end = offset + 1 + next_heading.start() if next_heading else len(text)
    return "〔源" in text[offset:end]


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    files = _markdown_files(job_root)
    checks.append(Check("main_or_parts_present", bool(files), message=f"{len(files)} markdown file(s)"))
    if not files:
        return checks
    texts: dict[Path, str] = {}
    errors: list[str] = []
    for path in files:
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: {e}")
    checks.append(Check("markdown_readable", not errors,
                        message="ok" if not errors else f"{errors[:3]}"))
    if errors:
        return checks

    combined = "\n\n".join(texts.values())
    title_ok = bool(re.search(r"^#\s+\S", combined, re.MULTILINE) or re.search(r"^title:\s*.+", combined, re.MULTILINE))
    summary_ok = "> **摘要**" in combined
    replacement_files = [p.relative_to(job_root).as_posix() for p, t in texts.items() if "\ufffd" in t]
    control_files = [p.relative_to(job_root).as_posix() for p, t in texts.items() if _bad_controls(t)]
    mojibake_files = [p.relative_to(job_root).as_posix() for p, t in texts.items() if MOJIBAKE_RE.search(t)]

    anchor_docs = [p for p in files if p.parent.name == "parts"] or files
    no_anchor = [p.relative_to(job_root).as_posix() for p in anchor_docs if "〔源" not in texts[p]]
    checks.append(Check("title_present", title_ok, message="title/front matter found" if title_ok else "missing title"))
    checks.append(Check("summary_present", summary_ok, level="warn",
                        message="summary present" if summary_ok else "missing > **摘要** block"))
    checks.append(Check("source_anchors_present", not no_anchor,
                        message="anchors present" if not no_anchor else f"missing anchors: {no_anchor[:5]}"))
    checks.append(Check("no_replacement_char", not replacement_files,
                        message="none" if not replacement_files else f"U+FFFD in {replacement_files[:5]}"))
    checks.append(Check("no_control_chars", not control_files,
                        message="none" if not control_files else f"control chars in {control_files[:5]}"))
    checks.append(Check("mojibake_risk_low", not mojibake_files, level="warn",
                        message="none" if not mojibake_files else f"risk in {mojibake_files[:5]}"))

    empty_alts, image_no_desc, table_no_anchor, formula_no_anchor = [], [], [], []
    for path, text in texts.items():
        rel = path.relative_to(job_root).as_posix()
        for m in IMAGE_RE.finditer(text):
            if not m.group(1).strip():
                empty_alts.append(rel)
            window = text[m.end():m.end() + 500]
            if ">" not in window or "[未解析:" in window:
                image_no_desc.append(rel)
        for offset in _table_separator_offsets(text):
            if not _table_section_has_anchor(text, offset):
                table_no_anchor.append(rel)
        for m in FORMULA_RE.finditer(text):
            window = text[m.start():m.end() + 240]
            if "〔源" not in window:
                formula_no_anchor.append(rel)

    checks.append(Check("image_alts_present", not empty_alts,
                        message="ok" if not empty_alts else f"empty alt: {empty_alts[:5]}"))
    checks.append(Check("image_descriptions_present", not image_no_desc, level="warn",
                        message="ok" if not image_no_desc else f"missing/未解析: {image_no_desc[:5]}"))
    checks.append(Check("tables_have_source_anchor", not table_no_anchor,
                        message="ok" if not table_no_anchor else f"missing: {table_no_anchor[:5]}"))
    checks.append(Check("formulas_have_source_anchor", not formula_no_anchor,
                        message="ok" if not formula_no_anchor else f"missing: {formula_no_anchor[:5]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate assembled Agent Markdown quality")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_agent_md_quality", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_agent_md_quality", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
