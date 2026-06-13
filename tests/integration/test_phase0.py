"""End-to-end Phase 0: init a bundle, then run the two gates (good + bad)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"


def run(target: str, *args: str):
    return subprocess.run(
        [sys.executable, str(WRAPPER), target, *args],
        capture_output=True, text=True, encoding="utf-8",
    )


class TestPhase0EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # a source filename with a space, to exercise quoting/slug
        self.src = self.root / "sample report.md"
        self.src.write_text("# Sample\n\nHello.\n", encoding="utf-8")
        self.jobs_root = self.root / "jobs"

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self):
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs_root), "--date", "20260612")
        self.assertEqual(r.returncode, 0, r.stderr)
        job = self.jobs_root / "sample-report-20260612"
        self.assertTrue((job / "STATE.json").is_file())
        self.assertTrue((job / "output" / "manifest.json").is_file())
        self.assertTrue((job / "source" / "sample report.md").is_file())
        return job

    def test_init_then_gates_pass(self):
        job = self._init()
        r = run("validators/validate_state.py", "--job", str(job))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run("validators/validate_manifest.py", "--job", str(job), "--mode", "draft")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # gate files written with phase prefix
        self.assertTrue((job / "logs" / "gates" / "gate_0_intake_validate_state.json").is_file())

    def test_skip_violation_blocks(self):
        job = self._init()
        sf = job / "STATE.json"
        st = json.loads(sf.read_text(encoding="utf-8"))
        st["phase_status"]["3_semantic_compile"] = "done"  # illegal skip
        sf.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        r = run("validators/validate_state.py", "--job", str(job))
        self.assertEqual(r.returncode, 1, "skip violation must fail the gate")
        st2 = json.loads(sf.read_text(encoding="utf-8"))
        self.assertEqual(st2["phase_status"]["0_intake"], "failed")

    def test_missing_state_hard_fails_with_gate_result(self):
        job = self._init()
        (job / "STATE.json").unlink()
        r = run("validators/validate_state.py", "--job", str(job))
        self.assertEqual(r.returncode, 1, "missing STATE.json must hard-fail, not pass_with_notes")
        self.assertTrue((job / "logs" / "gates" / "gate_0_intake_validate_state.json").is_file(),
                        "a gate result must be written even on the missing-artifact path")

    def test_missing_manifest_hard_fails(self):
        job = self._init()
        (job / "output" / "manifest.json").unlink()
        r = run("validators/validate_manifest.py", "--job", str(job), "--mode", "draft")
        self.assertEqual(r.returncode, 1, "missing manifest must hard-fail")

    def test_existing_job_refused_without_force(self):
        self._init()
        r = run("tools/init_document_job.py", "--source", str(self.src),
                "--jobs-root", str(self.jobs_root), "--date", "20260612")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
