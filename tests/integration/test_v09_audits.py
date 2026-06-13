"""Phase 4 special audit tests (v0.9)."""
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

from lib import hashes  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402


def run(target: str, *args: str):
    return subprocess.run([sys.executable, str(WRAPPER), target, *args],
                          capture_output=True, text=True, encoding="utf-8")


def _anchor() -> dict:
    return {"kind": "pdf_page", "source_file": "source/doc.pdf", "page": 1}


class TestV09Audits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = Path(self.tmp.name) / "job"
        P.ensure_skeleton(self.job)
        (self.job / "source/doc.pdf").write_text("source", encoding="utf-8")
        state = js.new_state(
            job_id="doc-20260613",
            source_files=["source/doc.pdf"],
            job_root=str(self.job),
            primary_ext=".pdf",
        )
        idx = js.PHASES.index("4_audit")
        state["current_phase"] = "4_audit"
        state["phase_status"] = {
            ph: ("done" if i < idx else "in_progress" if i == idx else "pending")
            for i, ph in enumerate(js.PHASES)
        }
        js.save_state(self.job, state)
        self._write_ir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_ir(self):
        blocks = [
            IR.new_block(
                "block_table_001", "table", _anchor(), confidence=0.95, needs_review=False,
                title="Coefficient Registers",
                table={
                    "columns": ["Address", "Register", "Description", "Reset"],
                    "header_rows": [],
                    "rows": [[
                        {"text": "0x08", "rowspan": 1, "colspan": 1},
                        {"text": "ADC_BQ1", "rowspan": 1, "colspan": 1},
                        {"text": "Filter coefficient", "rowspan": 1, "colspan": 1},
                        {"text": "0x7F", "rowspan": 1, "colspan": 1},
                    ]],
                },
            ),
            IR.new_block(
                "block_table_002", "table", _anchor(), confidence=0.9, needs_review=False,
                title="Register Table",
                table={
                    "columns": ["Address", "Register", "Description"],
                    "header_rows": [],
                    "rows": [[
                        {"text": "not_addr", "rowspan": 1, "colspan": 1},
                        {"text": "CTRL", "rowspan": 1, "colspan": 1},
                        {"text": "Control bits", "rowspan": 1, "colspan": 1},
                    ]],
                },
            ),
            IR.new_block(
                "block_formula_001", "formula", _anchor(), confidence=0.7, needs_review=True,
                formula={"equation_no": "1", "latex": "E={mc^2", "visual_check": "needs_review"},
            ),
            IR.new_block(
                "block_figure_001", "figure", _anchor(), confidence=0.8, needs_review=True,
                figure={
                    "figure_no": "Figure 1",
                    "caption": "",
                    "asset_id": "asset_fig_001",
                    "asset_file": "extracted/images/missing.png",
                    "description": "",
                    "estimated_values": [{"label": "gain", "value": "about 3 dB"}],
                },
            ),
        ]
        doc = {
            "schema_version": IR.IR_SCHEMA_VERSION,
            "document_id": "doc",
            "metadata": {"title": "Doc", "source_type": "pdf", "source_file": "source/doc.pdf", "language": "en"},
            "stores": {"blocks": "blocks.jsonl", "assets_index": "assets.index.json", "provenance": "provenance.json"},
            "block_order": [b["id"] for b in blocks],
            "relations": [],
            "stats": IR.recompute_stats(blocks),
        }
        IR.save_all(self.job, blocks, doc)

    def _issues(self) -> list[dict]:
        return ISS.read_issues(self.job / P.REVIEW_ISSUES)[0]

    def test_audit_tables_marks_register_hard_columns(self):
        r = run("tools/audit_tables.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        blocks = {b["id"]: b for b in IR.read_blocks(self.job)}
        self.assertEqual(blocks["block_table_001"]["table"]["audit"]["hard_column_check"], "pass")
        issue_ids = {i["id"] for i in self._issues()}
        self.assertIn("table_block_table_002_missing_required_columns", issue_ids)
        self.assertIn("table_block_table_002_register_address_format", issue_ids)

    def test_register_word_without_address_column_is_not_hard_register_table(self):
        blocks, doc = IR.load_ir(self.job)
        table = IR.new_block(
            "block_table_003", "table", _anchor(), confidence=0.9, needs_review=False,
            title="寄存器配置章节分配",
            table={
                "columns": ["项目", "说明"],
                "header_rows": [],
                "rows": [[
                    {"text": "ADC", "rowspan": 1, "colspan": 1},
                    {"text": "滤波配置所在章节", "rowspan": 1, "colspan": 1},
                ]],
            },
        )
        blocks.append(table)
        doc["block_order"].append(table["id"])
        doc["stats"] = IR.recompute_stats(blocks)
        IR.save_all(self.job, blocks, doc)
        r = run("tools/audit_tables.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        blocks = {b["id"]: b for b in IR.read_blocks(self.job)}
        self.assertEqual(blocks["block_table_003"]["table"]["audit"]["hard_table_type"], "generic")
        self.assertNotIn("table_block_table_003_missing_required_columns", {i["id"] for i in self._issues()})

    def test_audit_formulas_records_visual_proof_issues(self):
        r = run("tools/audit_formulas.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ids = {i["id"] for i in self._issues()}
        self.assertIn("formula_block_formula_001_unbalanced_latex", ids)
        self.assertIn("formula_block_formula_001_needs_visual_proof", ids)
        self.assertIn("formula_block_formula_001_low_confidence", ids)

    def test_audit_assets_marks_fixed_on_rerun(self):
        first = run("tools/audit_assets.py", "--job", str(self.job))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("figure_block_figure_001_asset_missing", {i["id"] for i in self._issues()})
        (self.job / "extracted/images/missing.png").write_bytes(b"png")
        blocks, doc = IR.load_ir(self.job)
        fig = blocks[-1]["figure"]
        fig["caption"] = "Chart caption"
        fig["description"] = "Chart description"
        fig["estimated_values"][0]["basis"] = "图上估读"
        IR.save_all(self.job, blocks, doc)
        second = run("tools/audit_assets.py", "--job", str(self.job))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        issues = {i["id"]: i for i in self._issues()}
        self.assertEqual(issues["figure_block_figure_001_asset_missing"]["status"], "fixed")
        unresolved = (self.job / P.REVIEW_UNRESOLVED).read_text(encoding="utf-8")
        self.assertNotIn("figure_block_figure_001_asset_missing", unresolved)

    def test_audit_assets_does_not_require_caption_for_noise_figures(self):
        (self.job / "extracted/images/logo.png").write_bytes(b"png")
        blocks, doc = IR.load_ir(self.job)
        fig = blocks[-1]["figure"]
        fig["asset_file"] = "extracted/images/logo.png"
        fig["caption"] = ""
        fig["description"] = ""
        fig["likely_noise"] = True
        fig["noise_reason"] = "decorative_or_document_artifact"
        fig["estimated_values"] = [{"label": "ignored", "value": "n/a"}]
        IR.save_all(self.job, blocks, doc)
        r = run("tools/audit_assets.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ids = {i["id"] for i in self._issues()}
        self.assertNotIn("figure_block_figure_001_caption_missing", ids)
        self.assertNotIn("figure_block_figure_001_description_missing", ids)
        self.assertNotIn("figure_block_figure_001_estimated_value_basis_missing", ids)

    def test_audit_provenance_accepts_anchored_word_comment(self):
        comment = {
            "id": "comment_001",
            "text": "Reviewer note",
            "source_anchor": {
                "kind": "docx_anchor",
                "source_file": "source/doc.pdf",
                "heading_path": ["Section"],
                "paragraph_index": 2,
            },
        }
        (self.job / "extracted/comments/comments.jsonl").write_text(json.dumps(comment) + "\n", encoding="utf-8")
        r = run("tools/audit_provenance.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([i for i in self._issues() if "comment_001" in i["id"]])

    def test_audit_provenance_flags_comment_without_anchor(self):
        comment = {"id": "comment_002", "text": "Reviewer note"}
        (self.job / "extracted/comments/comments.jsonl").write_text(json.dumps(comment) + "\n", encoding="utf-8")
        r = run("tools/audit_provenance.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ids = {i["id"] for i in self._issues()}
        self.assertIn("provenance_comment_comments_jsonl_1_anchor_missing", ids)

    def test_audit_provenance_reads_json_revisions_container(self):
        artifact = {"revisions": [{"id": "rev_001", "revision": "Deleted text"}]}
        (self.job / "extracted/comments/revisions.json").write_text(json.dumps(artifact), encoding="utf-8")
        r = run("tools/audit_provenance.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ids = {i["id"] for i in self._issues()}
        self.assertIn("provenance_comment_revisions_json_1_anchor_missing", ids)

    def test_audit_does_not_overwrite_malformed_existing_issues(self):
        bad = "{not-json}\n"
        (self.job / P.REVIEW_ISSUES).write_text(bad, encoding="utf-8")
        r = run("tools/audit_formulas.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual((self.job / P.REVIEW_ISSUES).read_text(encoding="utf-8"), bad)

    def test_run_audits_writes_phase4_summary(self):
        r = run("tools/run_audits.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        summary = json.loads((self.job / P.REVIEW_AUDIT_SUMMARY).read_text(encoding="utf-8"))
        self.assertEqual(len(summary["tools"]), 4)
        phase4_outputs = hashes.phase_hashes(self.job, "4_audit", "outputs")
        self.assertIn(P.REVIEW_AUDIT_SUMMARY, phase4_outputs)
        self.assertIn("ir/blocks.jsonl", phase4_outputs)
        gate = run("validators/validate_audit_summary.py", "--job", str(self.job))
        self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)


if __name__ == "__main__":
    unittest.main()
