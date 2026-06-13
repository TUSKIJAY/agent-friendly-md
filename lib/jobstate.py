"""STATE.json: the cross-session job state (PLAN §5/§6).

Defines the canonical phase enum (the only place it lives), the STATE shape,
and read/write/advance helpers. Validators check against ``PHASES`` /
``PHASE_STATUS_VALUES`` here rather than hard-coding strings.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_SCHEMA_VERSION = "agent-friendly-md-state/0.1"

# Canonical phase enum (PLAN §5/§6). List order == pipeline order; index is
# used to enforce "回退允许，跳过禁止" (rollback allowed, skipping forbidden).
PHASES: list[str] = [
    "0_intake",
    "1_extraction",
    "2_ir_build",
    "3_semantic_compile",
    "4_audit",
    "5_assembly",
    "6_validation",
    "7_package",
]
PHASE_STATUS_VALUES: list[str] = ["pending", "in_progress", "done", "failed"]
PROFILE_STATUS_VALUES: list[str] = ["provisional", "confirmed"]
RISK_LEVELS: list[str] = ["low", "medium", "high"]

# Split-output thresholds (PLAN §4). Defaults; overridable per-job via the
# init CLI, the effective values are persisted into STATE so a run is
# reproducible (review-003 minor 9).
DEFAULT_SPLIT_THRESHOLDS: dict[str, int] = {
    "max_pages": 100,
    "max_sheets": 3,
    "max_markdown_bytes": 300 * 1024,
    "max_blocks": 1500,
}

# Provisional risk heuristic at intake, from source extension only (no parsing
# libs at Phase 0). Extraction re-confirms and may raise it (PLAN §6).
_INTAKE_RISK_BY_EXT: dict[str, str] = {
    ".txt": "low",
    ".md": "low",
    ".docx": "medium",
    ".pdf": "medium",
    ".pptx": "medium",
    ".xlsx": "medium",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def primary_type_for(ext: str) -> str:
    return ext.lower().lstrip(".") or "unknown"


def intake_risk_for(ext: str) -> str:
    return _INTAKE_RISK_BY_EXT.get(ext.lower(), "medium")


def state_file(job_root: str | Path) -> Path:
    return Path(job_root) / "STATE.json"


def load_state(job_root: str | Path) -> dict:
    return json.loads(state_file(job_root).read_text(encoding="utf-8"))


def save_state(job_root: str | Path, state: dict) -> None:
    state["updated_at"] = now_iso()
    state_file(job_root).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def new_state(
    *,
    job_id: str,
    source_files: list[str],
    job_root: str,
    primary_ext: str,
    output_dir: str = "output",
    split_thresholds: dict[str, int] | None = None,
) -> dict:
    """Build a fresh STATE for Phase 0 with a provisional profile."""
    ts = now_iso()
    risk = intake_risk_for(primary_ext)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "job_id": job_id,
        "created_at": ts,
        "updated_at": ts,
        "source_files": list(source_files),
        "current_phase": PHASES[0],
        "phase_status": {
            ph: ("in_progress" if ph == PHASES[0] else "pending") for ph in PHASES
        },
        "document_profile": {
            "profile_status": "provisional",
            "confirmed_by": "",
            "primary_type": primary_type_for(primary_ext),
            "pages": None,
            "has_images": None,
            "has_tables": None,
            "has_formulas": None,
            "has_comments": None,
            "has_attachments": None,
            "is_scanned": None,
            "risk_level": risk,
            "risk_level_history": [
                {
                    "phase": "0_intake",
                    "risk_level": risk,
                    "basis": "source extension",
                }
            ],
        },
        "config": {
            "split_thresholds": dict(split_thresholds or DEFAULT_SPLIT_THRESHOLDS),
        },
        # Store the bundle's own dir name, not an absolute path: STATE.json lives
        # inside job_root, so an absolute path here is redundant and would leak the
        # author's filesystem layout into the (optionally shipped) bundle. Nothing
        # reads paths.job_root back; tools resolve the bundle from the --job arg.
        "paths": {"job_root": Path(job_root).name, "output_dir": output_dir},
    }


def set_phase_status(job_root: str | Path, phase: str, status: str) -> dict:
    """Set one phase's status and persist. Used by gates to mark ``failed``."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase: {phase}")
    if status not in PHASE_STATUS_VALUES:
        raise ValueError(f"unknown phase_status: {status}")
    state = load_state(job_root)
    state["phase_status"][phase] = status
    save_state(job_root, state)
    return state
