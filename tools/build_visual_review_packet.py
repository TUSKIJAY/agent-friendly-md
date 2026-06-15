#!/usr/bin/env python3
"""Phase 6: build visual review packet and promote QA outputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import portability  # noqa: E402
from lib import subproc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"


def _run_preview(job_root: Path) -> int:
    result = subproc.run_text(
        [sys.executable, str(WRAPPER), "tools/render_agent_md_preview.py", "--job", str(job_root)],
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _load_gate_results(job_root: Path) -> list[dict]:
    results = []
    for path in sorted((job_root / "logs" / "gates").glob("gate_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("phase") == "6_validation":
                continue  # Phase 6 gates are re-run after this packet is regenerated.
            results.append(data)
        except (OSError, json.JSONDecodeError):
            results.append({"phase": "unknown", "gate": path.name, "status": "fail", "notes": "unreadable gate result"})
    return results


def _issue_summary(job_root: Path) -> tuple[list[dict], list[str]]:
    path = job_root / P.REVIEW_ISSUES
    if not path.is_file():
        return [], ["review/issues.jsonl missing"]
    return ISS.read_issues(path)


def _overall(gates_data: list[dict], diagnostics: dict, issues: list[dict], parse_errors: list[str]) -> str:
    if parse_errors or diagnostics.get("status") == "fail":
        return "fail"
    if any(g.get("status") == "fail" for g in gates_data):
        return "fail"
    if any(i.get("severity") == "blocker" and i.get("status") == "open" for i in issues):
        return "fail"
    if diagnostics.get("status") == "pass_with_notes":
        return "pass_with_notes"
    if any(g.get("status") == "pass_with_notes" for g in gates_data):
        return "pass_with_notes"
    if any(i.get("severity") == "major" and i.get("status") == "open" for i in issues):
        return "pass_with_notes"
    return "pass"


def _write_visual(job_root: Path, diagnostics: dict, state: dict, overall: str) -> None:
    warnings = diagnostics.get("warnings") or []
    comparisons = diagnostics.get("source_comparisons") or {}
    evidence_manifest = P.REVIEW_EVIDENCE_MANIFEST if (job_root / P.REVIEW_EVIDENCE_MANIFEST).is_file() else ""
    lines = [
        "# Visual Acceptance Report",
        "",
        f"status: {diagnostics.get('status', overall)}",
        f"reviewed_at: {js.now_iso()}",
        "reviewer: validation_gate.py",
        f"risk_level: {state.get('document_profile', {}).get('risk_level', '')}",
        "",
        "## Reviewed Artifacts",
        "",
        "- review/visual_acceptance/rendered.html",
        "- review/visual_acceptance/anchor_map.json",
        "- review/visual_acceptance/render_diagnostics.json",
        f"- {comparisons.get('dir', 'review/visual_acceptance/source_comparisons')}/",
        *([f"- {evidence_manifest}"] if evidence_manifest else []),
        "",
        "## Diagnostics",
        "",
        f"- renderer: {diagnostics.get('renderer', '')}",
        f"- screenshots: {len(diagnostics.get('screenshots') or [])}",
        f"- source_comparisons: {len(comparisons.get('artifacts') or [])}",
        *[f"- warning: {w}" for w in warnings],
        "",
        "## Decision",
        "",
        overall,
    ]
    (job_root / P.OUTPUT_VISUAL_ACCEPTANCE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evidence_level_rows(job_root: Path) -> list[str]:
    try:
        blocks = IR.read_blocks(job_root)
    except (OSError, json.JSONDecodeError):
        return ["| unavailable | 0 | 0 |", "| --- | ---: | ---: |"]
    counts: dict[str, dict[str, int]] = {}
    for block in blocks:
        level = str(block.get("evidence_level") or "missing")
        row = counts.setdefault(level, {"blocks": 0, "needs_review": 0})
        row["blocks"] += 1
        if block.get("needs_review"):
            row["needs_review"] += 1
    rows = ["| Evidence level | Blocks | Needs review |", "| --- | ---: | ---: |"]
    for level in sorted(counts):
        row = counts[level]
        rows.append(f"| {level} | {row['blocks']} | {row['needs_review']} |")
    return rows


def _write_qa(job_root: Path, gates_data: list[dict], issues: list[dict], overall: str) -> None:
    replacements = portability.default_replacements(job_root, PROJECT_ROOT)
    rows = ["| Phase | Gate | Status | Notes |", "| --- | --- | --- | --- |"]
    for g in gates_data:
        notes = portability.sanitize_text(str(g.get("notes", "")), replacements)
        rows.append(f"| {g.get('phase', '')} | {g.get('gate', '')} | {g.get('status', '')} | {notes} |")
    blocker_open = sum(1 for i in issues if i.get("severity") == "blocker" and i.get("status") == "open")
    major_open = sum(1 for i in issues if i.get("severity") == "major" and i.get("status") == "open")
    lines = [
        "# QA Report",
        "",
        f"generated_at: {js.now_iso()}",
        f"overall: {overall}",
        "",
        "## Gate Results",
        "",
        *rows,
        "",
        "## Open Issues",
        "",
        f"- blocker(open): {blocker_open}",
        f"- major(open): {major_open}",
        "- see output/unresolved.md",
        "",
        "## Evidence Levels",
        "",
        *_evidence_level_rows(job_root),
        "",
        "## Visual Acceptance",
        "",
        "- see output/visual_acceptance.md",
    ]
    (job_root / P.OUTPUT_QA_REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hashed_output_files(job_root: Path) -> list[Path]:
    fixed = [
        job_root / P.OUTPUT_MAIN,
        job_root / "output/index.md",
        job_root / "output/index.json",
        job_root / "output/provenance.json",
        job_root / P.OUTPUT_QA_REPORT,
        job_root / P.OUTPUT_VISUAL_ACCEPTANCE,
        job_root / P.OUTPUT_UNRESOLVED,
    ]
    files = [p for p in fixed if p.is_file()]
    for directory in (job_root / P.OUTPUT_PARTS, job_root / P.OUTPUT_ASSETS):
        if directory.is_dir():
            files.extend(p for p in directory.rglob("*") if p.is_file())
    return sorted(files, key=lambda p: p.relative_to(job_root).as_posix())


def _update_manifest(job_root: Path) -> None:
    path = job_root / "output" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stage"] = "final"
    data["generated_at"] = js.now_iso()
    outputs = data.setdefault("outputs", {})
    outputs.setdefault("main", "main.md")
    outputs.setdefault("index", {"markdown": "index.md", "json": "index.json"})
    outputs["qa_report"] = "qa_report.md"
    outputs["visual_acceptance"] = "visual_acceptance.md"
    outputs["unresolved"] = "unresolved.md"
    hashes = data.setdefault("output_hashes", {})
    hashes.clear()
    for file in _hashed_output_files(job_root):
        hashes[file.relative_to(job_root).as_posix()] = mf.sha256_file(file)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_packet(job_root: Path) -> dict:
    if _run_preview(job_root) != 0:
        raise RuntimeError("render_agent_md_preview failed")
    diagnostics_path = job_root / P.REVIEW_VISUAL / "render_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    state = js.load_state(job_root)
    issues, parse_errors = _issue_summary(job_root)
    unresolved = ISS.unresolved_entries(issues)
    (job_root / P.OUTPUT_UNRESOLVED).write_text(ISS.render_unresolved(unresolved), encoding="utf-8")
    gates_data = _load_gate_results(job_root)
    overall = _overall(gates_data, diagnostics, issues, parse_errors)
    _write_visual(job_root, diagnostics, state, overall)
    _write_qa(job_root, gates_data, issues, overall)
    _update_manifest(job_root)
    return {"overall": overall, "diagnostics": diagnostics}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build Phase 6 visual review packet")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        result = build_packet(job_root)
    except (OSError, json.JSONDecodeError, RuntimeError) as e:
        print(f"[error] visual packet failed: {e}", file=sys.stderr)
        return 1
    print(f"[ok] visual review packet built: {result['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
