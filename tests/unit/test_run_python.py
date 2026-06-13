"""Regression: run_python.py target-containment must be separator-agnostic (B2).

The old guard used ``str(target).startswith(root + "/")``. On Windows paths join
with ``\\``, so that check matched nothing and the wrapper refused *every* in-repo
target — the entire pipeline was dead on Windows. These tests pin the fix by
driving the pure ``is_within_root`` predicate with both POSIX and Windows pure
paths (so they run identically on any host).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import PurePosixPath, PureWindowsPath

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "afm_run_python", PROJECT_ROOT / "scripts" / "run_python.py"
)
run_python = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_python)


class TestIsWithinRoot(unittest.TestCase):
    def test_windows_in_repo_target_accepted(self):
        root = PureWindowsPath(r"C:\repo\agent-friendly-md")
        target = PureWindowsPath(r"C:\repo\agent-friendly-md\tools\doctor.py")
        self.assertTrue(run_python.is_within_root(root, target),
                        "a Windows-style in-repo path must be accepted")

    def test_windows_root_itself_accepted(self):
        root = PureWindowsPath(r"C:\repo\agent-friendly-md")
        self.assertTrue(run_python.is_within_root(root, root))

    def test_windows_outside_target_refused(self):
        root = PureWindowsPath(r"C:\repo\agent-friendly-md")
        outside = PureWindowsPath(r"C:\repo\other\evil.py")
        self.assertFalse(run_python.is_within_root(root, outside))

    def test_windows_sibling_prefix_refused(self):
        # "agent-friendly-md-evil" shares a string prefix but is a different dir.
        root = PureWindowsPath(r"C:\repo\agent-friendly-md")
        sibling = PureWindowsPath(r"C:\repo\agent-friendly-md-evil\x.py")
        self.assertFalse(run_python.is_within_root(root, sibling))

    def test_posix_in_repo_target_accepted(self):
        root = PurePosixPath("/repo/agent-friendly-md")
        target = PurePosixPath("/repo/agent-friendly-md/validators/validate_state.py")
        self.assertTrue(run_python.is_within_root(root, target))

    def test_posix_outside_target_refused(self):
        root = PurePosixPath("/repo/agent-friendly-md")
        self.assertFalse(run_python.is_within_root(root, PurePosixPath("/etc/passwd")))

    def test_posix_sibling_prefix_refused(self):
        root = PurePosixPath("/repo/agent-friendly-md")
        self.assertFalse(run_python.is_within_root(root, PurePosixPath("/repo/agent-friendly-md-evil/x.py")))


if __name__ == "__main__":
    unittest.main()
