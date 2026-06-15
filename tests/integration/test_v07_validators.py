"""v0.7 validator, unresolved, and hash-staleness integration tests."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

from lib import ir as IR  # noqa: E402
from lib import extraction_elements as EE  # noqa: E402
from lib import extraction_router as ER  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402


def run(target: str, *args: str):
    return subprocess.run(
        [sys.executable, str(WRAPPER), target, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def set_phase(state: dict, phase: str) -> dict:
    idx = js.PHASES.index(phase)
    state["current_phase"] = phase
    state["phase_status"] = {
        ph: ("done" if i < idx else "in_progress" if i == idx else "pending")
        for i, ph in enumerate(js.PHASES)
    }
    return state


class TestV07Validators(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "job"
        P.ensure_skeleton(self.job)
        (self.job / "source" / "doc.md").write_text("# Title\n", encoding="utf-8")
        state = js.new_state(
            job_id="doc-20260612",
            source_files=["source/doc.md"],
            job_root=str(self.job),
            primary_ext=".md",
        )
        js.save_state(self.job, state)
        draft = mf.new_draft(
            job_id="doc-20260612",
            document_slug="doc",
            sources=[mf.source_entry(self.job, "source/doc.md")],
            split_thresholds=js.DEFAULT_SPLIT_THRESHOLDS,
        )
        (self.job / "output" / "manifest.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write_state_phase(self, phase: str) -> None:
        state = js.load_state(self.job)
        js.save_state(self.job, set_phase(state, phase))

    def _write_ir(self, bad_table: bool = False) -> None:
        anchor = {
            "kind": "text_anchor",
            "source_file": "source/doc.md",
            "heading_path": ["Title"],
            "block_index": 1,
        }
        table_row = [{"text": "1", "rowspan": 1, "colspan": 1}]
        if not bad_table:
            table_row.append({"text": "2", "rowspan": 1, "colspan": 1})
        blocks = [
            IR.new_block(
                "block_heading_001", "heading", anchor,
                confidence=1.0, needs_review=False,
                heading={"level": 1, "text": "Title"},
            ),
            IR.new_block(
                "block_table_001", "table", anchor,
                confidence=1.0, needs_review=False,
                title="Data",
                table={"columns": ["A", "B"], "header_rows": [], "rows": [table_row]},
            ),
        ]
        doc = {
            "schema_version": IR.IR_SCHEMA_VERSION,
            "document_id": "doc",
            "metadata": {
                "title": "Title",
                "source_type": "md",
                "source_file": "source/doc.md",
                "language": "zh-CN",
            },
            "stores": {
                "blocks": "blocks.jsonl",
                "assets_index": "assets.index.json",
                "provenance": "provenance.json",
            },
            "block_order": [b["id"] for b in blocks],
            "relations": [],
            "stats": IR.recompute_stats(blocks),
        }
        IR.save_all(self.job, blocks, doc)

    def _write_extraction(self, *, include_elements: bool = True) -> None:
        skeleton = "# Title\n\nBody.\n"
        meta = {"source_format": ".md", "image_count": 0, "mapped_image_count": 0, "structured_stats": {}}
        elements = EE.elements_from_skeleton(skeleton, "source/doc.md", ".md")
        state = js.load_state(self.job)
        elements, meta = ER.analyze_and_write(self.job, state, meta, elements)
        if include_elements:
            EE.write_elements(self.job, elements)
            meta = EE.update_extract_meta(meta, elements, ".md")
        (self.job / "extracted" / "extract_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (self.job / "extracted" / "text" / "doc_skeleton.md").write_text(skeleton, encoding="utf-8")

    def test_validate_tables_catches_row_width_mismatch(self):
        self._write_state_phase("4_audit")
        self._write_ir(bad_table=True)
        r = run("validators/validate_tables.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue((self.job / "logs/gates/gate_4_audit_validate_tables.json").is_file())

    def test_validate_tables_bad_cell_schema_fails_without_traceback(self):
        self._write_state_phase("4_audit")
        self._write_ir()
        blocks = IR.read_blocks(self.job)
        blocks[1]["table"]["rows"] = [[{"text": "1", "rowspan": 1, "colspan": 1}, "not-a-cell"]]
        IR.write_blocks(self.job, blocks)
        r = run("validators/validate_tables.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_validate_unresolved_blocks_open_blocker(self):
        self._write_state_phase("4_audit")
        issue = {
            "id": "unresolved_001",
            "severity": "blocker",
            "status": "open",
            "accepted_by": "",
            "accepted_reason": "",
            "source_block_id": "block_table_001",
            "source_anchor": "p.1",
            "category": "table",
            "issue": "Table needs manual review.",
            "required_action": "Fix the table.",
            "found_by": "audit_tables.py",
            "created_at": "2026-06-12T00:00:00Z",
        }
        (self.job / "review/issues.jsonl").write_text(json.dumps(issue) + "\n", encoding="utf-8")
        (self.job / "review/unresolved.md").write_text(
            "# Unresolved\n\n## unresolved_001\n\nTable needs manual review.\n",
            encoding="utf-8",
        )
        r = run("validators/validate_unresolved.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_validate_unresolved_missing_id_fails_without_traceback(self):
        self._write_state_phase("4_audit")
        issue = {
            "severity": "blocker",
            "status": "open",
            "accepted_by": "",
            "accepted_reason": "",
            "source_block_id": "block_table_001",
            "source_anchor": "p.1",
            "category": "table",
            "issue": "Missing id should be a gate failure, not a crash.",
            "required_action": "Add an id.",
            "found_by": "audit_tables.py",
            "created_at": "2026-06-12T00:00:00Z",
        }
        (self.job / "review/issues.jsonl").write_text(json.dumps(issue) + "\n", encoding="utf-8")
        (self.job / "review/unresolved.md").write_text(
            "# Unresolved\n\nMissing id should be a gate failure, not a crash.\n",
            encoding="utf-8",
        )
        r = run("validators/validate_unresolved.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue((self.job / "logs/gates/gate_4_audit_validate_unresolved.json").is_file())

    def test_validate_placeholders_requires_unresolved_entry(self):
        self._write_state_phase("5_assembly")
        (self.job / "output/main.md").write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\n"
            "> [未解析: 图片说明 — 需视觉描述]\n",
            encoding="utf-8",
        )
        (self.job / "review/unresolved.md").write_text("# Unresolved\n\n_No unresolved issues._\n", encoding="utf-8")
        r = run("validators/validate_placeholders.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

        (self.job / "review/unresolved.md").write_text(
            "# Unresolved\n\n## unresolved_001\n\n图片说明 — 需视觉描述\n",
            encoding="utf-8",
        )
        issue = {
            "id": "unresolved_001",
            "severity": "minor",
            "status": "open",
            "accepted_by": "",
            "accepted_reason": "",
            "source_block_id": "block_figure_001",
            "source_anchor": "p.1",
            "category": "figure",
            "issue": "图片说明 — 需视觉描述",
            "required_action": "补充视觉描述。",
            "found_by": "validate_placeholders.py",
            "created_at": "2026-06-12T00:00:00Z",
        }
        (self.job / "review/issues.jsonl").write_text(json.dumps(issue) + "\n", encoding="utf-8")
        (self.job / "review/unresolved.md").write_text(ISS.render_unresolved([issue]), encoding="utf-8")
        r = run("validators/validate_placeholders.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_validate_agent_md_quality_rejects_replacement_character(self):
        self._write_state_phase("5_assembly")
        (self.job / "output/main.md").write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\nBad � text.\n",
            encoding="utf-8",
        )
        r = run("validators/validate_agent_md_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_run_validators_phase0_advances_and_records_hashes(self):
        r = run("tools/run_validators.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = js.load_state(self.job)
        self.assertEqual(state["current_phase"], "1_extraction")
        self.assertTrue((self.job / "logs/hashes/0_intake.json").is_file())
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        self.assertIn("0_intake", manifest["input_hashes"])

    def test_run_validators_phase1_snapshot_can_be_rechecked(self):
        self._write_state_phase("1_extraction")
        self._write_extraction()
        first = run("tools/run_validators.py", "--job", str(self.job), "--phase", "1_extraction", "--no-advance")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run("tools/run_validators.py", "--job", str(self.job), "--phase", "1_extraction", "--no-advance")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_validate_extraction_requires_elements_file(self):
        self._write_state_phase("1_extraction")
        self._write_extraction(include_elements=False)
        r = run("validators/validate_extraction.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("elements_present", r.stdout)

    def test_run_validators_detects_stale_phase_inputs(self):
        self._write_state_phase("5_assembly")
        self._write_ir()
        (self.job / "output/main.md").write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n*〔源 p.1〕*\n",
            encoding="utf-8",
        )
        (self.job / "review/unresolved.md").write_text("# Unresolved\n\n_No unresolved issues._\n", encoding="utf-8")

        first = run("tools/run_validators.py", "--job", str(self.job), "--phase", "5_assembly", "--no-advance")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        blocks = self.job / IR.IR_BLOCKS
        blocks.write_text(blocks.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        second = run("tools/run_validators.py", "--job", str(self.job), "--phase", "5_assembly", "--no-advance")
        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
        self.assertTrue((self.job / "logs/gates/gate_5_assembly_hash_stale.json").is_file())

    def test_run_validators_corrupt_hash_snapshot_writes_gate(self):
        self._write_state_phase("5_assembly")
        self._write_ir()
        (self.job / "output/main.md").write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n",
            encoding="utf-8",
        )
        (self.job / "logs" / "hashes" / "5_assembly.json").write_text("{bad json", encoding="utf-8")
        r = run("tools/run_validators.py", "--job", str(self.job), "--phase", "5_assembly", "--no-advance")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue((self.job / "logs/gates/gate_5_assembly_hash_stale.json").is_file())


if __name__ == "__main__":
    unittest.main()
