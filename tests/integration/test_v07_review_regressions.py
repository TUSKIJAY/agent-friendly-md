"""Regressions from the v0.7 adversarial review pass."""
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
from lib import manifest as mf  # noqa: E402
from lib import md_render as MD  # noqa: E402
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


class TestV07ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = Path(self.tmp.name) / "job"
        P.ensure_skeleton(self.job)
        (self.job / "source/doc.md").write_text("# Title\n", encoding="utf-8")
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
        (self.job / "output/manifest.json").write_text(json.dumps(draft) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _phase(self, phase: str) -> None:
        js.save_state(self.job, set_phase(js.load_state(self.job), phase))

    def _write_ir(self, cell_text: str = "1", colspan: int = 1) -> None:
        anchor = {"kind": "text_anchor", "source_file": "source/doc.md",
                  "heading_path": ["Title"], "block_index": 1}
        row = [{"text": cell_text, "rowspan": 1, "colspan": colspan}]
        if colspan < 2:
            row.append({"text": "2", "rowspan": 1, "colspan": 1})
        else:
            row.append({"text": "tail", "rowspan": 1, "colspan": 1})
        blocks = [
            IR.new_block("block_heading_001", "heading", anchor, confidence=1.0,
                         needs_review=False, heading={"level": 1, "text": "Title"}),
            IR.new_block("block_table_001", "table", anchor, confidence=1.0,
                         needs_review=False, table={"columns": ["A", "B", "C"] if colspan > 1 else ["A", "B"],
                                                    "header_rows": [], "rows": [row]}),
        ]
        doc = {"schema_version": IR.IR_SCHEMA_VERSION, "document_id": "doc",
               "metadata": {"title": "Title", "source_type": "md", "source_file": "source/doc.md"},
               "stores": {"blocks": "blocks.jsonl", "assets_index": "assets.index.json",
                          "provenance": "provenance.json"},
               "block_order": [b["id"] for b in blocks], "relations": [],
               "stats": IR.recompute_stats(blocks)}
        IR.save_all(self.job, blocks, doc)

    def test_unresolved_projection_rejects_extra_entries(self):
        self._phase("4_audit")
        (self.job / P.REVIEW_UNRESOLVED).write_text("# Unresolved\n\n## unresolved_999\n\nextra\n", encoding="utf-8")
        r = run("validators/validate_unresolved.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_unresolved_fixed_missing_id_fails_without_traceback(self):
        self._phase("4_audit")
        issue = {"severity": "minor", "status": "fixed", "accepted_by": "",
                 "accepted_reason": "", "source_block_id": "block_para_001",
                 "source_anchor": "p.1", "category": "ocr", "issue": "fixed",
                 "required_action": "none", "found_by": "audit", "created_at": "2026-06-12T00:00:00Z"}
        (self.job / P.REVIEW_ISSUES).write_text(json.dumps(issue) + "\n", encoding="utf-8")
        (self.job / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved([]), encoding="utf-8")
        r = run("validators/validate_unresolved.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_placeholders_require_issue_entry(self):
        self._phase("5_assembly")
        marker = "[未解析: 图片说明 - 需视觉描述]"
        (self.job / P.OUTPUT_MAIN).write_text(f"# Title　〔源 p.1〕\n\n{marker}\n", encoding="utf-8")
        (self.job / P.REVIEW_UNRESOLVED).write_text("# Unresolved\n\n图片说明 - 需视觉描述\n", encoding="utf-8")
        r = run("validators/validate_placeholders.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_table_renderer_expands_colspan(self):
        md = MD.render_table_markdown({"columns": ["A", "B", "C"], "rows": [[
            {"text": "wide", "rowspan": 1, "colspan": 2},
            {"text": "tail", "rowspan": 1, "colspan": 1},
        ]]})
        self.assertIn("| wide |  | tail |", md)

    def test_validate_tables_allows_escaped_pipe_cells(self):
        self._phase("4_audit")
        self._write_ir(cell_text="a|b")
        r = run("validators/validate_tables.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_quality_allows_anchor_after_long_table(self):
        self._phase("5_assembly")
        rows = "\n".join(f"| {i} | {i} |" for i in range(120))
        table = f"| A | B |\n| --- | --- |\n{rows}\n\n*〔源 p.2〕*"
        (self.job / P.OUTPUT_MAIN).write_text(
            "# Title　〔源 p.1〕\n\n> **摘要**\n> ok\n\n" + ("x" * 500) + "\n\n" + table + "\n",
            encoding="utf-8",
        )
        r = run("validators/validate_agent_md_quality.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_run_validators_refresh_stale_revalidates(self):
        self._phase("5_assembly")
        self._write_ir()
        main = "# Title　〔源 p.1〕\n\n> **摘要**\n> ok\n"
        (self.job / P.OUTPUT_MAIN).write_text(main, encoding="utf-8")
        first = run("tools/run_validators.py", "--job", str(self.job), "--phase", "5_assembly", "--no-advance")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        blocks = self.job / IR.IR_BLOCKS
        blocks.write_text(blocks.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        refreshed = run("tools/run_validators.py", "--job", str(self.job), "--phase", "5_assembly",
                        "--no-advance", "--refresh-stale")
        self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)

    def test_run_validators_missing_or_corrupt_state_writes_gate(self):
        (self.job / "STATE.json").unlink()
        r = run("tools/run_validators.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue((self.job / "logs/gates/gate_0_intake_run_validators_state.json").is_file())
        (self.job / "STATE.json").write_text("{bad json", encoding="utf-8")
        r = run("tools/run_validators.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
