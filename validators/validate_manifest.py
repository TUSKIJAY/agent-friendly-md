#!/usr/bin/env python3
"""Gate: validate output/manifest.json (PLAN §4/§12, review-003 minor 7).

    python3 scripts/run_python.py validators/validate_manifest.py --job "<dir>" --mode draft
    python3 scripts/run_python.py validators/validate_manifest.py --job "<dir>" --mode final

Two modes because the manifest's required content differs by phase:
- draft (Phase 0): schema, ids, and verifiable source entries.
- final (Phase 6/7): additionally the compiled outputs, split parts, input hashes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import gates  # noqa: E402
from lib.gates import Check  # noqa: E402

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def draft_checks(job_root: Path, man: dict, state: dict | None) -> list[Check]:
    c: list[Check] = []
    c.append(Check("schema_version", man.get("schema_version") == mf.MANIFEST_SCHEMA_VERSION,
                   message=f"got {man.get('schema_version')!r}"))
    c.append(Check("stage", man.get("stage") in mf.STAGES, message=f"stage={man.get('stage')!r}"))
    c.append(Check("job_id_present", bool(man.get("job_id")), message=str(man.get("job_id"))))
    if state is not None:
        c.append(Check("job_id_matches_state", man.get("job_id") == state.get("job_id"),
                       message="matches STATE" if man.get("job_id") == state.get("job_id") else
                               f"manifest={man.get('job_id')} state={state.get('job_id')}"))
    c.append(Check("document_slug", bool(man.get("document_slug")), message=str(man.get("document_slug"))))

    sources = man.get("sources") or []
    c.append(Check("sources_nonempty", len(sources) > 0, message=f"{len(sources)} source(s)"))
    for i, s in enumerate(sources):
        rel = s.get("path", "")
        exists = (job_root / rel).is_file() if rel else False
        c.append(Check(f"source[{i}].file_exists", exists, message=rel or "<no path>"))
        c.append(Check(f"source[{i}].sha256", bool(_SHA256.match(str(s.get("sha256", "")))),
                       message="valid sha256" if _SHA256.match(str(s.get("sha256", ""))) else "bad/no sha256"))
        c.append(Check(f"source[{i}].bytes", isinstance(s.get("bytes"), int) and s["bytes"] >= 0,
                       level="warn", message=str(s.get("bytes"))))
    return c


def final_checks(job_root: Path, man: dict) -> list[Check]:
    c: list[Check] = []
    c.append(Check("stage_is_final", man.get("stage") == "final", message=f"stage={man.get('stage')!r}"))
    outputs = man.get("outputs") or {}
    main_rel = outputs.get("main")
    c.append(Check("outputs.main_set", bool(main_rel), message=str(main_rel)))
    if main_rel:
        c.append(Check("outputs.main_exists", _output_path(job_root, str(main_rel)).is_file(), message=str(main_rel)))
    index = outputs.get("index") or {}
    if isinstance(index, dict):
        index_md = index.get("markdown")
        index_json = index.get("json")
    else:
        index_md = index_json = None
    c.append(Check("outputs.index_markdown_set", bool(index_md), message=str(index_md)))
    c.append(Check("outputs.index_json_set", bool(index_json), message=str(index_json)))
    if index_md:
        c.append(Check("outputs.index_markdown_exists", _output_path(job_root, str(index_md)).is_file(),
                       message=str(index_md)))
    if index_json:
        c.append(Check("outputs.index_json_exists", _output_path(job_root, str(index_json)).is_file(),
                       message=str(index_json)))
    parts = outputs.get("parts") or []
    c.append(Check("parts_is_list", isinstance(parts, list), level="warn", message=f"{len(parts)} part(s)"))
    part_missing = [
        str(p.get("path")) for p in parts if isinstance(p, dict)
        and not _output_path(job_root, str(p.get("path", ""))).is_file()
    ]
    c.append(Check("parts_exist", not part_missing,
                   message="ok" if not part_missing else f"missing: {part_missing[:5]}"))
    assets = outputs.get("assets") or []
    asset_missing = [
        str(a.get("path")) for a in assets if isinstance(a, dict)
        and not _output_path(job_root, str(a.get("path", ""))).is_file()
    ]
    c.append(Check("assets_exist", not asset_missing,
                   message="ok" if not asset_missing else f"missing: {asset_missing[:5]}"))
    c.append(Check("input_hashes_present", bool(man.get("input_hashes")),
                   message=f"{len(man.get('input_hashes') or {})} hash(es)"))
    return c


def _output_path(job_root: Path, rel: str) -> Path:
    if rel.startswith("output/"):
        return job_root / rel
    return job_root / "output" / rel


def load_state_best_effort(job_root: Path) -> tuple[dict | None, Check | None]:
    """Load STATE for the job_id cross-check; surface (not swallow) a bad STATE."""
    if not (job_root / "STATE.json").is_file():
        return None, None
    try:
        return js.load_state(job_root), None
    except (OSError, json.JSONDecodeError) as e:
        return None, Check("state_loadable", False, level="warn",
                           message=f"STATE.json present but unreadable: {e}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate output/manifest.json")
    ap.add_argument("--job", required=True)
    ap.add_argument("--mode", choices=["draft", "final"], default="draft")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    state, state_warn = load_state_best_effort(job_root)
    phase = (state or {}).get("current_phase") if (state or {}).get("current_phase") in js.PHASES else js.PHASES[0]
    gate_name = f"validate_manifest_{args.mode}"

    man_file = job_root / "output" / "manifest.json"
    # Missing/unparseable manifest is a hard fail that still emits a gate result.
    if not man_file.is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name=gate_name, phase=phase,
            checks=[Check("manifest_present", False, message=f"manifest not found: {man_file}")],
        )
    try:
        man = json.loads(man_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return gates.write_gate_result(
            job_root=job_root, gate_name=gate_name, phase=phase,
            checks=[Check("manifest_parseable", False, message=f"manifest is not valid JSON: {e}")],
        )

    checks: list[Check] = []
    if state_warn is not None:
        checks.append(state_warn)
    checks += draft_checks(job_root, man, state)
    if args.mode == "final":
        checks += final_checks(job_root, man)

    return gates.write_gate_result(
        job_root=job_root, gate_name=gate_name, phase=phase, checks=checks
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
