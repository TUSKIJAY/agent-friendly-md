#!/usr/bin/env python3
"""Gate: validate asset links (PLAN §5/§10/§12).

    python3 scripts/run_python.py validators/validate_links.py --job "<dir>" --mode ir
    python3 scripts/run_python.py validators/validate_links.py --job "<dir>" --mode markdown

- ir mode: figure->asset references resolve, asset files exist, names conform to §10,
  no collisions, relations point at real assets (used in Phase 2/3).
- markdown mode: local links/images in main.md + parts/ resolve to existing files,
  asset names conform (used in Phase 5).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import naming  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import gates  # noqa: E402
from lib.gates import Check  # noqa: E402
from lib.md_render import gfm_slug  # noqa: E402

_MD_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_HTML_ID = re.compile(r'id="([^"]+)"')
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*(?:　〔源.*)?$")


def _anchor_ids(text: str) -> set[str]:
    ids = set(_HTML_ID.findall(text))
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            ids.add(gfm_slug(m.group(1)))
    return ids


def ir_checks(job_root: Path) -> list[Check]:
    c: list[Check] = []
    if not (job_root / IR.IR_BLOCKS).is_file():
        c.append(Check("blocks_present", False, message="ir/blocks.jsonl missing"))
        return c
    try:
        blocks = IR.read_blocks(job_root)
        index = json.loads((job_root / IR.IR_ASSETS_INDEX).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        c.append(Check("ir_readable", False, message=f"{e}"))
        return c
    assets = index.get("assets") or {}

    figs = [b for b in blocks if b["type"] == "figure"]
    dangling = [b["id"] for b in figs if b["figure"].get("asset_id") not in assets]
    c.append(Check("figure_assets_indexed", not dangling,
                   message="all figure assets in index" if not dangling else f"dangling: {dangling[:5]}"))

    # re-verify against disk, not the stored `exists` flag (which can go stale)
    broken = [aid for aid, e in assets.items()
              if not e.get("file") or not (job_root / e["file"]).is_file()]
    c.append(Check("asset_files_exist", not broken,
                   message="no broken links" if not broken else f"missing files: {broken[:5]}"))

    bad_names = [Path(e["file"]).name for e in assets.values()
                 if e.get("file") and not naming.is_valid_asset_name(Path(e["file"]).name)]
    c.append(Check("asset_names_conform", not bad_names,
                   message="§10 conformant" if not bad_names else f"bad names: {bad_names[:5]}"))

    files = [e["file"] for e in assets.values() if e.get("file")]
    collisions = sorted({f for f in files if files.count(f) > 1})
    c.append(Check("no_name_collisions", not collisions,
                   message="unique" if not collisions else f"collisions: {collisions[:5]}"))

    # orphan = image file on disk that no figure block declares (lost from the IR)
    img_dir = job_root / P.EXTRACTED_IMAGES
    referenced = {e["file"] for e in assets.values() if e.get("file")}
    on_disk = ({f"{P.EXTRACTED_IMAGES}/{p.name}" for p in img_dir.iterdir() if p.is_file()}
               if img_dir.is_dir() else set())
    orphan_files = sorted(on_disk - referenced)
    c.append(Check("no_orphan_image_files", not orphan_files, level="warn",
                   message="all images referenced" if not orphan_files else f"orphan files: {orphan_files[:5]}"))
    return c


def markdown_checks(job_root: Path) -> list[Check]:
    c: list[Check] = []
    mains = []
    main = job_root / P.OUTPUT_MAIN
    if main.is_file():
        mains.append(main)
    index = job_root / "output/index.md"
    if index.is_file():
        mains.append(index)
    mains += sorted((job_root / P.OUTPUT_PARTS).glob("*.md"))
    c.append(Check("main_present", bool(mains), message="output/main.md, index.md, or parts/ present"))
    if not mains:
        return c

    broken: list[str] = []
    bad_names: list[str] = []
    dead_anchors: list[str] = []
    for md in mains:
        text = md.read_text(encoding="utf-8", errors="replace")
        ids = _anchor_ids(text)
        for target in _MD_LINK.findall(text):
            if re.match(r"^[a-z]+://", target):
                continue  # external
            if target.startswith("#"):
                frag = target[1:]
                if frag and frag not in ids:
                    dead_anchors.append(f"{md.name}->{target}")
                continue
            local = target.split("#", 1)[0]
            if not (md.parent / local).exists():
                broken.append(f"{md.name}->{local}")
            name = Path(local).name
            if local.startswith("assets/") and not naming.is_valid_asset_name(name):
                bad_names.append(name)
    c.append(Check("local_links_resolve", not broken,
                   message="all resolve" if not broken else f"broken: {broken[:5]}"))
    c.append(Check("inpage_anchors_resolve", not dead_anchors,
                   message="TOC anchors resolve" if not dead_anchors else f"dead anchors: {dead_anchors[:5]}"))
    c.append(Check("asset_names_conform", not bad_names, level="warn",
                   message="ok" if not bad_names else f"bad names: {bad_names[:5]}"))
    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate asset links")
    ap.add_argument("--job", required=True)
    ap.add_argument("--mode", choices=["ir", "markdown"], required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name=f"validate_links_{args.mode}", phase="2_ir_build",
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    state = js.load_state(job_root)
    phase = state.get("current_phase") if state.get("current_phase") in js.PHASES else "2_ir_build"
    checks = ir_checks(job_root) if args.mode == "ir" else markdown_checks(job_root)
    return gates.write_gate_result(
        job_root=job_root, gate_name=f"validate_links_{args.mode}", phase=phase, checks=checks
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
