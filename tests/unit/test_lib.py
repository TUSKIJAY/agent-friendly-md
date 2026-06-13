"""Unit tests for the shared lib contract (phase enum, gates, state, manifest)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import jobstate as js
from lib import gates
from lib.gates import Check
from lib import manifest as mf


def _load_init():
    spec = importlib.util.spec_from_file_location(
        "init_document_job", PROJECT_ROOT / "tools" / "init_document_job.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSlugify(unittest.TestCase):
    def setUp(self):
        self.slugify = _load_init().slugify

    def test_ascii(self):
        self.assertEqual(self.slugify("Sample Report"), "sample-report")

    def test_keeps_hyphen_underscore(self):
        self.assertEqual(self.slugify("a_b-c"), "a_b-c")

    def test_collapses_runs(self):
        self.assertEqual(self.slugify("a   b...c"), "a-b-c")

    def test_chinese_falls_back(self):
        # all-non-ascii collapses to nothing -> fallback
        self.assertEqual(self.slugify("数据手册"), "doc")

    def test_mixed(self):
        self.assertEqual(self.slugify("TAC5x1x 数据手册"), "tac5x1x")


class TestState(unittest.TestCase):
    def test_new_state_shape(self):
        st = js.new_state(
            job_id="x-20260612", source_files=["source/x.pdf"],
            job_root="/tmp/x", primary_ext=".pdf",
        )
        self.assertEqual(st["schema_version"], js.STATE_SCHEMA_VERSION)
        self.assertEqual(st["current_phase"], "0_intake")
        self.assertEqual(set(st["phase_status"]), set(js.PHASES))
        self.assertEqual(st["phase_status"]["0_intake"], "in_progress")
        self.assertTrue(all(v == "pending" for k, v in st["phase_status"].items() if k != "0_intake"))
        self.assertEqual(st["document_profile"]["profile_status"], "provisional")
        self.assertIn(st["document_profile"]["risk_level"], js.RISK_LEVELS)
        self.assertIn("split_thresholds", st["config"])

    def test_phase_enum_unique_and_ordered(self):
        self.assertEqual(len(js.PHASES), len(set(js.PHASES)))
        self.assertEqual(js.PHASES[0], "0_intake")
        self.assertEqual(js.PHASES[-1], "7_package")

    def test_intake_risk(self):
        self.assertEqual(js.intake_risk_for(".md"), "low")
        self.assertEqual(js.intake_risk_for(".pdf"), "medium")
        self.assertEqual(js.intake_risk_for(".unknown"), "medium")


class TestGates(unittest.TestCase):
    def test_decide_exit_pass(self):
        self.assertEqual(gates.decide_exit([Check("a", True)]), gates.EXIT_PASS)

    def test_decide_exit_fail_on_error(self):
        self.assertEqual(
            gates.decide_exit([Check("a", False, level="error")]), gates.EXIT_FAIL
        )

    def test_decide_exit_notes_on_warn(self):
        self.assertEqual(
            gates.decide_exit([Check("a", False, level="warn")]),
            gates.EXIT_PASS_WITH_NOTES,
        )

    def test_error_dominates_warn(self):
        self.assertEqual(
            gates.decide_exit([Check("a", False, level="warn"),
                               Check("b", False, level="error")]),
            gates.EXIT_FAIL,
        )

    def test_info_never_blocks(self):
        self.assertEqual(
            gates.decide_exit([Check("a", False, level="info")]), gates.EXIT_PASS
        )

    def test_bad_level_raises(self):
        with self.assertRaises(ValueError):
            Check("a", True, level="bogus")


class TestManifest(unittest.TestCase):
    def test_new_draft_shape(self):
        d = mf.new_draft(
            job_id="x-1", document_slug="x",
            sources=[{"path": "source/x.pdf", "bytes": 1, "sha256": "0" * 64}],
            split_thresholds=js.DEFAULT_SPLIT_THRESHOLDS,
        )
        self.assertEqual(d["schema_version"], mf.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(d["stage"], "draft")
        self.assertEqual(d["outputs"]["main"], None)
        self.assertIn("thresholds", d["split"])


if __name__ == "__main__":
    unittest.main()
