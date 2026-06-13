#!/usr/bin/env python3
"""Phase 5 — Assembly (v0.6): compile output/main.md from the IR.

    python3 scripts/run_python.py tools/assemble_agent_md.py --job "<job-dir>"

Generates output/main.md (+ output/parts/ when over the split thresholds),
copies referenced images to output/assets/, and writes output/provenance.json.
Replaces the v0.2 backend bridge. Every major block carries a 〔源 …〕 anchor.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir as IR  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import md_render as MD  # noqa: E402
from lib import naming  # noqa: E402
from lib import paths as P  # noqa: E402

INDEX_MD = "index.md"
INDEX_JSON = "index.json"


def read_summary(job_root: Path) -> str:
    p = job_root / P.IR_SUMMARY_SEED
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    # the seed file may hold only an instruction comment -> treat as no summary yet
    if not text or text.startswith("<!--"):
        return ""
    return text


def render_body(blocks: list[dict], assets_prefix: str) -> str:
    slugs = MD.assign_heading_slugs(blocks)
    parts: list[str] = []
    for b in blocks:
        try:
            md = MD.render_block(b, assets_prefix=assets_prefix, heading_slug=slugs.get(b.get("id")))
        except (KeyError, TypeError) as e:
            md = f"> [未解析: 区块结构损坏 id={b.get('id')} ({e})]"  # never abort the whole doc
        if md:
            parts.append(md)
    return "\n\n".join(parts)


def render_toc_or_title(blocks: list[dict], title: str) -> str:
    if any(b["type"] == "heading" for b in blocks):
        return MD.render_toc(blocks)
    title = title or "文档"
    return "\n".join(["## 目录", "", f"- [{title}](#{MD.gfm_slug(title)})"])


def section_range(sec_blocks: list[dict]) -> str | None:
    """A coarse source range for a part, from its blocks' page/slide anchors."""
    nums = []
    for b in sec_blocks:
        a = b.get("source_anchor") or {}
        v = a.get("page") if a.get("page") is not None else a.get("slide")
        if v is not None:
            nums.append(v)
    if not nums:
        sheets = [a for a in ((b.get("source_anchor") or {}).get("sheet") for b in sec_blocks) if a]
        return sheets[0] if sheets else None
    lo, hi = min(nums), max(nums)
    return f"p.{lo}" if lo == hi else f"p.{lo}-{hi}"


