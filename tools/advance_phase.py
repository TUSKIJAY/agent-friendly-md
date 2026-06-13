#!/usr/bin/env python3
"""Advance a job to the next phase — only if the current phase's gates passed.

    python3 scripts/run_python.py tools/advance_phase.py --job "<job-dir>"

Enforces "gate 通过后才允许推进" (WORKFLOW.md §2): requires at least one gate
result for the current phase (filename AND internal phase matching) and none with
status ``fail``. Sets the current phase ``done``, the next ``in_progress``, and
moves ``current_phase`` forward. This is the minimal pre-v0.7 orchestrator;
run_validators.py will subsume it.

Known gap (pre-v0.7): after a manual rollback, stale passing gate files for the
re-opened phase are not detected (hash-staleness is a v0.7 concern, WORKFLOW §5).
A rollback should delete logs/gates/gate_<phase>_*.json for every reset phase.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402


def gate_statuses(job_root: Path, phase: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    gdir = job_root / "logs" / "gates"
    if not gdir.is_dir():
        return out
    for f in sorted(gdir.glob(f"gate_{phase}_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append((f.name, "unreadable"))
            continue
        # defense-in-depth: ignore a file whose internal phase disagrees with the
        # filename phase, so a mis-filed gate can never count toward advancement.
        if data.get("phase") != phase:
            continue
        out.append((f.name, data.get("status", "unknown")))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Advance to the next phase if gates passed.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--force", action="store_true", help="advance even without a passing gate (discouraged)")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    state = js.load_state(job_root)
    cur = state["current_phase"]
    idx = js.PHASES.index(cur)
    if idx >= len(js.PHASES) - 1:
        print(f"[ok] already at final phase: {cur} — nothing to advance.")
        return 0

    statuses = gate_statuses(job_root, cur)
    failed = [n for n, s in statuses if s == "fail"]
    if not args.force:
        if not statuses:
            print(f"[error] no gate results for phase {cur}; run its gates first.", file=sys.stderr)
            return 1
        if failed:
            print(f"[error] phase {cur} has failed gates: {failed}", file=sys.stderr)
            return 1

    nxt = js.PHASES[idx + 1]
    state["phase_status"][cur] = "done"
    state["phase_status"][nxt] = "in_progress"
    state["current_phase"] = nxt
    js.save_state(job_root, state)
    print(f"[ok] advanced: {cur} (done) -> {nxt} (in_progress)")
    for n, s in statuses:
        print(f"     gate {n}: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
