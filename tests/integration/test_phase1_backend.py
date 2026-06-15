"""End-to-end Phase 0->1 through the doc-to-agent-markdown backend (v0.2).

Skips automatically when the backend checkout or its Python deps are absent, so
the suite stays green on machines without the backend.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

from lib import backend as bk  # noqa: E402


def _deps_ok() -> bool:
    return all(importlib.util.find_spec(m) for m in ("docx", "fitz", "openpyxl", "pptx", "PIL"))


def run(target: str, *args: str):
    return subprocess.run([sys.executable, str(WRAPPER), target, *args],
                          capture_output=True, text=True, encoding="utf-8")


@unittest.skipUnless(bk.check_available()[0] and _deps_ok(), "backend or deps unavailable")
class TestPhase1Backend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "mini.md"
        self.src.write_text(
            "# Title\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nformula $E=mc^2$\n",
            encoding="utf-8",
        )
        self.jobs = self.root / "jobs"

    def tearDown(self):
        self.tmp.cleanup()

    def test_phase0_to_1_pipeline(self):
        steps = [
            ("tools/init_document_job.py", "--source", str(self.src),
             "--jobs-root", str(self.jobs), "--date", "20260612"),
        ]
        r = run(*steps[0])
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"

        for tgt, *a in [
            ("validators/validate_state.py", "--job", str(job)),
            ("validators/validate_manifest.py", "--job", str(job), "--mode", "draft"),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/run_extraction.py", "--job", str(job)),
            ("validators/validate_extraction.py", "--job", str(job)),
            ("tools/assemble_backend_md.py", "--job", str(job)),
        ]:
            r = run(tgt, *a)
            self.assertEqual(r.returncode, 0, f"{tgt} failed: {r.stdout}\n{r.stderr}")

        # §3 mapping slots all landed
        for rel in ["extracted/text", "extracted/extract_meta.json", "extracted/images",
                    "extracted/elements.jsonl",
                    "review/extraction_security_audit.json", "review/extraction_security_audit.md",
                    "review/vision_cache.json", "review/cleaning_decisions.json",
                    "review/imported_quality_report.md", "ir/summary.seed.md", "output/main.md"]:
            self.assertTrue((job / rel).exists(), f"missing §3 slot: {rel}")
        meta = json.loads((job / "extracted/extract_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["extraction_element_schema"], "agent-extraction-elements/0.1")
        self.assertEqual(meta["elements_file"], "extracted/elements.jsonl")
        self.assertGreater(meta["element_count"], 0)
        self.assertIn("routing", meta)
        first_element = json.loads((job / "extracted/elements.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("source_anchor", first_element)
        self.assertIn("evidence_level", first_element)

        # profile confirmed + risk upgraded by table/formula content
        st = json.loads((job / "STATE.json").read_text(encoding="utf-8"))
        prof = st["document_profile"]
        self.assertEqual(prof["profile_status"], "confirmed")
        self.assertEqual(prof["confirmed_by"], "validate_extraction.py")
        self.assertIn(prof["risk_level"], ("medium", "high"))
        # Phase 1 gate result written under the right phase
        self.assertTrue((job / "logs" / "gates" / "gate_1_extraction_validate_extraction.json").is_file())

    def test_extraction_gate_pinned_to_phase1(self):
        # init + Phase 0 gates, but deliberately do NOT advance to Phase 1.
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        run("validators/validate_state.py", "--job", str(job))
        run("validators/validate_manifest.py", "--job", str(job), "--mode", "draft")
        # run the Phase 1 work while current_phase is still 0_intake
        self.assertEqual(run("tools/run_extraction.py", "--job", str(job)).returncode, 0)
        self.assertEqual(run("validators/validate_extraction.py", "--job", str(job)).returncode, 0)
        gates = job / "logs" / "gates"
        self.assertTrue((gates / "gate_1_extraction_validate_extraction.json").is_file(),
                        "extraction gate must file under its owning phase 1_extraction")
        self.assertFalse((gates / "gate_0_intake_validate_extraction.json").is_file(),
                         "extraction gate must NOT file under 0_intake (would subvert no-skip)")

    def test_phase2_ir_pipeline(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        for tgt, *a in [
            ("validators/validate_state.py", "--job", str(job)),
            ("validators/validate_manifest.py", "--job", str(job), "--mode", "draft"),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/run_extraction.py", "--job", str(job)),
            ("validators/validate_extraction.py", "--job", str(job)),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/build_ir.py", "--job", str(job)),
            ("tools/link_assets.py", "--job", str(job)),
            ("validators/validate_ir.py", "--job", str(job)),
            ("validators/validate_provenance.py", "--job", str(job)),
            ("validators/validate_links.py", "--job", str(job), "--mode", "ir"),
        ]:
            r = run(tgt, *a)
            self.assertEqual(r.returncode, 0, f"{tgt} failed: {r.stdout}\n{r.stderr}")

        for rel in ["ir/blocks.jsonl", "ir/document.ir.json",
                    "ir/assets.index.json", "ir/provenance.json"]:
            self.assertTrue((job / rel).is_file(), f"missing IR file: {rel}")
        first_block = json.loads((job / "ir/blocks.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("evidence_level", first_block)
        self.assertIn("extraction_metadata", first_block)
        self.assertTrue((job / "logs" / "gates" / "gate_2_ir_build_validate_ir.json").is_file())

        # corrupting a projection must make validate_ir hard-fail
        prov = job / "ir" / "provenance.json"
        data = json.loads(prov.read_text(encoding="utf-8"))
        data["blocks"]["block_BOGUS_999"] = {"kind": "pdf_page", "page": 1}
        prov.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        r = run("validators/validate_ir.py", "--job", str(job))
        self.assertEqual(r.returncode, 1, "projection mismatch must hard-fail validate_ir")

    def test_phase3_semantic_pipeline(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        chain = [
            ("validators/validate_state.py", "--job", str(job)),
            ("validators/validate_manifest.py", "--job", str(job), "--mode", "draft"),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/run_extraction.py", "--job", str(job)),
            ("validators/validate_extraction.py", "--job", str(job)),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/build_ir.py", "--job", str(job)),
            ("tools/link_assets.py", "--job", str(job)),
            ("validators/validate_ir.py", "--job", str(job)),
            ("validators/validate_provenance.py", "--job", str(job)),
            ("validators/validate_links.py", "--job", str(job), "--mode", "ir"),
            ("tools/advance_phase.py", "--job", str(job)),  # -> Phase 3
            ("tools/compile_structure.py", "--job", str(job)),
            ("tools/normalize_tables.py", "--job", str(job)),
            ("tools/normalize_formulas.py", "--job", str(job)),
            ("tools/semanticize_figures.py", "--job", str(job)),
            ("validators/validate_ir.py", "--job", str(job)),
            ("validators/validate_links.py", "--job", str(job), "--mode", "ir"),
        ]
        for tgt, *a in chain:
            r = run(tgt, *a)
            self.assertEqual(r.returncode, 0, f"{tgt} failed: {r.stdout}\n{r.stderr}")
        self.assertTrue((job / "review" / "semantic_compile.md").is_file())
        # the Phase 3 validate_ir gate filed under the right phase
        self.assertTrue((job / "logs" / "gates" / "gate_3_semantic_compile_validate_ir.json").is_file())

    def test_phase5_assembly(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        chain = [
            ("validators/validate_state.py", "--job", str(job)),
            ("validators/validate_manifest.py", "--job", str(job), "--mode", "draft"),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/run_extraction.py", "--job", str(job)),
            ("validators/validate_extraction.py", "--job", str(job)),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/build_ir.py", "--job", str(job)),
            ("tools/link_assets.py", "--job", str(job)),
            ("tools/assemble_agent_md.py", "--job", str(job)),
            ("validators/validate_links.py", "--job", str(job), "--mode", "markdown"),
        ]
        for tgt, *a in chain:
            r = run(tgt, *a)
            self.assertEqual(r.returncode, 0, f"{tgt} failed: {r.stdout}\n{r.stderr}")
        main = (job / "output" / "main.md").read_text(encoding="utf-8")
        self.assertIn("schema: agent-friendly-md/0.1", main)   # front-matter
        self.assertIn("〔源", main)                              # at least one source anchor
        self.assertTrue((job / "output" / "provenance.json").is_file())
        # output provenance must match the IR projection (validate_ir checks this)
        r = run("validators/validate_ir.py", "--job", str(job))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_phase5_split_and_orphan_clear(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612", "--max-blocks", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        for tgt, *a in [
            ("validators/validate_state.py", "--job", str(job)),
            ("validators/validate_manifest.py", "--job", str(job), "--mode", "draft"),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/run_extraction.py", "--job", str(job)),
            ("validators/validate_extraction.py", "--job", str(job)),
            ("tools/advance_phase.py", "--job", str(job)),
            ("tools/build_ir.py", "--job", str(job)),
            ("tools/link_assets.py", "--job", str(job)),
            ("tools/assemble_agent_md.py", "--job", str(job)),
        ]:
            self.assertEqual(run(tgt, *a).returncode, 0, tgt)
        parts = job / "output" / "parts"
        self.assertTrue(list(parts.glob("*.md")), "split should produce parts")
        self.assertIn("分卷目录", (job / "output" / "main.md").read_text(encoding="utf-8"))
        index_md = (job / "output/index.md").read_text(encoding="utf-8")
        index_json = json.loads((job / "output/index.json").read_text(encoding="utf-8"))
        self.assertIn("Agent Index", index_md)
        self.assertTrue(index_json["split"]["enabled"])
        self.assertTrue(index_json["parts"])
        # inject an orphan part, re-assemble, confirm it is cleared
        (parts / "99-orphan.md").write_text("stale", encoding="utf-8")
        self.assertEqual(run("tools/assemble_agent_md.py", "--job", str(job)).returncode, 0)
        self.assertFalse((parts / "99-orphan.md").exists(), "re-assembly must clear orphan parts")
        self.assertEqual(run("validators/validate_links.py", "--job", str(job), "--mode", "markdown").returncode, 0)

    def test_advance_blocked_without_gates(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs / "mini-20260612"
        # advancing before any Phase 0 gate has run must be refused
        r = run("tools/advance_phase.py", "--job", str(job))
        self.assertEqual(r.returncode, 1, "advance must refuse a phase with no gate results")


if __name__ == "__main__":
    unittest.main()
