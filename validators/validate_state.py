#!/usr/bin/env python3
"""Gate: validate STATE.json (PLAN §5/§6/§12).

    python3 scripts/run_python.py validators/validate_state.py --job "<job-dir>"

Checks the phase enum, status progression ("回退允许，跳过禁止"), the document
profile two-stage rule, and that the declared paths exist. Writes
logs/gates/gate_<phase>_validate_state.json and exits 0/1/2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import gates  # noqa: E402
from lib.gates import Check  # noqa: E402

REQUIRED_KEYS = [
    "schema_version", "job_id", "source_files", "current_phase",
    "phase_status", "document_profile", "paths",
]


def build_checks(job_root: Path, state: dict) -> list[Check]:
    c: list[Check] = []

    c.append(Check("schema_version",
                   state.get("schema_version") == js.STATE_SCHEMA_VERSION,
                   message=f"expected {js.STATE_SCHEMA_VERSION}, got {state.get('schema_version')!r}"))

    missing = [k for k in REQUIRED_KEYS if k not in state]
    c.append(Check("required_keys", not missing,
                   message=f"missing keys: {missing}" if missing else "all present"))
    if missing:
        return c  # can't meaningfully continue

    cur = state["current_phase"]
    c.append(Check("current_phase_enum", cur in js.PHASES,
                   message=f"{cur!r} in phase enum" if cur in js.PHASES else f"{cur!r} not a valid phase"))

    ps = state["phase_status"]
    keys_ok = set(ps) == set(js.PHASES)
    c.append(Check("phase_status_keys", keys_ok,
                   message="keys match enum" if keys_ok else f"keys differ: {sorted(set(ps) ^ set(js.PHASES))}"))
    vals_ok = all(v in js.PHASE_STATUS_VALUES for v in ps.values())
    c.append(Check("phase_status_values", vals_ok,
                   message="all values valid" if vals_ok else
                           f"bad values: {[v for v in ps.values() if v not in js.PHASE_STATUS_VALUES]}"))

    # no-skip rule: phases before current must be done; after current must be pending
    if cur in js.PHASES and keys_ok and vals_ok:
        idx = js.PHASES.index(cur)
        before_bad = [p for i, p in enumerate(js.PHASES) if i < idx and ps[p] != "done"]
        after_bad = [p for i, p in enumerate(js.PHASES) if i > idx and ps[p] != "pending"]
        c.append(Check("no_skip_before", not before_bad,
                       message="earlier phases done" if not before_bad else f"earlier not done: {before_bad}"))
        c.append(Check("no_skip_after", not after_bad,
                       message="later phases pending" if not after_bad else f"later not pending: {after_bad}"))
        c.append(Check("current_status_active", ps[cur] in ("in_progress", "failed", "done"),
                       message=f"current status {ps[cur]!r}"))

    prof = state["document_profile"]
    c.append(Check("profile_status_enum", prof.get("profile_status") in js.PROFILE_STATUS_VALUES,
                   message=f"profile_status={prof.get('profile_status')!r}"))
    if prof.get("profile_status") == "confirmed":
        c.append(Check("confirmed_by_set", bool(prof.get("confirmed_by")),
                       message="confirmed_by present" if prof.get("confirmed_by") else "confirmed but confirmed_by empty"))
    c.append(Check("risk_level_enum", prof.get("risk_level") in js.RISK_LEVELS,
                   message=f"risk_level={prof.get('risk_level')!r}"))
    c.append(Check("risk_history_present", isinstance(prof.get("risk_level_history"), list)
                   and len(prof["risk_level_history"]) >= 1,
                   level="warn", message="risk_level_history present"))

    paths = state.get("paths", {})
    out_dir = job_root / paths.get("output_dir", "output")
    c.append(Check("job_root_exists", job_root.is_dir(), message=str(job_root)))
    c.append(Check("output_dir_exists", out_dir.is_dir(), message=str(out_dir)))

    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate STATE.json")
    ap.add_argument("--job", required=True, help="job bundle directory")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    state_file = job_root / "STATE.json"
    # A missing or unparseable STATE.json is a hard fail (the Phase 0 gate cannot
    # pass without its own required product), and must still emit a gate result.
    if not state_file.is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_state", phase=js.PHASES[0],
            checks=[Check("state_present", False, message=f"STATE.json not found in {job_root}")],
        )
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_state", phase=js.PHASES[0],
            checks=[Check("state_parseable", False, message=f"STATE.json is not valid JSON: {e}")],
        )

    phase = state.get("current_phase") if state.get("current_phase") in js.PHASES else js.PHASES[0]
    checks = build_checks(job_root, state)
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_state", phase=phase, checks=checks
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
