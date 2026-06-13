#!/usr/bin/env python3
"""Phase 2 — Asset binding (v0.4): bind figures to captions and rename assets.

    python3 scripts/run_python.py tools/link_assets.py --job "<job-dir>"

Refines the IR produced by build_ir.py:
- binds each figure to an adjacent caption (figure_no + caption text),
- renames asset files to semantic §10 names and updates asset_id/asset_file,
- adds `references` relations where body text cites a figure number,
then rewrites blocks.jsonl + regenerates assets.index.json / provenance.json and
updates document.ir.json relations. Run after build_ir, before validate_links.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import naming  # noqa: E402
from lib import paths as P  # noqa: E402

# keyword + a number token that contains at least one digit (so "图 3-3", "表 A1"
# bind but prose like "图 shows" does not) and ends alphanumeric (drops trailing ".")
_CAPTION = re.compile(
    r"^\s*(图表|图|圖|表|Figure|Fig\.?|Table|Chart)\s*"
    r"((?=[^\s]*[0-9])[0-9A-Za-z](?:[0-9A-Za-z.\-]*[0-9A-Za-z])?)"
)


def _para_text(block: dict) -> str:
    return (block.get("content") or {}).get("text", "")


def bind_captions(blocks: list[dict]) -> int:
    """Attach an adjacent caption para to each figure. Returns count bound.

    A caption para is claimed by at most one figure (next-sibling preferred),
    so a caption between two figures does not double-bind.
    """
    bound = 0
    consumed: set[str] = set()
    for k, b in enumerate(blocks):
        if b["type"] != "figure":
            continue
        for nb in (blocks[k + 1] if k + 1 < len(blocks) else None,
                   blocks[k - 1] if k >= 1 else None):
            if not nb or nb["type"] != "para" or nb["id"] in consumed:
                continue
            m = _CAPTION.match(_para_text(nb))
            if m:
                b["figure"]["figure_no"] = f"{m.group(1)} {m.group(2)}".strip()
                b["figure"]["caption"] = _para_text(nb)
                nb.setdefault("content", {})["is_caption_for"] = b["id"]
                b["needs_review"] = b["figure"].get("description") is None  # still needs vision
                consumed.add(nb["id"])
                bound += 1
                break
    return bound


def rename_assets(blocks: list[dict], job_root: Path) -> int:
    """Rename figure asset files to semantic §10 names; update id/file. Returns renamed.

    Idempotent: a figure's own current filename is excluded from the collision
    set, so re-running recomputes the same name and is a no-op.
    """
    img_dir = job_root / P.EXTRACTED_IMAGES
    existing = {p.name for p in img_dir.iterdir() if p.is_file()} if img_dir.is_dir() else set()
    renamed = 0
    seq = 0
    for b in blocks:
        if b["type"] != "figure":
            continue
        seq += 1
        fig = b["figure"]
        old_rel = fig.get("asset_file") or ""
        fig.setdefault("original_asset_file", old_rel)
        own = Path(old_rel).name
        old_path = job_root / old_rel
        ext = Path(old_rel).suffix or ".png"
        slug = fig.get("caption") or fig.get("figure_no")
        new_name = naming.asset_filename("fig", b.get("source_anchor"), slug, seq, ext, existing - {own})
        existing.discard(own)
        existing.add(new_name)
        if own == new_name:
            continue
        if not old_path.is_file():
            # source missing: don't fabricate a reference to a non-existent file
            print(f"[warn] asset file missing, left as-is: {old_rel}", file=sys.stderr)
            continue
        try:
            old_path.rename(img_dir / new_name)
        except OSError as e:
            print(f"[warn] rename failed {old_rel} -> {new_name}: {e}", file=sys.stderr)
            existing.discard(new_name)
            existing.add(own)
            continue
        renamed += 1
        fig["asset_file"] = f"{P.EXTRACTED_IMAGES}/{new_name}"
        fig["asset_id"] = f"asset_{Path(new_name).stem}"
    return renamed


def link_references(blocks: list[dict]) -> list[dict]:
    """Add `references` relations where a para cites a known figure_no."""
    fig_by_no = {b["figure"]["figure_no"]: b["id"]
                 for b in blocks if b["type"] == "figure" and b["figure"].get("figure_no")}
    rels: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for b in blocks:
        if b["type"] != "para" or (b.get("content") or {}).get("is_caption_for"):
            continue
        text = _para_text(b)
        for fno, fid in fig_by_no.items():
            if not fno or (b["id"], fid) in seen:
                continue
            # boundary after the number so "图 3-3" does not also match "图 3"
            if re.search(re.escape(fno) + r"(?![0-9A-Za-z.\-])", text):
                rels.append({"from": b["id"], "to": fid, "type": "references"})
                seen.add((b["id"], fid))
    return rels


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Bind figures to captions and name assets.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        print(f"[error] no STATE.json in {job_root}", file=sys.stderr)
        return 2
    doc_file = job_root / IR.IR_DOC
    if not (job_root / IR.IR_BLOCKS).is_file() or not doc_file.is_file():
        print("[error] no IR; run build_ir first", file=sys.stderr)
        return 2
    try:
        blocks = IR.read_blocks(job_root)
        doc = json.loads(doc_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1

    n_cap = bind_captions(blocks)
    n_ren = rename_assets(blocks, job_root)
    references = link_references(blocks)

    # relations = uses_asset (from updated figures) + references
    uses = [{"from": b["id"], "to": b["figure"]["asset_id"], "type": "uses_asset"}
            for b in blocks if b["type"] == "figure"]
    doc["relations"] = uses + references

    IR.write_blocks(job_root, blocks)
    IR.write_json(doc_file, doc)
    IR.write_json(job_root / IR.IR_ASSETS_INDEX, IR.project_assets_index(blocks, job_root))
    IR.write_json(job_root / IR.IR_PROVENANCE, IR.project_provenance(blocks))

    print(f"[ok] asset binding: captions bound={n_cap}, assets renamed={n_ren}, "
          f"text references={len(references)}")
    print("     next: Phase 2 link gate ->")
    print(f'       {sys.executable} scripts/run_python.py validators/validate_links.py --job "{job_root}" --mode ir')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
