"""Portability helpers for shipped package artifacts."""
from __future__ import annotations

from pathlib import Path

LOCAL_PATH_PATTERNS = (
    "/Users/",
    "/private/tmp/",
    "/tmp/",
    "C:\\",
    "GoogleDrive",
    "CloudStorage",
    "Downloads",
    "Desktop",
)

TEXT_SUFFIXES = {
    "",
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def scan_path_leaks(root: Path, rels: list[str] | set[str] | tuple[str, ...] | None = None) -> list[str]:
    """Return compact leak descriptions for text files under root."""
    paths: list[Path]
    if rels is None:
        paths = sorted(p for p in root.rglob("*") if p.is_file())
    else:
        paths = sorted(root / rel for rel in rels)

    leaks: list[str] = []
    for path in paths:
        if not path.is_file() or not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            leaks.append(f"{_rel(root, path)}:unreadable:{e}")
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern in LOCAL_PATH_PATTERNS:
                if pattern in line:
                    leaks.append(f"{_rel(root, path)}:{line_no}:{pattern}")
                    break
            if len(leaks) >= 20:
                return leaks
    return leaks


def default_replacements(job_root: Path, project_root: Path) -> dict[str, str]:
    replacements = {
        str(job_root): "<job-root>",
        str(job_root.resolve()): "<job-root>",
        str(project_root): "<project-root>",
        str(project_root.resolve()): "<project-root>",
    }
    for path, token in ((job_root, "<job-root>"), (project_root, "<project-root>")):
        resolved = str(path.resolve())
        if resolved.startswith("/private/"):
            replacements[resolved.removeprefix("/private")] = token
    return {k: v for k, v in replacements.items() if k}


def rewrite_text_paths(root: Path, replacements: dict[str, str]) -> None:
    for path in sorted(p for p in root.rglob("*") if p.is_file() and is_text_file(p)):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        new_text = text
        for old, new in replacements.items():
            new_text = new_text.replace(old, new)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


def sanitize_text(text: str, replacements: dict[str, str]) -> str:
    out = text
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