def _count_blocks(blocks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {"blocks": len(blocks), "headings": 0, "tables": 0, "figures": 0, "formulas": 0}
    for block in blocks:
        typ = block.get("type")
        if typ == "heading":
            counts["headings"] += 1
        elif typ == "table":
            counts["tables"] += 1
        elif typ == "figure":
            counts["figures"] += 1
        elif typ == "formula":
            counts["formulas"] += 1
    return counts


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8")) // 4)


def _md_cell(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _agent_index(
    *,
    title: str,
    summary: str,
    split_on: bool,
    main_md: str,
    main_text: str,
    parts_meta: list[dict],
    part_texts: dict[str, str],
    assets: list[str],
    blocks: list[dict],
    profile: dict,
    counts: dict,
) -> tuple[str, dict]:
    total_counts = _count_blocks(blocks)
    part_rows = []
    for part in parts_meta:
        path = part["path"]
        text = part_texts.get(path, "")
        part_counts = part.get("counts") or {}
        part_rows.append({
            "title": part["title"],
            "path": path,
            "source_range": part.get("range"),
            "blocks": part_counts.get("blocks", 0),
            "tables": part_counts.get("tables", 0),
            "figures": part_counts.get("figures", 0),
            "formulas": part_counts.get("formulas", 0),
            "approx_tokens": _estimate_tokens(text) if text else 0,
        })

    data = {
        "schema_version": "agent-friendly-md-index/0.1",
        "title": title,
        "summary": summary,
        "entry": {"path": main_md, "mode": "split_index" if split_on else "single_file",
                  "approx_tokens": _estimate_tokens(main_text)},
        "split": {"enabled": split_on, "parts": [row["path"] for row in part_rows]},
        "stats": {
            "profile": profile,
            "document": counts,
            "content": total_counts,
            "asset_count": len(assets),
            "part_count": len(part_rows),
        },
        "parts": part_rows,
        "reading_guidance": [
            "Read entry.path first.",
            "For split packages, open only the relevant parts by title/source_range before loading full text.",
            "Use assets/ only when a referenced figure is needed.",
        ],
    }

    lines = [
        f"# Agent Index: {title}",
        "",
        f"- Entry: [{main_md}]({main_md})",
        f"- Mode: {'split index' if split_on else 'single file'}",
        f"- Approx entry tokens: {data['entry']['approx_tokens']}",
        f"- Parts: {len(part_rows)}",
        f"- Assets: {len(assets)}",
    ]
    pages = profile.get("pages")
    if pages:
        lines.append(f"- Source pages: {pages}")
    if summary:
        lines.extend(["", "## Summary", "", summary])
    lines.extend([
        "",
        "## Read First",
        "",
        "- Start with the entry Markdown above.",
        "- If the entry is a split index, load only the part rows that match the task.",
        "- Use source ranges and counts below to avoid loading the whole document.",
    ])
    if part_rows:
        lines.extend([
            "",
            "## Parts",
            "",
            "| Part | Source | Blocks | Tables | Figures | Formulas | Approx Tokens |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in part_rows:
            lines.append(
                f"| [{_md_cell(row['title'])}]({row['path']}) | {_md_cell(row['source_range'] or '')} | "
                f"{row['blocks']} | {row['tables']} | {row['figures']} | {row['formulas']} | "
                f"{row['approx_tokens']} |"
            )
    lines.extend([
        "",
        "## Content Counts",
        "",
        f"- Blocks: {total_counts['blocks']}",
        f"- Headings: {total_counts['headings']}",
        f"- Tables: {total_counts['tables']}",
        f"- Figures: {total_counts['figures']}",
        f"- Formulas: {total_counts['formulas']}",
    ])
    return "\n".join(lines) + "\n", data


def _split_by_sheet(blocks: list[dict]) -> list[tuple[str, list[dict]]]:
    """Heading-less fallback: group consecutive blocks by their sheet, losing none."""
    sections: list[tuple[str, list[dict]]] = []
    title, cur = None, []
    for b in blocks:
        sh = (b.get("source_anchor") or {}).get("sheet")
        if sh and sh != title:
            if cur:
                sections.append((title or "document", cur))
            title, cur = sh, [b]
        else:
            cur.append(b)
    if cur:
        sections.append((title or "document", cur))
    return sections or [("document", blocks)]


def split_sections(blocks: list[dict]) -> list[tuple[str, list[dict]]]:
    levels = [b["heading"]["level"] for b in blocks if b["type"] == "heading"]
    if not levels:
        return _split_by_sheet(blocks)
    top = min(levels)
    sections: list[tuple[str, list[dict]]] = []
    title, cur = "前言", []
    for b in blocks:
        if b["type"] == "heading" and b["heading"]["level"] == top:
            if cur:
                sections.append((title, cur))
            title, cur = b["heading"]["text"], [b]
        else:
            cur.append(b)
    if cur:
        sections.append((title, cur))
    return sections


def should_split(blocks: list[dict], body_bytes: int, profile: dict, thr: dict) -> bool:
    pages = profile.get("pages") or 0
    sheets = len({b["source_anchor"].get("sheet") for b in blocks
                  if (b.get("source_anchor") or {}).get("kind") == "sheet_range"})
    return (len(blocks) > thr.get("max_blocks", 1500)
            or body_bytes > thr.get("max_markdown_bytes", 307200)
            or (pages and pages > thr.get("max_pages", 100))
            or sheets > thr.get("max_sheets", 3))


def copy_assets(blocks: list[dict], job_root: Path) -> list[str]:
    dst = job_root / P.OUTPUT_ASSETS
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for b in blocks:
        if b["type"] != "figure":
            continue
        fig = b["figure"]
        if fig.get("likely_noise") or b.get("likely_noise"):
            continue
        rel = fig.get("asset_file") or ""
        src = job_root / rel
        if src.is_file():
            shutil.copy2(src, dst / src.name)
            copied.append(f"assets/{src.name}")
    return copied


def update_manifest(job_root: Path, main_rel, parts, assets, split_on) -> None:
    mf = job_root / "output" / "manifest.json"
    if not mf.is_file():
        return
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    man.setdefault("outputs", {})
    man["outputs"]["main"] = main_rel
    man["outputs"]["index"] = {"markdown": INDEX_MD, "json": INDEX_JSON}
    man["outputs"]["parts"] = [{"path": p["path"], "title": p["title"], "source_range": p.get("range")} for p in parts]
    man["outputs"]["assets"] = [{"path": a} for a in assets]
    man.setdefault("split", {})["enabled"] = split_on
    man["split"]["parts"] = [p["path"] for p in parts]
    mf.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Assemble output/main.md from the IR.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file() or not (job_root / IR.IR_BLOCKS).is_file():
        print("[error] need STATE.json and IR (run build_ir first)", file=sys.stderr)
        return 2
    try:
        blocks, doc = IR.load_ir(job_root)
        state = js.load_state(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] unreadable: {e}", file=sys.stderr)
        return 1

    meta = doc.get("metadata", {})
    profile = state.get("document_profile", {})
    counts = doc.get("stats", {})
    thr = (state.get("config") or {}).get("split_thresholds", js.DEFAULT_SPLIT_THRESHOLDS)
    summary = read_summary(job_root)

    body_single = render_body(blocks, "assets")
    split_on = should_split(blocks, len(body_single.encode("utf-8")), profile, thr)

    out_dir = job_root / "output"
    (out_dir / "parts").mkdir(parents=True, exist_ok=True)
    fm = MD.render_front_matter(meta, profile, counts, split_on)
    head = [fm]
    # avoid duplicating the title: a single-file doc whose body starts with a
    # heading lets that heading be the title; otherwise emit an explicit H1.
    body_starts_heading = bool(blocks) and blocks[0]["type"] == "heading"
    if split_on or not body_starts_heading:
        head.append(f"# {meta.get('title', '文档')}")
    if summary:
        head.append(f"> **摘要**\n> {summary}")

    parts_meta: list[dict] = []
    part_texts: dict[str, str] = {}
    # a fresh assembly always starts from no parts, so split<->non-split never leaks orphans
    for old in (out_dir / "parts").glob("*.md"):
        old.unlink()
    if not split_on:
        doc_md = "\n\n".join([*head, render_toc_or_title(blocks, str(meta.get("title", "文档"))), "---", body_single])
        (out_dir / "main.md").write_text(doc_md + "\n", encoding="utf-8")
        main_text = doc_md + "\n"
    else:
        sections = split_sections(blocks)
        toc_lines = ["## 分卷目录", ""]
        for i, (title, sec_blocks) in enumerate(sections, 1):
            rng = section_range(sec_blocks)
            slug = naming.ascii_slug(title) or naming.ascii_slug(rng or "") or "part"
            fname = f"{i:02d}-{slug}.md"
            rel_path = f"parts/{fname}"
            body = render_body(sec_blocks, "../assets")
            # the section's own leading heading is the part title; only synthesize
            # an H1 for a leading non-heading section (e.g. 前言).
            starts_heading = bool(sec_blocks) and sec_blocks[0]["type"] == "heading"
            content = body if starts_heading else f"# {title}\n\n{body}"
            (out_dir / "parts" / fname).write_text(content + "\n", encoding="utf-8")
            part_texts[rel_path] = content + "\n"
            part_counts = _count_blocks(sec_blocks)
            parts_meta.append({"path": rel_path, "title": title, "range": rng, "counts": part_counts})
            details = []
            if rng:
                details.append(rng)
            details.append(f"{part_counts['blocks']} blocks")
            if part_counts["tables"] or part_counts["figures"] or part_counts["formulas"]:
                details.append(
                    f"tables {part_counts['tables']}, figures {part_counts['figures']}, formulas {part_counts['formulas']}"
                )
            toc_lines.append(f"- [{title}]({rel_path}) - {', '.join(details)}")
        index_md = "\n\n".join([*head, "\n".join(toc_lines)])
        (out_dir / "main.md").write_text(index_md + "\n", encoding="utf-8")
        main_text = index_md + "\n"

    assets = copy_assets(blocks, job_root)
    agent_index_md, agent_index_json = _agent_index(
        title=str(meta.get("title", "文档")),
        summary=summary,
        split_on=split_on,
        main_md="main.md",
        main_text=main_text,
        parts_meta=parts_meta,
        part_texts=part_texts,
        assets=assets,
        blocks=blocks,
        profile=profile,
        counts=counts,
    )
    (out_dir / INDEX_MD).write_text(agent_index_md, encoding="utf-8")
    (out_dir / INDEX_JSON).write_text(json.dumps(agent_index_json, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    IR.write_json(job_root / "output" / "provenance.json", IR.project_provenance(blocks))
    update_manifest(job_root, "main.md", parts_meta, assets, split_on)

    print(f"[ok] assembled output/main.md (split={split_on}, parts={len(parts_meta)}, assets={len(assets)})")
    print("     next: Phase 5 gates -> validate_links --mode markdown (validate_agent_md_quality/placeholders in v0.7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
