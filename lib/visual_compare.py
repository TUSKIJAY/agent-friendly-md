"""Source-vs-rendered visual comparison artifacts for Phase 6.

The first implementation is deliberately page-level: it pairs a source page or
slide render from ``extracted/pages/`` with the rendered HTML screenshot. The
artifact is still explicit and gate-enforced, and can later be replaced by
anchor-region crops without changing the diagnostics contract.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .anchors import format_anchor
from . import ir as IR
from . import jobstate as js
from . import paths as P

SAMPLE_LIMIT = 3
SAMPLE_SEED = "first-anchor-per-source-index/v1"
REASON = "page-level source render plus full rendered HTML screenshot"
TEXT_EVIDENCE_REASON = "source text evidence plus rendered HTML screenshot"
_PAGE_RE = re.compile(r"\bp\.(\d+)")
_SLIDE_RE = re.compile(r"\bslide\s+(\d+)", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d+)")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _rel(job_root: Path, path: Path) -> str:
    return path.relative_to(job_root).as_posix()


def _anchor_target(anchor: dict) -> dict | None:
    text = str(anchor.get("source_anchor") or "")
    page = _PAGE_RE.search(text)
    if page:
        return {
            "kind": "pdf_page",
            "index": int(page.group(1)),
            "anchor_id": anchor.get("id", ""),
            "source_anchor": text,
        }
    slide = _SLIDE_RE.search(text)
    if slide:
        return {
            "kind": "slide",
            "index": int(slide.group(1)),
            "anchor_id": anchor.get("id", ""),
            "source_anchor": text,
        }
    return None


def _sample_targets(anchor_map: dict) -> list[dict]:
    samples: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for anchor in anchor_map.get("anchors") or []:
        target = _anchor_target(anchor)
        if not target:
            continue
        key = (target["kind"], target["index"])
        if key in seen:
            continue
        seen.add(key)
        samples.append(target)
        if len(samples) >= SAMPLE_LIMIT:
            break
    return samples


def _text_targets(anchor_map: dict) -> list[dict]:
    samples: list[dict] = []
    seen: set[str] = set()
    for anchor in anchor_map.get("anchors") or []:
        text = str(anchor.get("source_anchor") or "")
        if not text or _anchor_target(anchor) is not None or text in seen:
            continue
        seen.add(text)
        samples.append({
            "anchor_id": anchor.get("id", ""),
            "source_anchor": text,
            "file": anchor.get("file", ""),
            "line": anchor.get("line", ""),
        })
        if len(samples) >= SAMPLE_LIMIT:
            break
    return samples


def _source_images(job_root: Path) -> list[Path]:
    pages = job_root / P.EXTRACTED_PAGES
    if not pages.is_dir():
        return []
    return sorted(p for p in pages.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)


def _image_number(path: Path) -> int | None:
    nums = _NUM_RE.findall(path.stem)
    return int(nums[-1]) if nums else None


def _render_pdf_page(job_root: Path, page_number: int) -> tuple[Path | None, str]:
    try:
        import fitz  # noqa: PLC0415
    except ImportError as e:
        return None, f"PyMuPDF unavailable for source page render: {e}"
    try:
        state = js.load_state(job_root)
    except (OSError, ValueError) as e:
        return None, f"STATE unreadable for source page render: {e}"
    source_rel = next((s for s in state.get("source_files") or [] if str(s).lower().endswith(".pdf")), "")
    if not source_rel:
        return None, "no PDF source declared for source page render"
    source = job_root / source_rel
    if not source.is_file():
        return None, f"PDF source missing: {source_rel}"
    target = job_root / P.EXTRACTED_PAGES / f"page_{page_number:03d}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with fitz.open(source) as doc:
            if page_number < 1 or page_number > len(doc):
                return None, f"PDF page out of range: {page_number}"
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(target)
    except (OSError, RuntimeError, ValueError) as e:
        return None, f"PDF source page render failed for p.{page_number}: {e}"
    return target, ""


def _find_source_image(job_root: Path, images: list[Path], target: dict) -> tuple[Path | None, str]:
    prefixes = ("slide",) if target["kind"] == "slide" else ("page",)
    preferred = [p for p in images if p.stem.lower().startswith(prefixes)]
    for group in (preferred, images):
        for path in group:
            if _image_number(path) == target["index"]:
                return path, ""
    if target["kind"] == "pdf_page":
        return _render_pdf_page(job_root, target["index"])
    return None, f"no source render for {target['kind']} {target['index']}"


def _thumbnail(img, max_size: tuple[int, int]):
    thumb = img.convert("RGB")
    thumb.thumbnail(max_size)
    return thumb


def _write_comparison(source: Path, rendered: Path, target: Path, title: str) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    with Image.open(source) as src_img, Image.open(rendered) as rendered_img:
        src = _thumbnail(src_img, (700, 920))
        ren = _thumbnail(rendered_img, (700, 920))
        header = 54
        gutter = 24
        width = src.width + ren.width + gutter + 32
        height = max(src.height, ren.height) + header + 24
        canvas = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 14), title, fill=(20, 20, 20))
        draw.text((16, 36), "source page/slide", fill=(90, 90, 90))
        right_x = 16 + src.width + gutter
        draw.text((right_x, 36), "rendered HTML screenshot", fill=(90, 90, 90))
        canvas.paste(src, (16, header))
        canvas.paste(ren, (right_x, header))
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target)


def _anchor_text(block: dict) -> str:
    marker = format_anchor(block.get("source_anchor"))
    if marker.startswith("〔源 ") and marker.endswith("〕"):
        return marker[3:-1]
    return marker


def _snippet(block: dict) -> str:
    btype = block.get("type")
    if btype == "heading":
        return (block.get("heading") or {}).get("text", "")
    if btype == "para":
        return (block.get("content") or {}).get("text", "")
    if btype == "list":
        items = (block.get("content") or {}).get("items") or []
        return "\n".join(f"- {item}" for item in items[:6])
    if btype == "table":
        table = block.get("table") or {}
        cols = table.get("columns") or []
        rows = table.get("rows") or []
        preview = [" | ".join(str(c) for c in cols)]
        for row in rows[:3]:
            preview.append(" | ".join(str((cell or {}).get("text", "")) for cell in row))
        return "\n".join(line for line in preview if line.strip())
    if btype == "figure":
        fig = block.get("figure") or {}
        return "\n".join(
            str(x) for x in (fig.get("figure_no"), fig.get("caption"), fig.get("description"), fig.get("asset_file"))
            if x
        )
    if btype == "formula":
        formula = block.get("formula") or {}
        return formula.get("latex") or formula.get("plain_text_source") or ""
    if btype == "code":
        return (block.get("code") or {}).get("text", "")
    return ""


def _blocks_by_anchor(job_root: Path) -> tuple[dict[str, list[dict]], str]:
    try:
        blocks = IR.read_blocks(job_root)
    except (OSError, ValueError) as e:
        return {}, f"IR blocks unavailable for source evidence: {e}"
    out: dict[str, list[dict]] = {}
    for block in blocks:
        out.setdefault(_anchor_text(block), []).append(block)
    return out, ""


def _rendered_line(job_root: Path, target: dict) -> str:
    try:
        path = job_root / str(target.get("file") or "")
        line_no = int(target.get("line") or 0)
        if not path.is_file() or line_no <= 0:
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[line_no - 1] if line_no <= len(lines) else ""
    except (OSError, ValueError):
        return ""


def _write_text_evidence(job_root: Path, target: dict, block: dict, rendered_rel: str, out: Path) -> None:
    anchor = block.get("source_anchor") or {}
    heading_path = anchor.get("heading_path") or []
    details = [
        "# Source Evidence",
        "",
        f"- source_anchor: {target['source_anchor']}",
        f"- anchor_id: {target.get('anchor_id', '')}",
        f"- rendered_markdown: {target.get('file', '')}:{target.get('line', '')}",
        f"- rendered_screenshot: {rendered_rel}",
        f"- ir_block: {block.get('id', '')}",
        f"- block_type: {block.get('type', '')}",
        f"- source_kind: {anchor.get('kind', '')}",
        f"- source_file: {anchor.get('source_file', '')}",
    ]
    if heading_path:
        details.append(f"- heading_path: {' > '.join(str(x) for x in heading_path)}")
    for key in ("paragraph_index", "block_index", "sheet", "range", "page", "slide"):
        if anchor.get(key) is not None:
            details.append(f"- {key}: {anchor.get(key)}")
    details.extend([
        "",
        "## Source Snippet",
        "",
        "```text",
        _snippet(block)[:2000],
        "```",
        "",
        "## Rendered Line",
        "",
        "```markdown",
        _rendered_line(job_root, target)[:1000],
        "```",
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(details) + "\n", encoding="utf-8")


def generate_source_comparisons(
    job_root: Path,
    anchor_map: dict,
    screenshots: list[str],
) -> dict:
    out_dir = job_root / P.REVIEW_SOURCE_COMPARISONS
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "dir": P.REVIEW_SOURCE_COMPARISONS,
        "artifacts": [],
        "sampled_pages": [],
        "sampled_source_evidence": [],
        "sampled_anchors": [],
        "reason": REASON,
        "seed": SAMPLE_SEED,
        "warnings": [],
    }
    rendered_rel = next((p for p in screenshots if "desktop" in p), screenshots[0] if screenshots else "")
    if not rendered_rel:
        result["warnings"].append("no rendered screenshot available for source comparison")
        return result
    rendered = job_root / rendered_rel
    if not rendered.is_file():
        result["warnings"].append(f"rendered screenshot missing: {rendered_rel}")
        return result

    images = _source_images(job_root)
    samples = _sample_targets(anchor_map)

    for sample in samples:
        source, source_warning = _find_source_image(job_root, images, sample)
        if source is None:
            result["warnings"].append(source_warning)
            continue
        kind_label = "slide" if sample["kind"] == "slide" else "page"
        out = out_dir / f"{kind_label}_{sample['index']:03d}_compare.png"
        try:
            _write_comparison(source, rendered, out, sample["source_anchor"])
        except (OSError, ImportError) as e:
            result["warnings"].append(f"comparison render failed for {source.name}: {e}")
            continue
        result["artifacts"].append(_rel(job_root, out))
        result["sampled_pages"].append({
            "kind": sample["kind"],
            "index": sample["index"],
            "source_image": _rel(job_root, source),
            "rendered_screenshot": rendered_rel,
            "comparison": _rel(job_root, out),
            "reason": REASON,
        })
        result["sampled_anchors"].append({
            "anchor_id": sample["anchor_id"],
            "source_anchor": sample["source_anchor"],
            "comparison": _rel(job_root, out),
        })

    text_samples = _text_targets(anchor_map)
    if text_samples:
        by_anchor, block_warning = _blocks_by_anchor(job_root)
        if block_warning:
            result["warnings"].append(block_warning)
        for idx, sample in enumerate(text_samples, 1):
            matches = by_anchor.get(sample["source_anchor"]) or []
            if not matches:
                result["warnings"].append(f"no IR block matched source anchor: {sample['source_anchor']}")
                continue
            block = matches[0]
            out = out_dir / f"source_evidence_{idx:03d}.md"
            try:
                _write_text_evidence(job_root, sample, block, rendered_rel, out)
            except OSError as e:
                result["warnings"].append(f"source evidence write failed for {sample['source_anchor']}: {e}")
                continue
            rel = _rel(job_root, out)
            result["artifacts"].append(rel)
            result["sampled_source_evidence"].append({
                "anchor_id": sample["anchor_id"],
                "source_anchor": sample["source_anchor"],
                "source_kind": (block.get("source_anchor") or {}).get("kind", ""),
                "source_file": (block.get("source_anchor") or {}).get("source_file", ""),
                "block_id": block.get("id", ""),
                "rendered_screenshot": rendered_rel,
                "evidence": rel,
                "reason": TEXT_EVIDENCE_REASON,
            })
            result["sampled_anchors"].append({
                "anchor_id": sample["anchor_id"],
                "source_anchor": sample["source_anchor"],
                "comparison": rel,
            })

    if not result["artifacts"]:
        if not samples and not text_samples:
            result["warnings"].append("no source anchors available for source evidence")
        else:
            result["warnings"].append("no source comparison or source evidence artifacts generated")
    return result
