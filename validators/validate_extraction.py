#!/usr/bin/env python3
"""Gate: validate Phase 1 extraction AND confirm the document profile.

    python3 scripts/run_python.py validators/validate_extraction.py --job "<job-dir>"

Checks extracted/ products, then re-confirms document_profile and the risk_level
(PLAN §6 / review-003 minor 8): sets profile_status=confirmed, confirmed_by, and
upgrades risk_level if the extracted content warrants it (never auto-downgrades).
Writes logs/gates/gate_<phase>_validate_extraction.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import gates  # noqa: E402
from lib import paths as P  # noqa: E402
from lib.gates import Check  # noqa: E402

# This is the single owning phase of this gate; pin it so the result file is
# always gate_1_extraction_validate_extraction.json and can never be mis-filed
# under (or help advance) another phase.
OWNING_PHASE = "1_extraction"

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_TABLE_SEP = re.compile(r"\|\s*:?-{3,}")
_FORMULA = re.compile(r"(?<!\\)\$\$?[^$\n]+\$\$?")  # $x$ or $$x$$ with content (not bare $$)
_PAGE_MARK = re.compile(r"meta:page_start")


def _max_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER.get(a, 0) >= _RISK_ORDER.get(b, 0) else b


def _detect(meta: dict, skeleton_text: str) -> dict:
    stats = meta.get("structured_stats") or {}
    n_images = int(meta.get("image_count") or 0) + int(meta.get("mapped_image_count") or 0)
    n_pages_rendered = int(meta.get("mapped_page_count") or 0)
    has_tables = bool(_TABLE_SEP.search(skeleton_text))
    has_formulas = int(stats.get("formula") or 0) > 0 or bool(_FORMULA.search(skeleton_text))
    n_charts = int(stats.get("chart") or 0)
    n_smart = int(stats.get("smartart") or 0)
    is_scanned = n_pages_rendered > 0
    # The backend does not emit page_count; derive it from per-page provenance
    # markers in the skeleton (PDF), else from rendered pages.
    pages = meta.get("page_count")
    if pages is None:
        n_markers = len(_PAGE_MARK.findall(skeleton_text))
        if n_markers > 0:
            pages = n_markers
        elif n_pages_rendered > 0:
            pages = n_pages_rendered
    return {
        "has_images": n_images > 0,
        "has_tables": has_tables,
        "has_formulas": has_formulas,
        "n_charts": n_charts,
        "n_smartart": n_smart,
        "is_scanned": is_scanned,
        "pages": pages,
        "n_pages_rendered": n_pages_rendered,
    }


def _computed_risk(d: dict) -> str:
    if d["has_formulas"] or d["has_tables"] or d["is_scanned"] or d["n_charts"] or d["n_smartart"]:
        return "high"
    if d["has_images"] or (d["pages"] or 0) > 1:
        return "medium"
    return "low"


def build_checks(job_root: Path, state: dict) -> tuple[list[Check], dict | None, str]:
    c: list[Check] = []
    meta_file = job_root / P.EXTRACT_META
    c.append(Check("extract_meta_present", meta_file.is_file(), message=str(meta_file)))
    if not meta_file.is_file():
        return c, None, ""
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        c.append(Check("extract_meta_parseable", False, message=f"invalid JSON: {e}"))
        return c, None, ""
    for key in ("source_format", "image_count", "structured_stats"):
        c.append(Check(f"meta.{key}", key in meta, message="present" if key in meta else "missing"))

    text_dir = job_root / P.EXTRACTED_TEXT
    skeletons = sorted(text_dir.glob("*_skeleton.md")) if text_dir.is_dir() else []
    c.append(Check("skeleton_present", bool(skeletons),
                   message=str(skeletons[0]) if skeletons else "no *_skeleton.md in extracted/text/"))
    skeleton_text = skeletons[0].read_text(encoding="utf-8", errors="replace") if skeletons else ""

    # image count consistency (warn, not fail) — count files only, mirroring _map_images
    img_dir = job_root / P.EXTRACTED_IMAGES
    n_on_disk = sum(1 for p in img_dir.iterdir() if p.is_file()) if img_dir.is_dir() else 0
    expected = int(meta.get("mapped_image_count") or 0)
    c.append(Check("image_count_consistent", n_on_disk == expected, level="warn",
                   message=f"on disk={n_on_disk} mapped={expected}"))
    return c, meta, skeleton_text


def confirm_profile(job_root: Path, state: dict, meta: dict, skeleton_text: str) -> None:
    d = _detect(meta, skeleton_text)
    prof = state["document_profile"]
    prof["has_images"] = d["has_images"]
    prof["has_tables"] = d["has_tables"]
    prof["has_formulas"] = d["has_formulas"]
    prof["is_scanned"] = d["is_scanned"]
    if d["pages"] is not None:
        prof["pages"] = d["pages"]

    old_risk = prof.get("risk_level", "medium")
    new_risk = _max_risk(old_risk, _computed_risk(d))
    if new_risk != old_risk:
        prof.setdefault("risk_level_history", []).append({
            "phase": "1_extraction",
            "risk_level": new_risk,
            "basis": "extracted content (tables/formulas/images/scan)",
        })
    prof["risk_level"] = new_risk
    prof["profile_status"] = "confirmed"
    prof["confirmed_by"] = "validate_extraction.py"
    js.save_state(job_root, state)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate Phase 1 extraction + confirm profile")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_extraction", phase="1_extraction",
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    state = js.load_state(job_root)
    phase = OWNING_PHASE  # pinned — never file under current_phase (see OWNING_PHASE note)

    checks, meta, skeleton_text = build_checks(job_root, state)
    if gates.decide_exit(checks) != gates.EXIT_FAIL and meta is not None:
        confirm_profile(job_root, state, meta, skeleton_text)
        checks.append(Check("profile_confirmed", True, level="info",
                            message=f"risk={state['document_profile']['risk_level']}, "
                                    f"status={state['document_profile']['profile_status']}"))

    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_extraction", phase=phase, checks=checks
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
