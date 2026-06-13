#!/usr/bin/env python3
"""Gate: validate block-level provenance (PLAN §9.2 / §12).

    python3 scripts/run_python.py validators/validate_provenance.py --job "<job-dir>"

Checks that every block has a well-formed source_anchor for its kind, that the
high-value blocks (table/figure/formula) are traceable, and that anchor
source_file values point at a declared source. Runs in Phase 2 and Phase 4, so
the gate phase is the current phase.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import gates  # noqa: E402
from lib.gates import Check  # noqa: E402

_ANCHOR_KEYS = IR.ANCHOR_REQUIRED_KEYS  # shared vocabulary (lib/ir.py)


def build_checks(job_root: Path, state: dict) -> list[Check]:
    c: list[Check] = []
    blocks_file = job_root / IR.IR_BLOCKS
    c.append(Check("blocks_present", blocks_file.is_file(), message=str(blocks_file)))
    if not blocks_file.is_file():
        return c
    try:
        blocks = IR.read_blocks(job_root)
    except (OSError, json.JSONDecodeError) as e:
        c.append(Check("blocks_parseable", False, message=f"blocks.jsonl unreadable: {e}"))
        return c
    sources = set(state.get("source_files") or [])

    no_anchor = [b["id"] for b in blocks if not b.get("source_anchor")]
    c.append(Check("every_block_has_anchor", not no_anchor,
                   message="all anchored" if not no_anchor else f"no anchor: {no_anchor[:5]}"))

    bad_kind, bad_keys, bad_src = [], [], []
    null_page = []
    for b in blocks:
        a = b.get("source_anchor") or {}
        kind = a.get("kind")
        if kind not in _ANCHOR_KEYS:
            bad_kind.append(b["id"])
            continue
        if any(k not in a for k in _ANCHOR_KEYS[kind]):
            bad_keys.append(b["id"])
        if a.get("source_file") and sources and a["source_file"] not in sources:
            bad_src.append(b["id"])
        if kind == "pdf_page" and a.get("page") is None:
            null_page.append(b["id"])
    c.append(Check("anchor_kind_known", not bad_kind,
                   message="ok" if not bad_kind else f"unknown anchor kind: {bad_kind[:5]}"))
    c.append(Check("anchor_keys_complete", not bad_keys,
                   message="ok" if not bad_keys else f"missing keys: {bad_keys[:5]}"))
    c.append(Check("anchor_source_declared", not bad_src, level="warn",
                   message="ok" if not bad_src else f"source not in STATE: {bad_src[:5]}"))
    c.append(Check("pdf_page_known", not null_page, level="warn",
                   message="ok" if not null_page else f"null page (content before first page marker): {null_page[:5]}"))

    # high-value blocks specifically traceable
    hv = [b["id"] for b in blocks if b["type"] in ("table", "figure", "formula") and not b.get("source_anchor")]
    c.append(Check("high_value_traceable", not hv,
                   message="tables/figures/formulas anchored" if not hv else f"untraceable: {hv[:5]}"))
    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate block-level provenance")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_provenance", phase="2_ir_build",
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    state = js.load_state(job_root)
    phase = state.get("current_phase") if state.get("current_phase") in js.PHASES else "2_ir_build"
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_provenance", phase=phase,
        checks=build_checks(job_root, state),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
