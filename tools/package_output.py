#!/usr/bin/env python3
"""Phase 7: build the final agent-md package directory."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import portability  # noqa: E402
from lib import subproc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"
PACKAGE_FILES = [
    "main.md",
    "index.md",
    "index.json",
    "manifest.json",
    "provenance.json",
    "qa_report.md",
    "visual_acceptance.md",
    "unresolved.md",
]
SUPPORT_DIR = "_agent-md"
SUPPORT_FILES = [
    "index.md",
    "index.json",
    "manifest.json",
    "provenance.json",
    "qa_report.md",
    "visual_acceptance.md",
    "unresolved.md",
]
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


def _safe_name_component(name: str, fallback: str) -> str:
    cleaned = "".join(
        "_" if ch in INVALID_FILENAME_CHARS or ord(ch) < 32 else ch
        for ch in name
    ).strip().strip(".")
    return cleaned or fallback


def _primary_source_stem(job_root: Path, manifest: dict | None = None) -> str:
    sources = (manifest or {}).get("sources") or []
    source_rel = ""
    if sources and isinstance(sources[0], dict):
        source_rel = str(sources[0].get("path") or "")
    if not source_rel:
        try:
            state = js.load_state(job_root)
            source_rel = str((state.get("source_files") or [""])[0])
        except (OSError, json.JSONDecodeError):
            source_rel = ""
    fallback = str((manifest or {}).get("document_slug") or job_root.name)
    stem = PureWindowsPath(source_rel).stem if source_rel else fallback
    return _safe_name_component(stem, _safe_name_component(fallback, "document"))


def _default_out(job_root: Path, source_stem: str) -> Path:
    if job_root.parent.name == "jobs" and job_root.parent.parent.name == ".agent-friendly-md":
        return job_root.parent.parent.parent / f"{source_stem}-agent-md"
    return job_root.parent / f"{source_stem}-agent-md"


def _run_gate(job_root: Path) -> int:
    result = subproc.run_text(
        [sys.executable, str(WRAPPER), "validators/package_gate.py", "--job", str(job_root)],
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _copy_dir(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)


def _preflight(job_root: Path) -> None:
    missing = [name for name in PACKAGE_FILES if not (job_root / "output" / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing package output file(s): {missing}")


def _copy_payload(job_root: Path, target: Path, source_stem: str, include_work: bool) -> str:
    target.mkdir(parents=True)
    final_main = f"{source_stem}.md"
    shutil.copy2(job_root / "output" / "main.md", target / final_main)
    _copy_dir(job_root / P.OUTPUT_PARTS, target / "parts")
    _copy_dir(job_root / P.OUTPUT_ASSETS, target / "assets")
    support = target / SUPPORT_DIR
    support.mkdir()
    for name in SUPPORT_FILES:
        shutil.copy2(job_root / "output" / name, support / name)
    if include_work:
        work = support / "work"
        work.mkdir()
        for rel in ("extracted", "ir", "review", "logs"):
            _copy_dir(job_root / rel, work / rel)
    return final_main


def _write_package_metadata(job_root: Path, target: Path, final_main: str, include_work: bool) -> None:
    files = {}
    metadata_path = target / SUPPORT_DIR / "package_metadata.json"
    for path in sorted(p for p in target.rglob("*") if p.is_file() and p != metadata_path):
        rel = path.relative_to(target).as_posix()
        files[rel] = {"sha256": mf.sha256_file(path), "bytes": path.stat().st_size}
    data = {
        "schema_version": "agent-friendly-md-package/0.1",
        "created_at": js.now_iso(),
        # M5: ship the bundle name only — never the author's absolute job path.
        # The full job id is already carried in the packaged manifest.json.
        "source_job": job_root.name,
        "main": final_main,
        "index": f"{SUPPORT_DIR}/index.md",
        "index_json": f"{SUPPORT_DIR}/index.json",
        "support_dir": SUPPORT_DIR,
        "include_work": include_work,
        "files": files,
    }
    metadata_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


def _rewrite_package_index(target: Path, final_main: str) -> None:
    support = target / SUPPORT_DIR
    md_path = support / "index.md"
    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        text = text.replace("[main.md](main.md)", f"[{final_main}](../{final_main})")
        text = text.replace("(main.md)", f"(../{final_main})")
        text = text.replace("](parts/", "](../parts/")
        md_path.write_text(text, encoding="utf-8")

    json_path = support / "index.json"
    if json_path.is_file():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        entry = data.setdefault("entry", {})
        entry["path"] = f"../{final_main}"
        entry["package_path"] = f"../{final_main}"
        for part in data.get("parts") or []:
            path = str(part.get("path") or "")
            if path.startswith("parts/"):
                part["path"] = f"../{path}"
                part["package_path"] = f"../{path}"
        data.setdefault("package", {})
        data["package"].update({
            "main": f"../{final_main}",
            "support_dir": ".",
            "parts_prefix": "../parts",
            "assets_prefix": "../assets",
        })
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sanitize_and_check_package(job_root: Path, target: Path) -> None:
    portability.rewrite_text_paths(
        target,
        portability.default_replacements(job_root, PROJECT_ROOT),
    )
    leaks = portability.scan_path_leaks(target)
    if leaks:
        raise ValueError(f"local path leak(s) in package: {leaks[:5]}")


def _replace_target(tmp: Path, target: Path, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"package target exists (use --force): {target}")
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


def _mark_done(job_root: Path, target: Path) -> None:
    state = js.load_state(job_root)
    state.setdefault("package", {})
    state["package"].update({"path": str(target), "created_at": js.now_iso()})
    state["current_phase"] = "7_package"
    state["phase_status"]["7_package"] = "done"
    js.save_state(job_root, state)


def build_package(job_root: Path, out: Path | None, include_work: bool, force: bool) -> Path:
    _preflight(job_root)
    manifest = json.loads((job_root / "output/manifest.json").read_text(encoding="utf-8"))
    source_stem = _primary_source_stem(job_root, manifest)
    target = out or _default_out(job_root, source_stem)
    if target.exists() and not force:
        raise FileExistsError(f"package target exists (use --force): {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        final_main = _copy_payload(job_root, tmp, source_stem, include_work)
        _rewrite_package_index(tmp, final_main)
        _write_package_metadata(job_root, tmp, final_main, include_work)
        _sanitize_and_check_package(job_root, tmp)
        _replace_target(tmp, target, force)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    _mark_done(job_root, target)
    return target


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Create final package directory from output/.")
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--include-work", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    if _run_gate(job_root) != 0:
        print("[error] package gate failed; not packaging.", file=sys.stderr)
        return 1
    try:
        target = build_package(
            job_root,
            Path(args.out).expanduser().resolve() if args.out else None,
            args.include_work,
            args.force,
        )
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[error] package failed: {e}", file=sys.stderr)
        return 1
    print(f"[ok] package written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
