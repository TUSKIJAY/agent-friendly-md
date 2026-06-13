#!/usr/bin/env python3
"""Gate: validate Document IR (PLAN §9.1 / docs/ir-schema.md — the 5 checks).

    python3 scripts/run_python.py validators/validate_ir.py --job "<job-dir>"

1. document.ir.json.block_order ids all exist in blocks.jsonl
2. no duplicate ids in blocks.jsonl
3. assets.index.json is regenerable from blocks (regenerate + compare)
4. ir/provenance.json (and output/provenance.json if present) regenerable from blocks
5. any projection mismatch -> fail
Plus: every block carries the required fields and a known type.

Runs in Phase 2 AND Phase 3, so the gate phase is the current phase (the
phase-in-filename convention keeps the two runs from overwriting).
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


def build_checks(job_root: Path) -> list[Check]:
    c: list[Check] = []
    doc_file = job_root / IR.IR_DOC
    blocks_file = job_root / IR.IR_BLOCKS
    c.append(Check("document_ir_present", doc_file.is_file(), message=str(doc_file)))
    c.append(Check("blocks_present", blocks_file.is_file(), message=str(blocks_file)))
    if not (doc_file.is_file() and blocks_file.is_file()):
        return c

    try:
        doc = json.loads(doc_file.read_text(encoding="utf-8"))
        blocks = IR.read_blocks(job_root)
    except (OSError, json.JSONDecodeError) as e:
        c.append(Check("ir_parseable", False, message=f"unreadable IR: {e}"))
        return c

    c.append(Check("schema_version", doc.get("schema_version") == IR.IR_SCHEMA_VERSION,
                   message=f"got {doc.get('schema_version')!r}"))

    ids = [b.get("id") for b in blocks]
    dup = len(ids) != len(set(ids))
    c.append(Check("no_duplicate_ids", not dup,
                   message="unique" if not dup else "duplicate block ids present"))

    id_set = set(ids)
    order = doc.get("block_order") or []
    missing = [o for o in order if o not in id_set]
    orphan = [i for i in ids if i not in set(order)]
    c.append(Check("block_order_exist", not missing,
                   message="all in blocks.jsonl" if not missing else f"order refs missing: {missing[:5]}"))
    c.append(Check("no_orphan_blocks", not orphan, level="warn",
                   message="all blocks in order" if not orphan else f"blocks not in order: {orphan[:5]}"))

    # required fields + known type
    bad_fields = [b.get("id") for b in blocks
                  if not all(k in b for k in IR.BLOCK_REQUIRED_FIELDS)]
    c.append(Check("required_fields", not bad_fields,
                   message="all present" if not bad_fields else f"blocks missing fields: {bad_fields[:5]}"))
    bad_type = [b.get("id") for b in blocks if b.get("type") not in IR.BLOCK_TYPES]
    c.append(Check("known_block_types", not bad_type,
                   message="ok" if not bad_type else f"unknown types: {bad_type[:5]}"))

    # PLAN §9.1: every block carries "content 或结构化子字段" — enforce per type
    no_subfield = [b.get("id") for b in blocks
                   if b.get("type") in IR.TYPE_SUBFIELD and IR.TYPE_SUBFIELD[b["type"]] not in b]
    c.append(Check("type_subfield_present", not no_subfield,
                   message="all carry their subfield" if not no_subfield else f"missing subfield: {no_subfield[:5]}"))

    # stats sanity
    stats = doc.get("stats") or {}
    c.append(Check("stats_block_count", stats.get("block_count") == len(blocks), level="warn",
                   message=f"stats={stats.get('block_count')} actual={len(blocks)}"))

    # projection 3: assets.index.json regenerable
    regen_assets = IR.project_assets_index(blocks, job_root)
    try:
        disk_assets = json.loads((job_root / IR.IR_ASSETS_INDEX).read_text(encoding="utf-8"))
        assets_ok = IR.canonical(disk_assets) == IR.canonical(regen_assets)
    except (OSError, json.JSONDecodeError):
        assets_ok = False
    c.append(Check("assets_index_regenerable", assets_ok,
                   message="matches projection" if assets_ok else "on-disk assets.index.json != regenerated"))

    # projection 4: provenance regenerable (ir + optional output)
    regen_prov = IR.project_provenance(blocks)
    for label, rel in (("ir_provenance", IR.IR_PROVENANCE), ("output_provenance", "output/provenance.json")):
        pf = job_root / rel
        if rel == "output/provenance.json" and not pf.is_file():
            continue  # output provenance is a Phase 5 product
        try:
            disk = json.loads(pf.read_text(encoding="utf-8"))
            ok = IR.canonical(disk) == IR.canonical(regen_prov)
        except (OSError, json.JSONDecodeError):
            ok = False
        c.append(Check(f"{label}_regenerable", ok,
                       message="matches projection" if ok else f"{rel} != regenerated"))
    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate Document IR")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_ir", phase="2_ir_build",
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    state = js.load_state(job_root)
    phase = state.get("current_phase") if state.get("current_phase") in js.PHASES else "2_ir_build"
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_ir", phase=phase, checks=build_checks(job_root)
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
