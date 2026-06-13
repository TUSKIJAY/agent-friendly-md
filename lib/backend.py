"""Locate the doc-to-agent-markdown extraction backend (v0.2).

The backend is reused as the Phase 1 extractor/assembler (see
docs/migration-from-skill.md). Its location is resolved in priority order:

1. an explicit ``--backend`` CLI override,
2. the ``AFM_BACKEND_DIR`` environment variable,
3. ``DEFAULT_BACKEND`` below — the vendored snapshot shipped in this repo.

A repo-relative default means a fresh clone runs Phase 1 with no flags and no
external checkout; #1/#2 still let you point at a newer working copy.
"""
from __future__ import annotations

import os
from pathlib import Path

from .paths import PROJECT_ROOT

DEFAULT_BACKEND = PROJECT_ROOT / "vendor" / "doc-to-agent-markdown"


def backend_dir(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("AFM_BACKEND_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_BACKEND


def extractor_path(override: str | None = None) -> Path:
    return backend_dir(override) / "doc_to_md_extractor.py"


def assembler_path(override: str | None = None) -> Path:
    return backend_dir(override) / "doc_to_md_assembler.py"


def check_available(override: str | None = None) -> tuple[bool, str]:
    d = backend_dir(override)
    if not d.is_dir():
        return False, f"backend dir not found: {d}"
    if not extractor_path(override).is_file():
        return False, f"extractor not found: {extractor_path(override)}"
    if not assembler_path(override).is_file():
        return False, f"assembler not found: {assembler_path(override)}"
    return True, str(d)
