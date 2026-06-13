#!/usr/bin/env python3
"""Phase 7 gate: validate final outputs before packaging."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import hashes  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import portability  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "7_package"
REQUIRED_OUTPUTS = [
    "output/main.md",
    "output/index.md",
    "output/index.json",
    "output/manifest.json",
    "output/provenance.json",
    P.OUTPUT_QA_REPORT,
    P.OUTPUT_VISUAL_ACCEPTANCE,
    P.OUTPUT_UNRESOLVED,
]
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _output_path(job_root: Path, rel: str) -> Path:
    if rel.startswith("output/"):
        return job_root / rel
    return job_root / "output" / rel


def _load_json(path: Path) -> tuple[dict | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def _manifest_output_paths(manifest: dict) -> set[str]:
    out: set[str] = set()
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    for key in ("main", "qa_report", "visual_acceptance", "unresolved"):
        value = outputs.get(key)
        if value:
            out.add(f"output/{value}" if not str(value).startswith("output/") else str(value))
    index = outputs.get("index")
    if isinstance(index, dict):
        for key in ("markdown", "json"):
            value = index.get(key)
            if value:
                out.add(f"output/{value}" if not str(value).startswith("output/") else str(value))
    for key in ("parts", "assets"):
        values = outputs.get(key) or []
        for item in values if isinstance(values, list) else []:
            rel = item.get("path") if isinstance(item, dict) else item
            if rel:
                out.add(f"output/{rel}" if not str(rel).startswith("output/") else str(rel))
    return out


def _delivered_hash_paths(job_root: Path, manifest: dict) -> list[str]:
    rels = set(REQUIRED_OUTPUTS) - {"output/manifest.json"}
    rels.update(_manifest_output_paths(manifest))
    for directory in (job_root / P.OUTPUT_PARTS, job_root / P.OUTPUT_ASSETS):
        if directory.is_dir():
            rels.update(p.relative_to(job_root).as_posix() for p in directory.rglob("*") if p.is_file())
    return sorted(rels)


def _markdown_files(job_root: Path) -> list[Path]:
    files = [job_root / P.OUTPUT_MAIN] if (job_root / P.OUTPUT_MAIN).is_file() else []
    index = job_root / "output/index.md"
    if index.is_file():
        files.append(index)
    parts = job_root / P.OUTPUT_PARTS
    if parts.is_dir():
        files.extend(sorted(parts.glob("*.md")))
    return files


def _markdown_link_errors(job_root: Path) -> list[str]:
    errors: list[str] = []
    output_root = (job_root / "output").resolve()
    for md in _markdown_files(job_root):
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in IMAGE_RE.findall(text):
            if re.match(r"^[a-z]+://", target) or target.startswith("#"):
                continue
            local = target.split("#", 1)[0]
            path = (md.parent / local).resolve()
            try:
                path.relative_to(output_root)
            except ValueError:
                errors.append(f"{md.name}->{local} outside output/")
                continue
            if not path.is_file():
                errors.append(f"{md.name}->{local}")
    return errors


def _snapshot_inputs_changed(job_root: Path, snap: dict) -> list[str]:
    changed: list[str] = []
    for rel, meta in (snap.get("inputs") or {}).items():
        path = job_root / rel
        if not path.is_file():
            changed.append(f"missing:{rel}")
            continue
        if path.stat().st_size != meta.get("bytes") or mf.sha256_file(path) != meta.get("sha256"):
            changed.append(f"changed:{rel}")
    return changed


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    for rel in REQUIRED_OUTPUTS:
        checks.append(Check(f"{rel}_present", (job_root / rel).is_file(), message=rel))
    if not all((job_root / rel).is_file() for rel in REQUIRED_OUTPUTS):
        return checks

    manifest, man_err = _load_json(job_root / "output/manifest.json")
    checks.append(Check("manifest_parseable", manifest is not None, message=man_err or "ok"))
    if manifest is None:
        return checks
    checks.append(Check("manifest_final", manifest.get("stage") == "final",
                        message=f"stage={manifest.get('stage')!r}"))
    output_hashes = manifest.get("output_hashes") or {}
    expected_hash_paths = _delivered_hash_paths(job_root, manifest)
    missing_hashes = [rel for rel in expected_hash_paths if rel not in output_hashes]
    missing_files = [rel for rel in expected_hash_paths if not (job_root / rel).is_file()]
    bad_hashes = [
        rel for rel in expected_hash_paths
        if rel in output_hashes and (job_root / rel).is_file() and mf.sha256_file(job_root / rel) != output_hashes[rel]
    ]
    extra_hashes = [rel for rel in output_hashes if rel != "output/manifest.json" and not (job_root / rel).is_file()]
    checks.append(Check("manifest_output_hashes_complete", not missing_hashes,
                        message="ok" if not missing_hashes else f"missing hashes: {missing_hashes[:5]}"))
    checks.append(Check("manifest_output_files_present", not missing_files,
                        message="ok" if not missing_files else f"missing files: {missing_files[:5]}"))
    checks.append(Check("manifest_output_hashes_current", not bad_hashes and not extra_hashes,
                        message="ok" if not bad_hashes and not extra_hashes
                        else f"changed={bad_hashes[:5]} missing={extra_hashes[:5]}"))
    broken_links = _markdown_link_errors(job_root)
    checks.append(Check("markdown_image_links_packageable", not broken_links,
                        message="ok" if not broken_links else f"broken: {broken_links[:5]}"))
    leak_paths = sorted(set(expected_hash_paths) | {"output/manifest.json"})
    leaks = portability.scan_path_leaks(job_root, leak_paths)
    checks.append(Check("no_local_path_leaks", not leaks,
                        message="ok" if not leaks else f"{leaks[:5]}"))

    issues_path = job_root / P.REVIEW_ISSUES
    checks.append(Check("issues_present", issues_path.is_file(), message=P.REVIEW_ISSUES))
    issues, parse_errors = ISS.read_issues(issues_path) if issues_path.is_file() else ([], ["review/issues.jsonl missing"])
    checks.append(Check("issues_parseable", not parse_errors,
                        message="ok" if not parse_errors else f"{parse_errors[:3]}"))
    open_blockers = [i.get("id", "<missing-id>") for i in issues
                     if i.get("severity") == "blocker" and i.get("status") == "open"]
    bad_accepted = [i.get("id", "<missing-id>") for i in issues
                    if i.get("severity") == "blocker" and i.get("status") == "accepted"
                    and not (i.get("accepted_by") and i.get("accepted_reason"))]
    checks.append(Check("no_open_blockers", not open_blockers,
                        message="none" if not open_blockers else f"{open_blockers[:5]}"))
    checks.append(Check("accepted_blockers_documented", not bad_accepted,
                        message="ok" if not bad_accepted else f"{bad_accepted[:5]}"))
    projected = ISS.render_unresolved(ISS.unresolved_entries(issues)) if not parse_errors else ""
    try:
        unresolved_text = (job_root / P.OUTPUT_UNRESOLVED).read_text(encoding="utf-8")
    except OSError as e:
        unresolved_text = ""
        checks.append(Check("output_unresolved_readable", False, message=str(e)))
    checks.append(Check("output_unresolved_matches_issues", not parse_errors and unresolved_text == projected,
                        message="matches issues projection" if not parse_errors and unresolved_text == projected
                        else "output/unresolved.md is stale"))

    input_hashes = manifest.get("input_hashes") or {}
    snap = hashes.load_snapshot(job_root, "6_validation")
    checks.append(Check("phase6_snapshot_present", snap is not None,
                        message="logs/hashes/6_validation.json"))
    if snap is not None:
        checks.append(Check("phase6_manifest_hash_matches_snapshot",
                            input_hashes.get("6_validation") == snap.get("input_digest"),
                            message=f"manifest={input_hashes.get('6_validation')} snapshot={snap.get('input_digest')}"))
        changed_inputs = _snapshot_inputs_changed(job_root, snap)
        checks.append(Check("phase6_snapshot_inputs_current", not changed_inputs,
                            message="ok" if not changed_inputs else f"{changed_inputs[:5]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate package readiness.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="package_gate", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="package_gate", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
