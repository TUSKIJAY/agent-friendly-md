#!/usr/bin/env python3
"""Project entry-point wrapper.

Run every tool/validator through this, from the project root, with a
project-relative target path::

    python3 scripts/run_python.py tools/init_document_job.py --source "<file>"
    python3 scripts/run_python.py validators/validate_state.py --job "<job-dir>"

What it does:
- resolves the target relative to the project root (refuses targets that escape
  the project, so callers never pass parent-directory paths — PLAN §8);
- puts the project root on ``sys.path`` so tools can ``import lib...``;
- executes the target in-process under ``__main__`` so a single interpreter
  (and, if present, the project ``.venv``) is used, propagating its exit code.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path, PurePath

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _force_utf8_stdio() -> None:
    """Emit UTF-8 on stdout/stderr regardless of the console's locale.

    Tool output is Chinese-bearing (and uses "—"). On a non-UTF-8 console —
    Windows' default code page, or an ``LC_ALL=C`` shell with UTF-8 mode off — a
    bare ``print`` of a non-ASCII char raises ``UnicodeEncodeError`` and kills the
    process mid-run. This guards the wrapper's own early prints (usage/refusal);
    tools invoked DIRECTLY (``python3 tools/x.py``) are covered by the same
    reconfigure in ``lib/__init__`` (``lib.subproc.force_utf8_stdio``), which they
    all hit via ``from lib import ...``. Kept standalone so the wrapper needs no
    project imports.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # pragma: no cover - exotic streams
                pass


def is_within_root(root: PurePath, target: PurePath) -> bool:
    """True when ``target`` is ``root`` itself or nested inside it.

    Uses ``relative_to`` (component-wise) rather than a ``str.startswith(root +
    "/")`` test: the literal "/" is wrong on Windows, where paths join with "\\",
    so the old check refused *every* in-repo target and the pipeline was dead on
    Windows. ``relative_to`` is separator-agnostic and still refuses a sibling
    like ``<root>-evil`` (component "agent-friendly-md-evil" != "agent-friendly-md").
    Callers pass already-resolved paths so ``..`` is collapsed before the check.
    """
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def main(argv: list[str]) -> int:
    _force_utf8_stdio()
    if len(argv) < 2:
        print(
            "usage: run_python.py <tools|validators>/<name>.py [args...]",
            file=sys.stderr,
        )
        return 2

    target = (PROJECT_ROOT / argv[1]).resolve()
    root_str = str(PROJECT_ROOT)
    if not is_within_root(PROJECT_ROOT, target):
        print(f"refusing target outside project root: {argv[1]}", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"target not found: {argv[1]}", file=sys.stderr)
        return 2

    sys.path.insert(0, root_str)
    sys.argv = [str(target), *argv[2:]]
    runpy.run_path(str(target), run_name="__main__")
    return 0  # reached only if target did not raise SystemExit


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
