"""Gate output protocol (PLAN §12, with review-003 fixes folded in).

Every gate (validator) uses this so behaviour is uniform:

- exit code 0 = pass, 1 = fail, 2 = pass_with_notes
- a machine result is written to ``logs/gates/gate_<phase>_<name>.json``
  (phase is in the filename so the same validator run in two phases — e.g.
  validate_ir in Phase 2 and Phase 3 — does not overwrite, review-003 minor 3)
- a human one-liner is appended to ``review/gate_log.md`` (NOT output/qa_report.md;
  Phase 6 alone promotes into output/, review-003 medium 1)
- on fail, the phase's STATE status is set to ``failed``

A gate is a list of ``Check`` results. ``error``-level failures fail the gate;
``warn``-level failures downgrade to pass_with_notes; ``info`` never blocks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from . import jobstate

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_PASS_WITH_NOTES = 2
STATUS_BY_EXIT = {0: "pass", 1: "fail", 2: "pass_with_notes"}

LEVELS = ("error", "warn", "info")


@dataclass
class Check:
    id: str
    ok: bool
    level: str = "error"  # error | warn | info
    message: str = ""

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"bad check level: {self.level!r}")


def decide_exit(checks: list[Check]) -> int:
    failed = [c for c in checks if not c.ok]
    if any(c.level == "error" for c in failed):
        return EXIT_FAIL
    if any(c.level == "warn" for c in failed):
        return EXIT_PASS_WITH_NOTES
    return EXIT_PASS


def _gate_filename(phase: str, gate_name: str) -> str:
    return f"gate_{phase}_{gate_name}.json"


def write_gate_result(
    *,
    job_root: str | Path,
    gate_name: str,
    phase: str,
    checks: list[Check],
    notes: str = "",
    extra: dict | None = None,
) -> int:
    """Write the gate result, append a human line, mark phase failed on fail.

    Returns the exit code (caller does ``raise SystemExit(code)``).
    """
    root = Path(job_root)
    exit_code = decide_exit(checks)
    status = STATUS_BY_EXIT[exit_code]

    result = {
        "gate": gate_name,
        "phase": phase,
        "status": status,
        "exit_code": exit_code,
        "created_at": jobstate.now_iso(),
        "checks": [asdict(c) for c in checks],
        "notes": notes,
    }
    if extra:
        result["extra"] = extra

    gates_dir = root / "logs" / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    (gates_dir / _gate_filename(phase, gate_name)).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    failed = [c for c in checks if not c.ok]
    summary = (
        f"- [{status}] `{gate_name}` (phase {phase}) — "
        f"{len(checks) - len(failed)}/{len(checks)} checks ok"
    )
    if failed:
        summary += " — failed: " + ", ".join(
            f"{c.id}({c.level})" for c in failed
        )
    _append_gate_log(root, summary)

    if status == "fail":
        try:
            jobstate.set_phase_status(root, phase, "failed")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            # STATE may be absent or unreadable — that is itself the failure being
            # reported; the gate result is already written, so skip the status update.
            print("  (note: could not mark phase failed — STATE.json absent or unreadable)")

    _print_console(gate_name, phase, status, checks)
    return exit_code


def _append_gate_log(root: Path, line: str) -> None:
    log = root / "review" / "gate_log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    header = "" if log.exists() else "# Gate log\n\n"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(header + line + "\n")


def _print_console(gate_name: str, phase: str, status: str, checks: list[Check]) -> None:
    print(f"[{status.upper()}] {gate_name} (phase {phase})")
    for c in checks:
        mark = "ok" if c.ok else "FAIL"
        print(f"  {mark:>4} [{c.level}] {c.id}: {c.message}")
