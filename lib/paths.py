"""Job-bundle directory layout — the canonical skeleton (PLAN §4).

``init_document_job.py`` creates exactly these directories; validators check
against the same list so "what a bundle looks like" is defined once.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Relative directories that make up a job bundle. Order is creation order.
JOB_DIRS: list[str] = [
    "source",
    "extracted",
    "extracted/text",
    "extracted/pages",
    "extracted/images",
    "extracted/tables",
    "extracted/comments",
    "extracted/attachments",
    "ir",
    "review",
    "review/visual_acceptance",
    "review/visual_acceptance/source_comparisons",
    "output",
    "output/parts",
    "output/assets",
    "logs",
    "logs/gates",
    "logs/hashes",
]

# Files an empty (pre-data) bundle carries so downstream stages can append.
JOB_SEED_FILES: dict[str, str] = {
    "review/issues.jsonl": "",
    "review/unresolved.md": "# Unresolved\n\n_No unresolved issues._\n",
}

# Canonical bundle file/dir locations — single source so tools that read/write
# them never desync on a typo (the §3 mapping contract).
EXTRACTED_TEXT = "extracted/text"
EXTRACTED_IMAGES = "extracted/images"
EXTRACTED_PAGES = "extracted/pages"
EXTRACT_META = "extracted/extract_meta.json"
EXTRACT_ELEMENTS = "extracted/elements.jsonl"
EXTRACT_PDF_TEXT_BLOCKS = "extracted/pdf_text_blocks.jsonl"
REVIEW_VISION_CACHE = "review/vision_cache.json"
REVIEW_CLEANING = "review/cleaning_decisions.json"
REVIEW_QUALITY_REPORT = "review/imported_quality_report.md"
REVIEW_ISSUES = "review/issues.jsonl"
REVIEW_UNRESOLVED = "review/unresolved.md"
REVIEW_VISUAL = "review/visual_acceptance"
REVIEW_SOURCE_COMPARISONS = "review/visual_acceptance/source_comparisons"
REVIEW_AUDIT_SUMMARY = "review/audit_summary.json"
REVIEW_EXTRACTION_SECURITY_AUDIT_JSON = "review/extraction_security_audit.json"
REVIEW_EXTRACTION_SECURITY_AUDIT_MD = "review/extraction_security_audit.md"
REVIEW_EVIDENCE_MANIFEST = "review/visual_acceptance/evidence_manifest.json"
IR_SUMMARY_SEED = "ir/summary.seed.md"
OUTPUT_MAIN = "output/main.md"
OUTPUT_PARTS = "output/parts"
OUTPUT_ASSETS = "output/assets"
OUTPUT_QA_REPORT = "output/qa_report.md"
OUTPUT_VISUAL_ACCEPTANCE = "output/visual_acceptance.md"
OUTPUT_UNRESOLVED = "output/unresolved.md"


def job_path(job_root: str | Path, *parts: str) -> Path:
    """Resolve a path inside a job bundle."""
    return Path(job_root).joinpath(*parts)


def ensure_skeleton(job_root: str | Path) -> Path:
    """Create the full directory skeleton + seed files under ``job_root``."""
    root = Path(job_root)
    for d in JOB_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    for f, seed in JOB_SEED_FILES.items():
        p = root / f
        if not p.exists():
            p.write_text(seed, encoding="utf-8")
    return root
