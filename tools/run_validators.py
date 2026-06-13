#!/usr/bin/env python3
"""Run all gates for a phase, record hash snapshots, then advance."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import hashes  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import subproc  # noqa: E402
from lib.gates import Check  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

PHASE_GATES: dict[str, list[tuple[str, list[str]]]] = {
    "0_intake": [
        ("validators/validate_state.py", []),
        ("validators/validate_manifest.py", ["--mode", "draft"]),
    ],
    "1_extraction": [
        ("validators/validate_extraction.py", []),
    ],
    "2_ir_build": [
        ("validators/validate_ir.py", []),
        ("validators/validate_provenance.py", []),
        ("validators/validate_links.py", ["--mode", "ir"]),
    ],
    "3_semantic_compile": [
        ("validators/validate_ir.py", []),
        ("validators/validate_links.py", ["--mode", "ir"]),
    ],
    "4_audit": [
        ("validators/validate_audit_summary.py", []),
        ("validators/validate_tables.py", []),
        ("validators/validate_provenance.py", []),
        ("validators/validate_unresolved.py", []),
    ],
    "5_assembly": [
        ("validators/validate_agent_md_quality.py", []),
        ("validators/validate_placeholders.py", []),
        ("validators/validate_links.py", ["--mode", "markdown"]),
    ],
    "6_validation": [
        ("validators/validation_gate.py", []),
        ("validators/validate_manifest.py", ["--mode", "final"]),
    ],
    "7_package": [
        ("validators/package_gate.py", []),
    ],
}


def _run_target(target: str, job_root: Path, extra: list[str]) -> int:
    target_path = PROJECT_ROOT / target
    if not target_path.is_file():
        print(f"[error] configured gate target missing: {target}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(WRAPPER), target, "--job", str(job_root), *extra]
    result = subproc.run_text(cmd, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode not in (0, 1, 2):
        print(f"[error] gate exited with unexpected code {result.returncode}: {target}", file=sys.stderr)
        return 1
    return result.returncode


def _advance(job_root: Path) -> int:
    result = subproc.run_text(
        [sys.executable, str(WRAPPER), "tools/advance_phase.py", "--job", str(job_root)],
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _write_stale_gate(job_root: Path, phase: str, diff: dict) -> int:
    msg = (
        f"input digest changed {diff.get('previous_digest')} -> {diff.get('current_digest')}; "
        f"changed={diff.get('changed', [])[:5]} added={diff.get('added', [])[:5]} "
        f"removed={diff.get('removed', [])[:5]}"
    )
    return gates.write_gate_result(
        job_root=job_root,
        gate_name="hash_stale",
        phase=phase,
        checks=[Check("phase_inputs_fresh", False, message=msg)],
        extra={"stale_diff": diff},
    )


def _write_state_gate(job_root: Path, message: str) -> int:
    return gates.write_gate_result(
        job_root=job_root,
        gate_name="run_validators_state",
        phase="0_intake",
        checks=[Check("state_loadable", False, message=message)],
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run all validators for a phase and advance.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--phase", choices=js.PHASES, default=None,
                    help="phase to validate (default: STATE.current_phase)")
    ap.add_argument("--no-advance", action="store_true",
                    help="run gates and record hashes without advancing")
    ap.add_argument("--refresh-stale", action="store_true",
                    help="run gates and refresh hash snapshot despite stale inputs")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return _write_state_gate(job_root, f"STATE.json missing in {job_root}")
    try:
        state = js.load_state(job_root)
    except (OSError, json.JSONDecodeError) as e:
        return _write_state_gate(job_root, f"STATE.json unreadable: {e}")
    phase = args.phase or state.get("current_phase")
    if phase not in js.PHASES:
        print(f"[error] bad phase: {phase}", file=sys.stderr)
        return 2
    if phase not in PHASE_GATES:
        print(f"[error] no configured gates yet for phase {phase}", file=sys.stderr)
        return 1

    try:
        diff = hashes.stale_diff(job_root, phase)
    except (OSError, json.JSONDecodeError) as e:
        diff = {"error": f"hash snapshot unreadable: {e}", "changed": [], "added": [], "removed": []}
    if diff is not None:
        if not args.refresh_stale:
            return _write_stale_gate(job_root, phase, diff)
        gates.write_gate_result(
            job_root=job_root,
            gate_name="hash_stale",
            phase=phase,
            checks=[Check("phase_inputs_fresh", False, level="warn",
                          message=f"refreshing stale snapshot: {diff}")],
            extra={"stale_diff": diff},
        )

    exits = [_run_target(target, job_root, extra) for target, extra in PHASE_GATES[phase]]
    if any(code == 1 for code in exits):
        print(f"[fail] phase {phase} has failed gates; not advancing.", file=sys.stderr)
        return 1
    if any(code not in (0, 2) for code in exits):
        print(f"[fail] phase {phase} had unexpected gate exits; not advancing.", file=sys.stderr)
        return 1

    try:
        snap = hashes.record_snapshot(job_root, phase)
    except (OSError, ValueError, TypeError) as e:
        return gates.write_gate_result(
            job_root=job_root,
            gate_name="hash_snapshot",
            phase=phase,
            checks=[Check("hash_snapshot_written", False, message=str(e))],
        )
    print(f"[ok] hash snapshot: logs/hashes/{phase}.json ({snap['input_digest'][:12]})")

    has_notes = any(code == 2 for code in exits)
    if args.no_advance:
        return 2 if has_notes else 0
    if state.get("current_phase") != phase:
        print(f"[error] refusing to advance: STATE.current_phase is {state.get('current_phase')}, validated {phase}",
              file=sys.stderr)
        return 1
    adv = _advance(job_root)
    if adv != 0:
        return adv
    return 2 if has_notes else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
