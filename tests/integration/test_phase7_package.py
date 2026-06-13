"""Phase 7 package gate/output tests."""
from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

from lib import hashes  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import manifest as mf  # noqa: E402
from lib import paths as P  # noqa: E402
from lib import portability  # noqa: E402


def _load_package_output():
    spec = importlib.util.spec_from_file_location("package_output", PROJECT_ROOT / "tools" / "package_output.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(target: str, *args: str):
    return subprocess.run([sys.executable, str(WRAPPER), target, *args],
                          capture_output=True, text=True, encoding="utf-8")


class TestPhase7Package(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = Path(self.tmp.name) / ".agent-friendly-md" / "jobs" / "doc-20260613"
        self.source_name = "跨资产关联入门手册.pdf"
        self.final_main = "跨资产关联入门手册.md"
        P.ensure_skeleton(self.job)
        (self.job / f"source/{self.source_name}").write_text("# Doc\n", encoding="utf-8")
        state = js.new_state(
            job_id="doc-20260613",
            source_files=[f"source/{self.source_name}"],
            job_root=str(self.job),
            primary_ext=".pdf",
        )
        idx = js.PHASES.index("7_package")
        state["current_phase"] = "7_package"
        state["phase_status"] = {ph: ("done" if i < idx else "in_progress") for i, ph in enumerate(js.PHASES)}
        js.save_state(self.job, state)
        for rel, text in {
            "output/main.md": "# Doc　〔源 p.1〕\n\n![Figure](assets/fig.png)\n",
            "output/index.md": "# Agent Index: Doc\n\n- Entry: [main.md](main.md)\n",
            "output/index.json": json.dumps({
                "schema_version": "agent-friendly-md-index/0.1",
                "title": "Doc",
                "entry": {"path": "main.md", "mode": "single_file", "approx_tokens": 10},
                "split": {"enabled": False, "parts": []},
                "stats": {},
                "parts": [],
            }) + "\n",
            "output/parts/01-doc.md": "# Part　〔源 p.1〕\n\n![Figure](../assets/fig.png)\n",
            "output/provenance.json": "{}\n",
            "output/qa_report.md": "# QA\n",
            "output/visual_acceptance.md": "# Visual\nstatus: pass\n",
            "output/unresolved.md": "# Unresolved\n\n_No unresolved issues._\n",
        }.items():
            (self.job / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.job / rel).write_text(text, encoding="utf-8")
        (self.job / "output/assets").mkdir(parents=True, exist_ok=True)
        (self.job / "output/assets/fig.png").write_bytes(b"png")
        (self.job / P.REVIEW_ISSUES).write_text("", encoding="utf-8")
        self._write_manifest_and_snapshot()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest_and_snapshot(self):
        digest = "a" * 64
        manifest = mf.new_draft(
            job_id="doc-20260613",
            document_slug="doc",
            sources=[mf.source_entry(self.job, f"source/{self.source_name}")],
            split_thresholds=js.DEFAULT_SPLIT_THRESHOLDS,
        )
        manifest["stage"] = "final"
        manifest["outputs"]["main"] = "main.md"
        manifest["outputs"]["index"] = {"markdown": "index.md", "json": "index.json"}
        manifest["outputs"]["parts"] = [{"path": "parts/01-doc.md", "title": "Part", "source_range": "p.1"}]
        manifest["outputs"]["assets"] = [{"path": "assets/fig.png"}]
        manifest["input_hashes"]["6_validation"] = digest
        manifest["output_hashes"] = {}
        for rel in (
            "output/main.md",
            "output/index.md",
            "output/index.json",
            "output/parts/01-doc.md",
            "output/assets/fig.png",
            "output/provenance.json",
            "output/qa_report.md",
            "output/visual_acceptance.md",
            "output/unresolved.md",
        ):
            manifest["output_hashes"][rel] = mf.sha256_file(self.job / rel)
        (self.job / "output/manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        (self.job / "logs/hashes/6_validation.json").write_text(
            json.dumps({
                "schema_version": hashes.HASH_SCHEMA_VERSION,
                "phase": "6_validation",
                "input_digest": digest,
                "inputs": {},
            }) + "\n",
            encoding="utf-8",
        )

    def test_package_gate_passes_ready_output(self):
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_validate_manifest_final_uses_output_relative_paths(self):
        r = run("validators/validate_manifest.py", "--job", str(self.job), "--mode", "final")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_package_gate_rechecks_phase6_snapshot_inputs(self):
        probe = self.job / "review/visual_acceptance/render_diagnostics.json"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text('{"status":"pass"}\n', encoding="utf-8")
        rel = probe.relative_to(self.job).as_posix()
        inputs = {rel: {"sha256": mf.sha256_file(probe), "bytes": probe.stat().st_size}}
        digest = hashes.aggregate_hash(inputs)
        manifest_path = self.job / "output/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["input_hashes"]["6_validation"] = digest
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        (self.job / "logs/hashes/6_validation.json").write_text(
            json.dumps({
                "schema_version": hashes.HASH_SCHEMA_VERSION,
                "phase": "6_validation",
                "input_digest": digest,
                "inputs": inputs,
            }) + "\n",
            encoding="utf-8",
        )
        probe.write_text('{"status":"fail"}\n', encoding="utf-8")
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_package_gate_blocks_open_blocker(self):
        issue = ISS.new_issue(
            issue_id="blocker_001",
            severity="blocker",
            category="table",
            source_block_id="block_table_001",
            source_anchor="〔源 p.1〕",
            issue="Blocking issue.",
            required_action="Fix it.",
            found_by="test",
        )
        ISS.write_issues(self.job / P.REVIEW_ISSUES, [issue])
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_package_gate_requires_issue_ledger_and_projection(self):
        (self.job / P.REVIEW_ISSUES).unlink()
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        issue = ISS.new_issue(
            issue_id="minor_001",
            severity="minor",
            category="formula",
            source_block_id="block_formula_001",
            source_anchor="〔源 p.1〕",
            issue="Needs review.",
            required_action="Track it.",
            found_by="test",
        )
        ISS.write_issues(self.job / P.REVIEW_ISSUES, [issue])
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_package_gate_requires_complete_output_hashes_and_links(self):
        manifest_path = self.job / "output/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["output_hashes"]["output/assets/fig.png"]
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self._write_manifest_and_snapshot()
        (self.job / "output/assets/fig.png").unlink()
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_package_gate_rejects_local_path_leaks(self):
        qa = self.job / "output/qa_report.md"
        qa.write_text("# QA\n\nleak: /Users/example/Downloads/source.pdf\n", encoding="utf-8")
        self._write_manifest_and_snapshot()
        r = run("validators/package_gate.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no_local_path_leaks", r.stdout + r.stderr)

    def test_package_output_copies_snapshot_and_refuses_overwrite(self):
        out = Path(self.tmp.name) / "pkg"
        r = run("tools/package_output.py", "--job", str(self.job), "--out", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / self.final_main).is_file())
        self.assertFalse((out / "main.md").exists())
        self.assertTrue((out / "parts/01-doc.md").is_file())
        self.assertTrue((out / "assets/fig.png").is_file())
        self.assertTrue((out / "_agent-md/package_metadata.json").is_file())
        self.assertTrue((out / "_agent-md/index.md").is_file())
        self.assertTrue((out / "_agent-md/index.json").is_file())
        self.assertTrue((out / "_agent-md/qa_report.md").is_file())
        self.assertFalse((out / "qa_report.md").exists())
        metadata = json.loads((out / "_agent-md/package_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["main"], self.final_main)
        self.assertEqual(metadata["index"], "_agent-md/index.md")
        self.assertEqual(metadata["support_dir"], "_agent-md")
        index_text = (out / "_agent-md/index.md").read_text(encoding="utf-8")
        self.assertIn(f"[{self.final_main}](../{self.final_main})", index_text)
        state = js.load_state(self.job)
        self.assertEqual(state["phase_status"]["7_package"], "done")
        second = run("tools/package_output.py", "--job", str(self.job), "--out", str(out))
        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)

    def test_default_package_name_uses_source_document_name(self):
        r = run("tools/package_output.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = Path(self.tmp.name) / "跨资产关联入门手册-agent-md"
        self.assertTrue((out / self.final_main).is_file())
        self.assertTrue((out / "assets/fig.png").is_file())

    def test_include_work_package_sanitizes_copied_logs(self):
        gate_log = self.job / "logs/gates/gate_6_validation_probe.json"
        gate_log.write_text(json.dumps({
            "phase": "6_validation",
            "gate": "probe",
            "status": "pass",
            "notes": f"read {self.job}/output/main.md",
        }) + "\n", encoding="utf-8")
        out = Path(self.tmp.name) / "pkg-work"
        r = run("tools/package_output.py", "--job", str(self.job), "--out", str(out), "--include-work")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        leaks = portability.scan_path_leaks(out)
        self.assertEqual(leaks, [])
        copied = (out / "_agent-md/work/logs/gates/gate_6_validation_probe.json").read_text(encoding="utf-8")
        self.assertIn("<job-root>", copied)

    def test_force_package_preserves_existing_target_on_copy_preflight_failure(self):
        out = Path(self.tmp.name) / "pkg"
        out.mkdir()
        (out / self.final_main).write_text("old package", encoding="utf-8")
        (self.job / "output/provenance.json").unlink()
        mod = _load_package_output()
        with self.assertRaises(FileNotFoundError):
            mod.build_package(self.job, out, include_work=False, force=True)
        self.assertEqual((out / self.final_main).read_text(encoding="utf-8"), "old package")

    def test_run_validators_phase7_records_snapshot(self):
        r = run("tools/run_validators.py", "--job", str(self.job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.job / "logs/hashes/7_package.json").is_file())


if __name__ == "__main__":
    unittest.main()
