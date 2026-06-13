"""Idempotent markdown-report sections (review/semantic_compile.md etc.).

Tools may re-run (the role doc mandates re-running semanticize_figures after the
vision pass), so report writing must replace a tool's section rather than append
a duplicate.
"""
from __future__ import annotations

import re
from pathlib import Path


def upsert_section(report_path: str | Path, doc_title: str, section: str, body: str) -> None:
    """Insert/replace a `## <section>` block under a `# <doc_title>` report."""
    path = Path(report_path)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not existing.strip():
        existing = f"# {doc_title}\n\n"
    # drop any existing block for this section (from its heading to the next ## or EOF)
    pattern = re.compile(rf"^## {re.escape(section)}\n.*?(?=^## |\Z)", re.S | re.M)
    existing = pattern.sub("", existing).rstrip() + "\n\n"
    existing += f"## {section}\n\n{body.rstrip()}\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing, encoding="utf-8")
