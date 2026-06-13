"""subprocess helpers with portable UTF-8 text I/O.

Tool stdin/stdout/stderr is Chinese-bearing (and uses "—"). A bare
``subprocess.run(..., text=True)`` encodes/decodes with the *locale* codec —
ASCII under ``LC_ALL=C``, a legacy code page on Windows — so the first non-ASCII
byte raises ``UnicodeDecodeError``/``UnicodeEncodeError`` and kills the tool
mid-run. Every in-repo subprocess that exchanges text routes through here, so
the codec is pinned once instead of being re-specified (or forgotten) per call
site. See also ``scripts/run_python.py`` which forces UTF-8 on the wrapper's own
stdout/stderr for the same reason.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any


def force_utf8_stdio() -> None:
    """Emit UTF-8 on this process's stdout/stderr regardless of console locale.

    ``lib/__init__`` calls this on import, so a tool/validator run **directly**
    (``python3 tools/x.py``) — not just through ``scripts/run_python.py`` — also
    survives a non-UTF-8 console (Windows code page / ``LC_ALL=C`` with UTF-8 mode
    off), where a bare ``print`` of "—"/Chinese would otherwise raise
    ``UnicodeEncodeError`` mid-run. The wrapper keeps its own copy so it is robust
    without importing lib. Idempotent; a no-op on streams without ``reconfigure``.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # pragma: no cover - exotic streams
                pass


def run_text(cmd: Any, **kwargs: Any) -> "subprocess.CompletedProcess[str]":
    """``subprocess.run`` defaulting to UTF-8 text I/O.

    Callers keep passing ``capture_output``/``input``/``timeout`` as usual; this
    only fills in ``text=True`` and ``encoding="utf-8"`` when unset.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    return subprocess.run(cmd, **kwargs)
