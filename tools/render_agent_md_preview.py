#!/usr/bin/env python3
"""Phase 6: render Agent Markdown preview HTML and anchor_map."""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import subproc  # noqa: E402
from lib import visual_compare as VC  # noqa: E402

SOURCE_RE = re.compile(r"〔源 ([^〕]+)〕")


def _markdown_files(job_root: Path) -> list[Path]:
    files = []
    main = job_root / P.OUTPUT_MAIN
    if main.is_file():
        files.append(main)
    parts = job_root / P.OUTPUT_PARTS
    if parts.is_dir():
        files.extend(sorted(parts.glob("*.md")))
    return files


def _combined_markdown(job_root: Path, files: list[Path]) -> str:
    chunks = []
    for path in files:
        rel = path.relative_to(job_root).as_posix()
        chunks.append(f"<!-- source-file: {rel} -->\n\n" + path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(chunks)


def build_anchor_map(job_root: Path, files: list[Path]) -> dict:
    anchors = []
    for path in files:
        rel = path.relative_to(job_root).as_posix()
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in SOURCE_RE.finditer(line):
                anchors.append({
                    "id": f"anchor_{len(anchors) + 1:04d}",
                    "file": rel,
                    "line": line_no,
                    "source_anchor": match.group(1),
                })
    return {"schema_version": "agent-friendly-md-anchor-map/0.1", "anchors": anchors}


def _fallback_html(markdown: str) -> str:
    return "<pre>" + html.escape(markdown) + "</pre>"


def render_markdown(markdown: str) -> tuple[str, bool, str]:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return _fallback_html(markdown), False, "pandoc missing; used escaped preformatted fallback"
    try:
        result = subproc.run_text(
            [pandoc, "--from", "gfm", "--to", "html"],
            input=markdown,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return _fallback_html(markdown), False, f"pandoc failed: {e}"
    if result.returncode != 0:
        return _fallback_html(markdown), False, f"pandoc exited {result.returncode}: {result.stderr[:200]}"
    return result.stdout, True, "pandoc"


KATEX_DIR = Path(__file__).resolve().parent.parent / "vendor" / "katex"
_MATH_RE = re.compile(r"\$\$.+?\$\$|\\\(.+?\\\)|\\\[.+?\\\]", re.DOTALL)


def _katex_head() -> tuple[str, dict]:
    """Inline the vendored KaTeX so $$…$$ / \\(…\\) render offline.

    Inlining (rather than linking) sidesteps the document's ``<base href>`` and
    keeps ``rendered.html`` self-contained/portable. Fonts are not inlined, so
    KaTeX falls back to system fonts for glyphs — layout is still correct, which
    is enough for a review screenshot. Fully decoupled from the gate: the return
    status lands in diagnostics under ``formula_render`` (never ``warnings``), so
    a missing/again-vendored KaTeX can't affect visual acceptance.
    """
    css = KATEX_DIR / "katex.min.css"
    js = KATEX_DIR / "katex.min.js"
    auto = KATEX_DIR / "contrib" / "auto-render.min.js"
    missing = [p.name for p in (css, js, auto) if not p.is_file()]
    if missing:
        return "", {"katex": False, "note": f"offline KaTeX assets missing ({missing}); formulas shown as raw text"}
    try:
        head = (
            "<style>" + css.read_text(encoding="utf-8") + "</style>"
            "<script>" + js.read_text(encoding="utf-8") + "</script>"
            "<script>" + auto.read_text(encoding="utf-8") + "</script>"
            "<script>document.addEventListener('DOMContentLoaded',function(){"
            "try{renderMathInElement(document.body,{delimiters:["
            "{left:'$$',right:'$$',display:true},"
            "{left:'\\\\[',right:'\\\\]',display:true},"
            "{left:'\\\\(',right:'\\\\)',display:false}"
            "],throwOnError:false});}catch(e){}});</script>"
        )
        return head, {"katex": True, "note": "inlined vendor/katex (system-font fallback)"}
    except OSError as e:
        return "", {"katex": False, "note": f"failed to inline KaTeX: {e}"}


def _playwright_ready() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _make_contact_sheet(out_dir: Path, screenshot_paths: list[Path]) -> Path:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    thumbs = []
    for path in screenshot_paths:
        with Image.open(path) as img:
            thumb = img.convert("RGB")
            thumb.thumbnail((520, 720))
            canvas = Image.new("RGB", (560, thumb.height + 52), "white")
            canvas.paste(thumb, ((560 - thumb.width) // 2, 12))
            ImageDraw.Draw(canvas).text((16, thumb.height + 24), path.name, fill=(30, 30, 30))
            thumbs.append(canvas)
    height = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (len(thumbs) * 580 - 20, height), "white")
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, (idx * 580, 0))
    target = out_dir / "contact_sheet.png"
    sheet.save(target)
    return target


def _capture_screenshots(out_dir: Path) -> tuple[list[str], str, list[str]]:
    if not _playwright_ready():
        return [], "", ["playwright unavailable; screenshots/contact sheet skipped"]
    try:
        from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as e:
        return [], "", [f"playwright import failed; screenshots/contact sheet skipped: {e}"]

    html_file = (out_dir / "rendered.html").resolve().as_uri()
    viewports = [("desktop", 1280, 1600), ("mobile", 390, 1200)]
    screenshots: list[Path] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for label, width, height in viewports:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(html_file, wait_until="networkidle")
                    target = out_dir / f"screenshot_{label}.png"
                    page.screenshot(path=str(target), full_page=True)
                    screenshots.append(target)
                    page.close()
            finally:
                browser.close()
    except (ImportError, OSError, PlaywrightError) as e:
        return [], "", [f"playwright screenshot failed; screenshots/contact sheet skipped: {e}"]
    rels = [f"review/visual_acceptance/{p.name}" for p in screenshots]
    # Contact sheet is a separate (PIL) step: if it fails, keep the screenshots we
    # already captured rather than discarding valid review artifacts, and attribute
    # the failure to the contact sheet (not playwright).
    try:
        contact = _make_contact_sheet(out_dir, screenshots)
    except (OSError, ValueError) as e:
        return rels, "", [f"contact sheet failed; screenshots kept: {e}"]
    return rels, f"review/visual_acceptance/{contact.name}", []


def write_preview(job_root: Path) -> dict:
    files = _markdown_files(job_root)
    if not files:
        raise FileNotFoundError("output/main.md or output/parts/*.md missing")
    out_dir = job_root / P.REVIEW_VISUAL
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = _combined_markdown(job_root, files)
    body, pandoc_ok, renderer = render_markdown(markdown)
    katex_head, formula_render = ("", {"katex": False, "note": "no math in output"})
    if _MATH_RE.search(markdown):
        katex_head, formula_render = _katex_head()
    page = "\n".join([
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><base href=\"../../output/\">",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.55;max-width:960px;margin:32px auto;padding:0 24px} table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:4px 8px} img{max-width:100%}</style>",
        katex_head,
        "</head><body>",
        body,
        "</body></html>",
    ])
    (out_dir / "rendered.html").write_text(page, encoding="utf-8")
    anchor_map = build_anchor_map(job_root, files)
    (out_dir / "anchor_map.json").write_text(json.dumps(anchor_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    warnings = []
    if not pandoc_ok:
        warnings.append(renderer)
    screenshots, contact_sheet, screenshot_warnings = _capture_screenshots(out_dir)
    warnings.extend(screenshot_warnings)
    source_comparisons = VC.generate_source_comparisons(job_root, anchor_map, screenshots)
    warnings.extend(source_comparisons.get("warnings") or [])
    diagnostics = {
        "schema_version": "agent-friendly-md-render-diagnostics/0.1",
        "created_at": js.now_iso(),
        "status": "pass_with_notes" if warnings else "pass",
        "renderer": renderer,
        # Explicit signal for the gate: did the *real* renderer run, or did we
        # fall back to an escaped <pre> blob? A fallback must never count as
        # visual acceptance (PLAN §14) — the gate reads this, not the label.
        "renderer_ok": pandoc_ok,
        "markdown_files": [p.relative_to(job_root).as_posix() for p in files],
        "html": "review/visual_acceptance/rendered.html",
        "anchor_map": "review/visual_acceptance/anchor_map.json",
        "screenshots": screenshots,
        "contact_sheet": contact_sheet,
        "source_comparisons": source_comparisons,
        "formula_render": formula_render,
        "warnings": warnings,
    }
    (out_dir / "render_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return diagnostics


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render Agent Markdown preview HTML")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        diagnostics = write_preview(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] preview render failed: {e}", file=sys.stderr)
        return 1
    print(f"[ok] rendered preview ({diagnostics['status']}): review/visual_acceptance/rendered.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
