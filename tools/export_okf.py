#!/usr/bin/env python3
"""Export a package-gate-passed job as an OKF-style concept bundle.

This is intentionally a downstream export. It reads the final agent-md outputs
after the package gate passes, then writes a separate markdown concept bundle.
It never replaces the `_agent-md/` support directory or its QA/provenance files.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import subproc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"
OKF_EXPORT_SCHEMA = "agent-friendly-md-okf-export/0.1"


def _run_package_gate(job_root: Path) -> int:
    result = subproc.run_text(
        [sys.executable, str(WRAPPER), "validators/package_gate.py", "--job", str(job_root)],
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(text: str, fallback: str) -> str:
    keep = []
    for ch in text.lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in (" ", "-", "_", "."):
            keep.append("-")
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or fallback


def _default_out(job_root: Path, package_dir: Path | None) -> Path:
    if package_dir is not None:
        return package_dir.parent / f"{package_dir.name}-okf"
    return job_root.parent / f"{job_root.name}-okf"


def _package_from_state(job_root: Path) -> Path | None:
    try:
        state = js.load_state(job_root)
    except (OSError, json.JSONDecodeError):
        return None
    package_path = ((state.get("package") or {}).get("path") or "")
    if not package_path:
        return None
    path = Path(package_path).expanduser()
    return path if path.is_dir() else None


def _layout(job_root: Path, package_dir: Path | None) -> dict:
    index = _load_json(job_root / "output/index.json")
    manifest = _load_json(job_root / "output/manifest.json")
    title = str(index.get("title") or manifest.get("document_slug") or job_root.name)
    if package_dir is not None:
        support = package_dir / "_agent-md"
        metadata = _load_json(support / "package_metadata.json")
        required = {
            "main": package_dir / metadata["main"],
            "manifest": support / "manifest.json",
            "provenance": support / "provenance.json",
            "qa_report": support / "qa_report.md",
            "visual_acceptance": support / "visual_acceptance.md",
            "index": support / "index.md",
            "index_json": support / "index.json",
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"package is missing required agent-md file(s): {missing}")
        base = package_dir
    else:
        required = {
            "main": job_root / P.OUTPUT_MAIN,
            "manifest": job_root / "output/manifest.json",
            "provenance": job_root / "output/provenance.json",
            "qa_report": job_root / P.OUTPUT_QA_REPORT,
            "visual_acceptance": job_root / P.OUTPUT_VISUAL_ACCEPTANCE,
            "index": job_root / "output/index.md",
            "index_json": job_root / "output/index.json",
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"job output is missing required file(s): {missing}")
        base = job_root / "output"
    parts = []
    for i, part in enumerate(index.get("parts") or [], start=1):
        rel = str(part.get("path") or "")
        if not rel:
            continue
        parts.append({
            "title": str(part.get("title") or f"Part {i}"),
            "path": base / rel,
            "source_range": str(part.get("source_range") or ""),
        })
    return {"title": title, "manifest": manifest, "required": required, "parts": parts}


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_value(v) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _rel_link(from_file: Path, target: Path) -> str:
    return Path(os.path.relpath(target, from_file.parent)).as_posix()


def _md_link(label: str, from_file: Path, target: Path) -> str:
    rel = _rel_link(from_file, target)
    return f"[{label}](<{rel}>)"


def _concept_frontmatter(
    *,
    title: str,
    description: str,
    resource: str,
    timestamp: str,
    job_id: str,
    tags: list[str],
    extras: dict[str, Any] | None = None,
) -> str:
    fields: dict[str, Any] = {
        "type": "Reference",
        "title": title,
        "description": description,
        "resource": resource,
        "tags": tags,
        "timestamp": timestamp,
        "okf_export_schema": OKF_EXPORT_SCHEMA,
        "afmd_job_id": job_id,
        "afmd_package_gate": "passed",
    }
    if extras:
        fields.update(extras)
    return _frontmatter(fields)


def _write_bundle(job_root: Path, package_dir: Path | None, out: Path) -> None:
    layout = _layout(job_root, package_dir)
    manifest = layout["manifest"]
    job_id = str(manifest.get("job_id") or job_root.name)
    timestamp = js.now_iso()
    title = layout["title"]
    required = layout["required"]

    out.mkdir(parents=True)
    document = out / "document.md"
    rel_main = _rel_link(document, required["main"])
    document.write_text(
        _concept_frontmatter(
            title=title,
            description=f"Agent-friendly Markdown package export for {title}.",
            resource=rel_main,
            timestamp=timestamp,
            job_id=job_id,
            tags=["agent-friendly-md", "document"],
            extras={
                "afmd_manifest": _rel_link(document, required["manifest"]),
                "afmd_provenance": _rel_link(document, required["provenance"]),
                "afmd_qa_report": _rel_link(document, required["qa_report"]),
                "afmd_visual_acceptance": _rel_link(document, required["visual_acceptance"]),
            },
        )
        + f"# {title}\n\n"
        + f"- Document: {_md_link('main markdown', document, required['main'])}\n"
        + f"- Agent index: {_md_link('index', document, required['index'])}\n"
        + f"- QA report: {_md_link('qa report', document, required['qa_report'])}\n"
        + f"- Visual acceptance: {_md_link('visual acceptance', document, required['visual_acceptance'])}\n\n"
        + "# Citations\n\n"
        + f"[1] {_md_link('agent-md manifest', document, required['manifest'])}\n"
        + f"[2] {_md_link('block-level provenance', document, required['provenance'])}\n",
        encoding="utf-8",
    )

    part_entries = []
    parts_dir = out / "parts"
    if layout["parts"]:
        parts_dir.mkdir()
    for i, part in enumerate(layout["parts"], start=1):
        filename = f"{i:02d}-{_slug(part['title'], f'part-{i}')}.md"
        path = parts_dir / filename
        rel_part = _rel_link(path, part["path"])
        path.write_text(
            _concept_frontmatter(
                title=part["title"],
                description=f"Part of {title}.",
                resource=rel_part,
                timestamp=timestamp,
                job_id=job_id,
                tags=["agent-friendly-md", "document-part"],
                extras={"afmd_source_range": part["source_range"]},
            )
            + f"# {part['title']}\n\n"
            + f"- Part markdown: {_md_link('source part', path, part['path'])}\n"
            + f"- Parent document: [document](/document.md)\n",
            encoding="utf-8",
        )
        part_entries.append((part["title"], f"parts/{filename}"))

    index_lines = [
        "# OKF Export Index",
        "",
        f"* [Document](document.md) - {title}",
    ]
    if part_entries:
        index_lines.extend(["", "# Parts", ""])
        for part_title, rel in part_entries:
            index_lines.append(f"* [{part_title}]({rel}) - Part concept")
    (out / "index.md").write_text("\n".join(index_lines).rstrip() + "\n", encoding="utf-8")
    (out / "log.md").write_text(
        f"# Directory Update Log\n\n## {timestamp[:10]}\n"
        f"* **Creation**: Exported from package-gate-passed agent-friendly-md job `{job_id}`.\n",
        encoding="utf-8",
    )


def _replace_target(tmp: Path, target: Path, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"OKF export target exists (use --force): {target}")
    backup = target.parent / f".{target.name}.bak-{uuid.uuid4().hex}"
    had_target = target.exists()
    if had_target:
        target.rename(backup)
    try:
        tmp.rename(target)
    except OSError:
        if had_target:
            backup.rename(target)
        raise
    if had_target:
        shutil.rmtree(backup)


def export_okf(job_root: Path, package_dir: Path | None, out: Path, force: bool) -> Path:
    tmp = out.parent / f".{out.name}.tmp-{uuid.uuid4().hex}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        _write_bundle(job_root, package_dir, tmp)
        _replace_target(tmp, out, force)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Export a passed agent-md package as an OKF-style bundle.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--package", default=None, help="Optional final package directory. Defaults to STATE package path.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    package_dir = Path(args.package).expanduser().resolve() if args.package else _package_from_state(job_root)
    out = Path(args.out).expanduser().resolve() if args.out else _default_out(job_root, package_dir)
    if _run_package_gate(job_root) != 0:
        print("[error] package gate failed; not exporting OKF.", file=sys.stderr)
        return 1
    try:
        target = export_okf(job_root, package_dir, out, args.force)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[error] OKF export failed: {e}", file=sys.stderr)
        return 1
    print(f"[ok] OKF-style export written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
