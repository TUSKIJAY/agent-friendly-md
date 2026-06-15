"""Phase 6 visual validation smoke tests (v0.8)."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4"
    "z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def run(target: str, *args: str):
    return subprocess.run([sys.executable, str(WRAPPER), target, *args],
                          capture_output=True, text=True, encoding="utf-8")


class TestV08VisualValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = Path(self.tmp.name) / "job"
        P.ensure_skeleton(self.job)
        (self.job / "source/doc.md").write_text("# Title\n", encoding="utf-8")
        state = js.new_state(job_id="doc-20260612", source_files=["source/doc.md"],
                             job_root=str(self.job), primary_ext=".md")
        idx = js.PHASES.index("6_validation")
        state["current_phase"] = "6_validation"
        state["phase_status"] = {
            ph: ("done" if i < idx else "in_progress" if i == idx else "pending")
            for i, ph in enumerate(js.PHASES)
        }
        state["document_profile"]["profile_status"] = "confirmed"
        state["document_profile"]["confirmed_by"] = "test"
        state["document_profile"]["risk_level"] = "high"
        js.save_state(self.job, state)
        draft = mf.new_draft(job_id="doc-20260612", document_slug="doc",
                             sources=[mf.source_entry(self.job, "source/doc.md")],
                             split_thresholds=js.DEFAULT_SPLIT_THRESHOLDS)
        draft["outputs"]["main"] = "main.md"
        draft["outputs"]["index"] = {"markdown": "index.md", "json": "index.json"}
        draft["input_hashes"] = {"5_assembly": "0" * 64}
        (self.job / "output/manifest.json").write_text(json.dumps(draft) + "\n", encoding="utf-8")
        (self.job / P.OUTPUT_MAIN).write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\nBody.\n",
            encoding="utf-8",
        )
        (self.job / "output/index.md").write_text("# Agent Index: Title\n\n- Entry: [main.md](main.md)\n",
                                                   encoding="utf-8")
        (self.job / "output/index.json").write_text(json.dumps({
            "schema_version": "agent-friendly-md-index/0.1",
            "title": "Title",
            "entry": {"path": "main.md", "mode": "single_file", "approx_tokens": 10},
            "split": {"enabled": False, "parts": []},
            "stats": {},
            "parts": [],
        }) + "\n", encoding="utf-8")
        (self.job / "extracted/pages/page_001.png").write_bytes(PNG_BYTES)
        (self.job / "ir/blocks.jsonl").write_text("", encoding="utf-8")
        (self.job / P.REVIEW_UNRESOLVED).write_text("# Unresolved\n\n_No unresolved issues._\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_preview_generates_html_and_anchor_map(self):
        r = run("tools/render_agent_md_preview.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.job / "review/visual_acceptance/rendered.html").is_file())
        anchor_map = json.loads((self.job / "review/visual_acceptance/anchor_map.json").read_text(encoding="utf-8"))
        self.assertEqual(anchor_map["anchors"][0]["source_anchor"], "p.1")
        diagnostics = json.loads((self.job / "review/visual_acceptance/render_diagnostics.json").read_text(encoding="utf-8"))
        self.assertIn("renderer_ok", diagnostics, "render must declare an explicit renderer_ok signal")
        if diagnostics["status"] == "pass":
            self.assertTrue(diagnostics["renderer_ok"], "a clean render must have used the real renderer")
            self.assertTrue(diagnostics["screenshots"])
            self.assertTrue(diagnostics["contact_sheet"])
            for rel in [*diagnostics["screenshots"], diagnostics["contact_sheet"]]:
                self.assertTrue((self.job / rel).is_file(), rel)
            comparisons = diagnostics["source_comparisons"]
            self.assertTrue(comparisons["artifacts"])
            self.assertTrue(comparisons["sampled_pages"])
            self.assertTrue(comparisons["sampled_anchors"])
            for rel in comparisons["artifacts"]:
                self.assertTrue((self.job / rel).is_file(), rel)
        else:
            self.assertTrue(diagnostics["warnings"])

    def test_formula_output_inlines_katex_offline(self):
        # P2: vendored KaTeX must actually be wired so $$…$$ renders offline.
        (self.job / P.OUTPUT_MAIN).write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Title　〔源 p.1〕\n\n"
            "$$H(z)=\\frac{b_0}{1+a_1 z^{-1}}$$\n",
            encoding="utf-8",
        )
        r = run("tools/render_agent_md_preview.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html = (self.job / "review/visual_acceptance/rendered.html").read_text(encoding="utf-8")
        self.assertIn("renderMathInElement", html)
        self.assertIn("katex", html.lower())
        diagnostics = json.loads(
            (self.job / "review/visual_acceptance/render_diagnostics.json").read_text(encoding="utf-8"))
        self.assertTrue(diagnostics["formula_render"]["katex"])

    def test_no_math_output_skips_katex(self):
        # setUp main.md has no math: KaTeX must NOT be inlined, and this is decoupled
        # from the gate (formula_render lives outside warnings).
        r = run("tools/render_agent_md_preview.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html = (self.job / "review/visual_acceptance/rendered.html").read_text(encoding="utf-8")
        self.assertNotIn("renderMathInElement", html)
        diagnostics = json.loads(
            (self.job / "review/visual_acceptance/render_diagnostics.json").read_text(encoding="utf-8"))
        self.assertFalse(diagnostics["formula_render"]["katex"])

    def test_build_packet_promotes_phase6_outputs(self):
        r = run("tools/build_visual_review_packet.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in ("output/qa_report.md", "output/visual_acceptance.md", "output/unresolved.md",
                    "review/visual_acceptance/render_diagnostics.json"):
            self.assertTrue((self.job / rel).is_file(), rel)
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stage"], "final")
        self.assertIn("qa_report", manifest["outputs"])

    def test_validation_gate_fails_missing_visual_report_for_high_risk(self):
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_high_risk_visual_requires_screenshot_artifacts(self):
        for rel, text in {
            P.OUTPUT_QA_REPORT: "# QA\n",
            P.OUTPUT_VISUAL_ACCEPTANCE: "# Visual\nstatus: pass_with_notes\n",
            P.OUTPUT_UNRESOLVED: "# Unresolved\n\n_No unresolved issues._\n",
            "review/visual_acceptance/rendered.html": "<html></html>\n",
            "review/visual_acceptance/anchor_map.json": json.dumps({"anchors": [{"source_anchor": "p.1"}]}),
            "review/visual_acceptance/render_diagnostics.json": json.dumps({
                "status": "pass_with_notes",
                "warnings": ["screenshots unavailable"],
                "screenshots": [],
                "contact_sheet": "",
            }),
        }.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        manifest["stage"] = "final"
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_high_risk_visual_requires_source_comparisons(self):
        for rel, text in {
            P.OUTPUT_QA_REPORT: "# QA\n",
            P.OUTPUT_VISUAL_ACCEPTANCE: "# Visual\nstatus: pass\n",
            P.OUTPUT_UNRESOLVED: "# Unresolved\n\n_No unresolved issues._\n",
            "review/visual_acceptance/rendered.html": "<html></html>\n",
            "review/visual_acceptance/anchor_map.json": json.dumps({"anchors": [{"source_anchor": "p.1"}]}),
            "review/visual_acceptance/render_diagnostics.json": json.dumps({
                "status": "pass",
                "warnings": [],
                "screenshots": ["review/visual_acceptance/screenshot_desktop.png"],
                "contact_sheet": "review/visual_acceptance/contact_sheet.png",
                "source_comparisons": {
                    "dir": "review/visual_acceptance/source_comparisons",
                    "artifacts": [],
                    "sampled_pages": [],
                    "sampled_anchors": [],
                    "reason": "test",
                    "seed": "test",
                },
            }),
        }.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        for rel in ("review/visual_acceptance/screenshot_desktop.png",
                    "review/visual_acceptance/contact_sheet.png"):
            (self.job / rel).write_bytes(PNG_BYTES)
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        manifest["stage"] = "final"
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_high_risk_visual_passes_with_readable_source_comparison(self):
        comparison = "review/visual_acceptance/source_comparisons/page_001_compare.png"
        for rel, text in {
            P.OUTPUT_QA_REPORT: "# QA\n",
            P.OUTPUT_VISUAL_ACCEPTANCE: "# Visual\nstatus: pass\n",
            P.OUTPUT_UNRESOLVED: "# Unresolved\n\n_No unresolved issues._\n",
            "review/visual_acceptance/rendered.html": "<html></html>\n",
            "review/visual_acceptance/anchor_map.json": json.dumps({"anchors": [{"source_anchor": "p.1"}]}),
            "review/visual_acceptance/render_diagnostics.json": json.dumps({
                "status": "pass",
                "warnings": [],
                "renderer": "pandoc",
                "renderer_ok": True,
                "screenshots": ["review/visual_acceptance/screenshot_desktop.png"],
                "contact_sheet": "review/visual_acceptance/contact_sheet.png",
                "source_comparisons": {
                    "dir": "review/visual_acceptance/source_comparisons",
                    "artifacts": [comparison],
                    "sampled_pages": [{
                        "kind": "pdf_page",
                        "index": 1,
                        "source_image": "extracted/pages/page_001.png",
                        "rendered_screenshot": "review/visual_acceptance/screenshot_desktop.png",
                        "comparison": comparison,
                        "reason": "test",
                    }],
                    "sampled_anchors": [{
                        "anchor_id": "anchor_0001",
                        "source_anchor": "p.1",
                        "comparison": comparison,
                    }],
                    "reason": "test",
                    "seed": "test",
                },
            }),
        }.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        for rel in ("review/visual_acceptance/screenshot_desktop.png",
                    "review/visual_acceptance/contact_sheet.png",
                    comparison):
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_bytes(PNG_BYTES)
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        manifest["stage"] = "final"
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_high_risk_visual_passes_with_readable_text_source_evidence(self):
        evidence = "review/visual_acceptance/source_comparisons/source_evidence_001.md"
        for rel, text in {
            P.OUTPUT_QA_REPORT: "# QA\n",
            P.OUTPUT_VISUAL_ACCEPTANCE: "# Visual\nstatus: pass\n",
            P.OUTPUT_UNRESOLVED: "# Unresolved\n\n_No unresolved issues._\n",
            "review/visual_acceptance/rendered.html": "<html></html>\n",
            "review/visual_acceptance/anchor_map.json": json.dumps(
                {"anchors": [{"id": "anchor_0001", "source_anchor": "Intro / 段 2"}]}
            ),
            "review/visual_acceptance/render_diagnostics.json": json.dumps({
                "status": "pass",
                "warnings": [],
                "renderer": "pandoc",
                "renderer_ok": True,
                "screenshots": ["review/visual_acceptance/screenshot_desktop.png"],
                "contact_sheet": "review/visual_acceptance/contact_sheet.png",
                "source_comparisons": {
                    "dir": "review/visual_acceptance/source_comparisons",
                    "artifacts": [evidence],
                    "sampled_pages": [],
                    "sampled_source_evidence": [{
                        "anchor_id": "anchor_0001",
                        "source_anchor": "Intro / 段 2",
                        "source_kind": "docx_anchor",
                        "source_file": "source/doc.docx",
                        "block_id": "block_para_001",
                        "rendered_screenshot": "review/visual_acceptance/screenshot_desktop.png",
                        "evidence": evidence,
                        "reason": "test",
                    }],
                    "sampled_anchors": [{
                        "anchor_id": "anchor_0001",
                        "source_anchor": "Intro / 段 2",
                        "comparison": evidence,
                    }],
                    "reason": "test",
                    "seed": "test",
                },
            }),
        }.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        for rel in ("review/visual_acceptance/screenshot_desktop.png",
                    "review/visual_acceptance/contact_sheet.png"):
            (self.job / rel).write_bytes(PNG_BYTES)
        (self.job / evidence).parent.mkdir(parents=True, exist_ok=True)
        (self.job / evidence).write_text("# Source Evidence\n\nsource-linked\n", encoding="utf-8")
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        manifest["stage"] = "final"
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_render_preview_generates_text_source_evidence_for_docx_anchor(self):
        self._set_risk("high")
        (self.job / P.OUTPUT_MAIN).write_text(
            "---\nschema: agent-friendly-md/0.1\n---\n\n# Intro　〔源 Intro / 段 1〕\n\nBody.\n",
            encoding="utf-8",
        )
        (self.job / "ir/blocks.jsonl").write_text(json.dumps({
            "id": "block_heading_001",
            "type": "heading",
            "source_anchor": {
                "kind": "docx_anchor",
                "source_file": "source/doc.docx",
                "page": None,
                "heading_path": ["Intro"],
                "paragraph_index": 1,
            },
            "confidence": 1.0,
            "needs_review": False,
            "evidence_level": "native",
            "heading": {"level": 1, "text": "Intro"},
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        r = run("tools/render_agent_md_preview.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        diagnostics = json.loads(
            (self.job / "review/visual_acceptance/render_diagnostics.json").read_text(encoding="utf-8"))
        if diagnostics["status"] == "pass":
            evidence = diagnostics["source_comparisons"]["sampled_source_evidence"]
            self.assertTrue(evidence, diagnostics)
            self.assertTrue((self.job / evidence[0]["evidence"]).is_file())
        else:
            self.assertTrue(diagnostics["warnings"])

    def _set_risk(self, level: str) -> None:
        state = js.load_state(self.job)
        state["document_profile"]["risk_level"] = level
        js.save_state(self.job, state)

    def _write_phase6_outputs(self, diagnostics: dict, *,
                              with_screenshot: bool = False, with_contact: bool = False) -> None:
        status = diagnostics.get("status", "pass")
        files = {
            P.OUTPUT_QA_REPORT: "# QA\n",
            P.OUTPUT_VISUAL_ACCEPTANCE: f"# Visual\nstatus: {status}\n",
            P.OUTPUT_UNRESOLVED: "# Unresolved\n\n_No unresolved issues._\n",
            "review/visual_acceptance/rendered.html": "<html></html>\n",
            "review/visual_acceptance/anchor_map.json": json.dumps({"anchors": [{"source_anchor": "p.1"}]}),
            "review/visual_acceptance/render_diagnostics.json": json.dumps(diagnostics),
        }
        for rel, text in files.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        if with_screenshot:
            (self.job / "review/visual_acceptance/screenshot_desktop.png").write_bytes(PNG_BYTES)
        if with_contact:
            (self.job / "review/visual_acceptance/contact_sheet.png").write_bytes(PNG_BYTES)
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        manifest = json.loads((self.job / "output/manifest.json").read_text(encoding="utf-8"))
        manifest["stage"] = "final"
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    _FALLBACK_DIAG = {
        "status": "pass_with_notes",
        "renderer": "pandoc missing; used escaped preformatted fallback",
        "renderer_ok": False,
        "screenshots": [],
        "contact_sheet": "",
        "warnings": ["pandoc missing; used escaped preformatted fallback",
                     "playwright unavailable; screenshots/contact sheet skipped"],
    }
    _REAL_DIAG = {
        "status": "pass",
        "renderer": "pandoc",
        "renderer_ok": True,
        "screenshots": ["review/visual_acceptance/screenshot_desktop.png"],
        "contact_sheet": "review/visual_acceptance/contact_sheet.png",
        "warnings": [],
    }

    def test_medium_risk_fallback_render_fails_then_real_render_passes(self):
        # B3: a medium-risk job with pandoc+playwright unavailable degrades to a
        # <pre> fallback with zero screenshots. That must HARD-FAIL (exit 1), not
        # advance to packaging; with the real renderer present it must pass.
        self._set_risk("medium")
        self._write_phase6_outputs(self._FALLBACK_DIAG)
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1,
                         "medium-risk fallback render must FAIL the gate\n" + r.stdout + r.stderr)

        self._write_phase6_outputs(self._REAL_DIAG, with_screenshot=True, with_contact=True)
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0,
                         "medium-risk real render must PASS the gate\n" + r.stdout + r.stderr)

    def test_low_risk_missing_renderer_is_not_required_not_hard_fail(self):
        # PLAN §14.1: low risk is validator-only. A missing renderer is reported
        # "not required" (n/a) and must NOT hard-fail (exit 1) on that basis —
        # but it is still pass_with_notes, never a silent clean pass.
        self._set_risk("low")
        self._write_phase6_outputs(self._FALLBACK_DIAG)
        r = run("validators/validation_gate.py", "--job", str(self.job))
        self.assertIn(r.returncode, (0, 2),
                      "low-risk must not hard-fail purely for a missing renderer\n" + r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 1)

    def test_run_validators_phase6_advances_after_packet(self):
        self.assertEqual(run("tools/build_visual_review_packet.py", "--job", str(self.job)).returncode, 0)
        r = run("tools/run_validators.py", "--job", str(self.job))
        self.assertIn(r.returncode, (0, 2), r.stdout + r.stderr)
        state = js.load_state(self.job)
        self.assertEqual(state["current_phase"], "7_package")
        self.assertTrue((self.job / "logs/hashes/6_validation.json").is_file())


if __name__ == "__main__":
    unittest.main()
