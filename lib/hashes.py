"""Per-phase hash snapshots and stale-input detection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import jobstate as js
from . import manifest as mf

HASH_SCHEMA_VERSION = "agent-friendly-md-hashes/0.1"

PHASE_PATTERNS: dict[str, dict[str, list[str]]] = {
    "0_intake": {
        "inputs": ["source/**"],
        "outputs": ["STATE.json", "output/manifest.json", "review/issues.jsonl", "review/unresolved.md"],
    },
    "1_extraction": {
        "inputs": ["STATE.json", "source/**"],
        "outputs": ["extracted/**", "review/imported_quality_report.md",
                    "review/vision_cache.json", "review/cleaning_decisions.json", "ir/summary.seed.md"],
    },
    "2_ir_build": {
        "inputs": ["extracted/**", "review/imported_quality_report.md"],
        "outputs": ["ir/document.ir.json", "ir/blocks.jsonl", "ir/assets.index.json", "ir/provenance.json"],
    },
    "3_semantic_compile": {
        "inputs": ["ir/**", "review/vision_cache.json", "review/cleaning_decisions.json"],
        "outputs": ["ir/**", "review/semantic_compile.md"],
    },
    "4_audit": {
        "inputs": ["ir/**", "review/issues.jsonl", "review/unresolved.md"],
        "outputs": ["ir/**", "review/audit_summary.json", "review/issues.jsonl", "review/unresolved.md"],
    },
    "5_assembly": {
        "inputs": ["ir/**", "review/unresolved.md"],
        "outputs": ["output/main.md", "output/index.md", "output/index.json",
                    "output/parts/**", "output/assets/**",
                    "output/provenance.json", "output/manifest.json"],
    },
    "6_validation": {
        "inputs": ["output/main.md", "output/index.md", "output/index.json",
                   "output/parts/**", "output/assets/**", "output/provenance.json",
                   "review/visual_acceptance/**", "review/issues.jsonl", "review/unresolved.md",
                   "logs/gates/gate_0_intake_*.json", "logs/gates/gate_1_extraction_*.json",
                   "logs/gates/gate_2_ir_build_*.json", "logs/gates/gate_3_semantic_compile_*.json",
                   "logs/gates/gate_4_audit_*.json", "logs/gates/gate_5_assembly_*.json"],
        "outputs": ["output/qa_report.md", "output/visual_acceptance.md",
                    "output/unresolved.md", "output/manifest.json"],
    },
    "7_package": {
        "inputs": ["output/main.md", "output/index.md", "output/index.json",
                   "output/parts/**", "output/assets/**",
                   "output/provenance.json", "output/qa_report.md",
                   "output/visual_acceptance.md", "output/unresolved.md"],
        "outputs": [],
    },
}


def snapshot_file(job_root: str | Path, phase: str) -> Path:
    return Path(job_root) / "logs" / "hashes" / f"{phase}.json"


def _matching_files(root: Path, patterns: list[str]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        if pattern.endswith("/**"):
            base = root / pattern[:-3]
            if base.is_dir():
                files.update(p for p in base.rglob("*") if p.is_file())
            continue
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def collect_hashes(job_root: str | Path, patterns: list[str]) -> dict[str, dict]:
    root = Path(job_root)
    out: dict[str, dict] = {}
    for path in _matching_files(root, patterns):
        rel = path.relative_to(root).as_posix()
        out[rel] = {"sha256": mf.sha256_file(path), "bytes": path.stat().st_size}
    return out


def aggregate_hash(entries: dict[str, dict]) -> str:
    h = hashlib.sha256()
    for rel, meta in sorted(entries.items()):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(meta.get("bytes", "")).encode("ascii"))
        h.update(b"\0")
        h.update(str(meta.get("sha256", "")).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def phase_hashes(job_root: str | Path, phase: str, kind: str) -> dict[str, dict]:
    if phase not in PHASE_PATTERNS:
        raise ValueError(f"unknown phase: {phase}")
    if kind not in ("inputs", "outputs"):
        raise ValueError(f"unknown hash kind: {kind}")
    return collect_hashes(job_root, PHASE_PATTERNS[phase][kind])


def load_snapshot(job_root: str | Path, phase: str) -> dict | None:
    path = snapshot_file(job_root, phase)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def stale_diff(job_root: str | Path, phase: str) -> dict | None:
    previous = load_snapshot(job_root, phase)
    if previous is None:
        return None
    old = previous.get("inputs") or {}
    new = phase_hashes(job_root, phase, "inputs")
    if old == new:
        return None
    old_keys, new_keys = set(old), set(new)
    changed = sorted(k for k in old_keys & new_keys if old[k] != new[k])
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "changed": changed,
        "previous_digest": aggregate_hash(old),
        "current_digest": aggregate_hash(new),
    }


def _update_manifest_input_hash(job_root: Path, phase: str, inputs: dict[str, dict]) -> None:
    path = job_root / "output" / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("input_hashes", {})[phase] = aggregate_hash(inputs)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_snapshot(job_root: str | Path, phase: str) -> dict:
    root = Path(job_root)
    if phase not in js.PHASES:
        raise ValueError(f"unknown phase: {phase}")
    inputs = phase_hashes(root, phase, "inputs")
    _update_manifest_input_hash(root, phase, inputs)
    outputs = phase_hashes(root, phase, "outputs")
    data = {
        "schema_version": HASH_SCHEMA_VERSION,
        "phase": phase,
        "created_at": js.now_iso(),
        "input_digest": aggregate_hash(inputs),
        "output_digest": aggregate_hash(outputs),
        "inputs": inputs,
        "outputs": outputs,
    }
    path = snapshot_file(root, phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data
