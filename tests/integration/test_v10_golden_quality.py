"""Golden quality regression tests (v1.0)."""
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
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import paths as P  # noqa: E402


def run(target: str, *args: str):
    return subprocess.run([sys.executable, str(WRAPPER), target, *args],
                          capture_output=True, text=True, encoding="utf-8")


class TestV10GoldenQuality(unittest.TestCase):
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
        js.save_state(self.job, state)
        (self.job / "extracted/images/fig.png").write_bytes(b"png")
        self._write_ir(needs_review=False, confidence=0.95)
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n"
            "> This golden document summarizes programmable filter registers, figures, and equations.\n\n"
            "## 目录\n\n"
            "- [Golden Doc](#golden-doc)\n\n"
            "---\n\n"
            "![Figure](../extracted/images/fig.png)\n\n"
            "| Address | Register | Description | Reset |\n"
            "| --- | --- | --- | --- |\n"
            "| 0x08 | ADC_BQ1 | Filter coefficient | 0x7F |\n\n"
            "$$H(z)=\\frac{b_0}{1+a_1z^{-1}}$$\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write_ir(self, needs_review: bool, confidence: float):
        anchor = {"kind": "pdf_page", "source_file": "source/doc.pdf", "page": 1}
        blocks = [
            IR.new_block(
                "block_heading_001", "heading", anchor, confidence=1.0, needs_review=False,
                heading={"level": 1, "text": "Golden Doc"},
            ),
            IR.new_block(
                "block_table_001", "table", anchor, confidence=0.95, needs_review=False,
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
                "block_formula_001", "formula", anchor, confidence=confidence, needs_review=needs_review,
                formula={"equation_no": "1", "latex": "H(z)=\\frac{b_0}{1+a_1z^{-1}}", "visual_check": "ok"},
            ),
            IR.new_block(
                "block_figure_001", "figure", anchor, confidence=0.9, needs_review=False,
                figure={
                    "figure_no": "Figure 1",
                    "caption": "Filter response",
                    "asset_id": "asset_fig_001",
                    "asset_file": "extracted/images/fig.png",
                    "description": "A response chart.",
                    "estimated_values": [{"label": "gain", "value": "约 3 dB", "basis": "图上估读"}],
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

    def test_golden_quality_passes_core_criteria(self):
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job),
                "--expect", "figure", "--expect", "formula", "--expect", "register")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["counts"]["register_tables"], 1)

    def test_low_confidence_must_be_tracked(self):
        self._write_ir(needs_review=True, confidence=0.5)
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job), "--expect", "formula")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        issue = ISS.new_issue(
            issue_id="golden_formula_review",
            severity="minor",
            category="formula",
            source_block_id="block_formula_001",
            source_anchor="〔源 p.1〕",
            issue="Formula needs manual tracking.",
            required_action="Review formula.",
            found_by="test",
        )
        ISS.write_issues(self.job / P.REVIEW_ISSUES, [issue])
        (self.job / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved([issue]), encoding="utf-8")
        r = run("tools/check_golden_quality.py", "--job", str(self.job), "--expect", "formula")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_broken_output_markdown_image_link_fails_golden_quality(self):
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n- [Golden Doc](#golden-doc)\n\n---\n\n"
            "![Figure](assets/missing.png)\n",
            encoding="utf-8",
        )
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job), "--expect", "figure")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("markdown_links_resolve", report["failed_checks"])

    def test_likely_noise_blocks_do_not_need_unresolved_issues(self):
        blocks, doc = IR.load_ir(self.job)
        noise = IR.new_block(
            "block_para_noise", "para",
            {"kind": "pdf_page", "source_file": "source/doc.pdf", "page": 1},
            confidence=0.2, needs_review=True,
            content={"text": "第 1 页 公司页脚", "likely_noise": True},
        )
        blocks.append(noise)
        doc["block_order"].append(noise["id"])
        doc["stats"] = IR.recompute_stats(blocks)
        IR.save_all(self.job, blocks, doc)
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job), "--expect", "register")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertEqual(report["counts"]["low_confidence"], 0)

    def test_baseline_comparison_is_recorded(self):
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        baseline = self.job / "baseline.md"
        baseline.write_text("# Golden Doc\n\nPlain text only.\n", encoding="utf-8")
        r = run("tools/check_golden_quality.py", "--job", str(self.job),
                "--baseline-md", str(baseline), "--expect", "register")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(report["baseline_comparison"])
        self.assertGreater(report["baseline_comparison"]["delta"]["source_anchors"], 0)
        self.assertEqual(report["baseline_comparison"]["status"], "pass")
        self.assertIn("criteria", report["baseline_comparison"])

    def test_generic_title_fails(self):
        (self.job / P.OUTPUT_MAIN).write_text(
            "# pdf　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n- [pdf](#pdf)\n\n---\n\nBody.\n",
            encoding="utf-8",
        )
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("main_has_meaningful_title", report["failed_checks"])

    def test_missing_summary_block_fails(self):
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "## 目录\n\n- [Golden Doc](#golden-doc)\n\n---\n\nBody.\n",
            encoding="utf-8",
        )
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("main_has_summary_block", report["failed_checks"])

    def test_empty_toc_when_headings_exist_fails(self):
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n---\n\n## Register Map　〔源 p.1〕\n\nBody.\n",
            encoding="utf-8",
        )
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("main_has_nonempty_toc", report["failed_checks"])

    def test_incoherent_toc_fails_golden(self):
        # Q1: the prior gate scored 1.0 with "6 to 4 Mux" (a device label) promoted
        # to the top of the TOC and the section numbering out of order. A TOC like
        # the real ZHCAEJ4 one must now FAIL golden.
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n"
            "- [6 to 4 Mux](#6-to-4-mux)\n"
            "- [3 概述](#3)\n"
            "  - [3.4 滤波器](#34)\n"
            "- [6 参考资料](#6)\n\n"
            "---\n\n"
            "## 6 to 4 Mux　〔源 p.1〕\n\nBody.\n",
            encoding="utf-8",
        )
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("toc_structurally_coherent", report["failed_checks"])
        kinds = {i["kind"] for i in report["structure_quality"]["toc_coherence"]["issues"]}
        self.assertIn("caption_label_at_top_level", kinds)
        self.assertIn("nonmonotonic_section_numbers", kinds)

    def test_coherent_toc_passes_golden(self):
        # The counter-case: properly ordered TOC with real titles passes — including
        # a legitimate appendix restart-to-1 ([1,2,3,1] must NOT be flagged).
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n"
            "- [1 概述](#1)\n"
            "- [2 寄存器映射](#2)\n"
            "  - [2.1 系数寄存器](#21)\n"
            "- [3 参考资料](#3)\n"
            "- [1 附录 A](#a1)\n\n"
            "---\n\n"
            "## 1 概述　〔源 p.1〕\n\nBody.\n",
            encoding="utf-8",
        )
        self.assertEqual(run("tools/audit_tables.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertTrue(report["checks"]["toc_structurally_coherent"])

    def test_opening_noise_density_fails(self):
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Golden Doc　〔源 p.1〕\n\n"
            "> **摘要**\n> ok\n\n"
            "## 目录\n\n- [Golden Doc](#golden-doc)\n\n---\n\n"
            "pdf\n"
            "目录\n"
            "1 Overview 1\n"
            "2 Register Map 4\n"
            "Page 1 of 24\n"
            "## Register Map　〔源 p.1〕\n\nBody.\n",
            encoding="utf-8",
        )
        r = run("tools/check_golden_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        report = json.loads((self.job / "review/golden_quality.json").read_text(encoding="utf-8"))
        self.assertIn("opening_noise_density_ok", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
