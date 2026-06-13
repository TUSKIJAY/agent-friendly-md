#!/usr/bin/env python3
"""Phase 6 gate: validate QA and visual acceptance outputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "6_validation"


def _load_json(path: Path) -> tuple[dict | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def _readable_rel_files(job_root: Path, rels: list[str]) -> list[str]:
    missing = []
    for rel in rels:
        path = job_root / rel
        try:
            with path.open("rb") as fh:
                fh.read(1)
        except OSError:
            missing.append(rel)
    return missing


def build_checks(job_root: Path, state: dict) -> list[Check]:
    checks: list[Check] = []
    required = {
        "qa_report": job_root / P.OUTPUT_QA_REPORT,
        "visual_acceptance": job_root / P.OUTPUT_VISUAL_ACCEPTANCE,
        "unresolved": job_root / P.OUTPUT_UNRESOLVED,
        "rendered_html": job_root / P.REVIEW_VISUAL / "rendered.html",
        "anchor_map": job_root / P.REVIEW_VISUAL / "anchor_map.json",
        "render_diagnostics": job_root / P.REVIEW_VISUAL / "render_diagnostics.json",
    }
    for name, path in required.items():
        checks.append(Check(f"{name}_present", path.is_file(), message=str(path)))
    if not all(path.is_file() for path in required.values()):
        return checks

    diagnostics, diag_err = _load_json(required["render_diagnostics"])
    checks.append(Check("diagnostics_parseable", diagnostics is not None,
                        message="ok" if diagnostics is not None else diag_err))
    anchor_map, anchor_err = _load_json(required["anchor_map"])
    checks.append(Check("anchor_map_parseable", anchor_map is not None,
                        message="ok" if anchor_map is not None else anchor_err))
    if diagnostics is None or anchor_map is None:
        return checks

    visual_status = diagnostics.get("status")
    risk = (state.get("document_profile") or {}).get("risk_level")
    # Defense-in-depth: a missing/corrupt profile at Phase 6 would make risk None,
    # silently disabling every high-risk source-comparison check. Fail loudly
    # instead (Phase 0 already enforces the enum, so this should never fire).
    checks.append(Check("risk_level_valid", risk in js.RISK_LEVELS, level="error",
                        message=f"risk={risk!r}"))
    checks.append(Check("visual_status_not_fail", visual_status != "fail",
                        message=f"status={visual_status!r}"))
    checks.append(Check("high_risk_visual_status_pass", risk != "high" or visual_status == "pass",
                        message=f"risk={risk} status={visual_status!r}"))
    warnings = diagnostics.get("warnings") or []
    checks.append(Check("visual_warnings", not warnings, level="warn",
                        message="none" if not warnings else f"{warnings[:5]}"))
    screenshots = diagnostics.get("screenshots") or []
    contact_sheet = diagnostics.get("contact_sheet") or ""
    visual_complete = bool(screenshots and contact_sheet)

    # B3 / PLAN §14.1: a fallback <pre> render (no real renderer) or absent
    # screenshots must NEVER count as visual acceptance. Only "low" risk is
    # validator-only — for it, an absent renderer is reported "not required"
    # (n/a), not a pass. Every other level (medium, high, or unconfirmed risk)
    # requires a real renderer + screenshots, at error level, so a degraded
    # Phase 6 hard-fails instead of silently advancing to packaging.
    renderer_ok = bool(diagnostics.get("renderer_ok"))
    visual_required = risk != "low"
    visual_produced = renderer_ok and bool(screenshots)
    checks.append(Check(
        "visual_acceptance_rendered",
        (not visual_required) or visual_produced,
        level="error",
        message=(f"not required (risk={risk})" if not visual_required
                 else f"renderer_ok={renderer_ok} screenshots={len(screenshots)}"),
    ))
    artifact_level = "error" if risk == "high" or visual_status == "pass" else "warn"
    checks.append(Check("visual_artifacts_listed", bool(visual_complete), level=artifact_level,
                        message=f"screenshots={len(screenshots)} contact_sheet={bool(contact_sheet)}"))
    artifact_paths = [*screenshots, contact_sheet] if contact_sheet else list(screenshots)
    missing_artifacts = [p for p in artifact_paths if not (job_root / p).is_file()]
    checks.append(Check("visual_artifacts_exist", not missing_artifacts,
                        message="ok" if not missing_artifacts else f"{missing_artifacts[:5]}"))
    comparisons = diagnostics.get("source_comparisons") or {}
    comparison_dir = job_root / P.REVIEW_SOURCE_COMPARISONS
    comparison_artifacts = comparisons.get("artifacts") or []
    page_samples = comparisons.get("sampled_pages") or []
    text_evidence = comparisons.get("sampled_source_evidence") or []
    missing_comparisons = _readable_rel_files(job_root, comparison_artifacts)
    high_risk = risk == "high"
    checks.append(Check("source_comparisons_dir_present", not high_risk or comparison_dir.is_dir(),
                        message=str(comparison_dir)))
    checks.append(Check("source_comparisons_listed", not high_risk or bool(comparison_artifacts),
                        message=f"{len(comparison_artifacts)} artifact(s)"))
    checks.append(Check("source_comparisons_readable", not high_risk or not missing_comparisons,
                        message="ok" if not missing_comparisons else f"{missing_comparisons[:5]}"))
    checks.append(Check("source_comparison_sample_recorded",
                        not high_risk or (bool(page_samples) or bool(text_evidence))
                        and bool(comparisons.get("sampled_anchors"))
                        and bool(comparisons.get("reason"))
                        and bool(comparisons.get("seed")),
                        message=(f"sampled_pages={len(page_samples)} "
                                 f"source_evidence={len(text_evidence)}")))
    checks.append(Check("anchors_nonempty", bool(anchor_map.get("anchors")),
                        message=f"{len(anchor_map.get('anchors') or [])} anchor(s)"))

    issues_path = job_root / P.REVIEW_ISSUES
    issues, parse_errors = ISS.read_issues(issues_path) if issues_path.is_file() else ([], ["review/issues.jsonl missing"])
    checks.append(Check("issues_parseable", not parse_errors,
                        message="ok" if not parse_errors else f"{parse_errors[:3]}"))
    blocker_open = [i.get("id", "<missing-id>") for i in issues
                    if i.get("severity") == "blocker" and i.get("status") == "open"]
    major_open = [i.get("id", "<missing-id>") for i in issues
                  if i.get("severity") == "major" and i.get("status") == "open"]
    checks.append(Check("no_open_blockers", not blocker_open,
                        message="none" if not blocker_open else f"{blocker_open[:5]}"))
    checks.append(Check("major_open_notes", not major_open, level="warn",
                        message="none" if not major_open else f"{major_open[:5]}"))
    checks.append(Check("high_risk_visual_report", risk != "high" or (required["visual_acceptance"].is_file()
                        and visual_status == "pass" and visual_complete and bool(comparison_artifacts)
                        and not missing_comparisons),
                        message=f"risk={risk}"))
    manifest, man_err = _load_json(job_root / "output" / "manifest.json")
    checks.append(Check("manifest_final", bool(manifest and manifest.get("stage") == "final"),
                        message="final" if manifest and manifest.get("stage") == "final" else man_err or "not final"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate Phase 6 visual acceptance outputs")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validation_gate", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    state = js.load_state(job_root)
    return gates.write_gate_result(
        job_root=job_root, gate_name="validation_gate", phase=PHASE,
        checks=build_checks(job_root, state),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
