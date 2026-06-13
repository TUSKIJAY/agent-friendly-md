"""output/manifest.json shape and builders (PLAN §4/§10, review-003 medium 1).

The manifest is tool-generated, never hand-edited:

- Phase 0  ``init_document_job.py`` writes a ``draft`` manifest from the source
  files (slug, per-source bytes + sha256).
- Phase 6/7 it is refreshed to ``final`` from the IR + gate results (outputs,
  split parts, key input hashes).

``logs/hashes/`` holds per-stage input/output hash snapshots (the staleness
basis); ``manifest.json`` holds the final deliverable hashes (review-003 minor 4).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .jobstate import now_iso


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

MANIFEST_SCHEMA_VERSION = "agent-friendly-md-manifest/0.1"
STAGES = ("draft", "final")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def source_entry(job_root: str | Path, rel_path: str) -> dict:
    p = Path(job_root) / rel_path
    st = p.stat()
    return {
        "path": rel_path,
        "bytes": st.st_size,
        "sha256": sha256_file(p),
        "mtime": _iso_from_epoch(st.st_mtime),  # the source file's mtime, not "now"
    }


def new_draft(
    *,
    job_id: str,
    document_slug: str,
    sources: list[dict],
    split_thresholds: dict,
) -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "job_id": job_id,
        "document_slug": document_slug,
        "stage": "draft",
        "generated_at": now_iso(),
        "sources": sources,
        "outputs": {"main": None, "parts": [], "assets": []},
        "split": {"enabled": False, "thresholds": dict(split_thresholds), "parts": []},
        "input_hashes": {},
        "stats": {},
    }
