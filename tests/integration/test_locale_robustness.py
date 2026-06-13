"""Regression: the toolchain must survive a non-UTF-8 console locale (M2).

Tool output is Chinese-bearing and uses "—". On a non-UTF-8 console — Windows'
default code page, or an ``LC_ALL=C`` shell — a bare ``print``/``subprocess``
text round-trip would raise UnicodeEncode/DecodeError and kill the tool. The
wrapper forces UTF-8 on its own stdio (``scripts/run_python.py``) and every
in-repo subprocess routes through ``lib.subproc.run_text`` (UTF-8). These tests
spawn the wrapper under an ASCII locale and assert it neither crashes nor emits
mojibake.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = PROJECT_ROOT / "scripts" / "run_python.py"

ASCII_LOCALE_ENV = {
    **os.environ,
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONUTF8": "0",
    "PYTHONIOENCODING": "",
}


class TestLocaleRobustness(unittest.TestCase):
    def test_gate_emits_utf8_under_ascii_locale(self):
        # Running a gate on a STATE-less dir makes lib/gates.py print a note
        # containing "—": a deterministic non-ASCII emitter independent of repo
        # path. Capture raw bytes (no text=) to inspect the actual encoding.
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(WRAPPER), "validators/validate_state.py", "--job", tmp],
                capture_output=True,
                env=ASCII_LOCALE_ENV,
            )
        combined = proc.stdout + proc.stderr
        self.assertNotIn(b"Traceback", combined,
                         "wrapper crashed under ASCII locale:\n" + combined.decode("utf-8", "replace"))
        self.assertNotIn(b"UnicodeEncodeError", combined)
        self.assertNotIn(b"UnicodeDecodeError", combined)
        # Output must be valid UTF-8 (raises here if not) and carry the em-dash.
        text = combined.decode("utf-8")
        self.assertIn("—", text, "expected the non-ASCII em-dash note to be emitted")
        # It is a clean gate failure (exit 1), not an interpreter crash.
        self.assertEqual(proc.returncode, 1, text)

    def test_tool_run_directly_under_ascii_locale(self):
        # WORKFLOW §1 sanctions running tools directly (not via the wrapper). The
        # direct path must ALSO survive a non-UTF-8 console — lib/__init__ forces
        # UTF-8 stdio on import. doctor.py prints "—" when the path has a space.
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "doctor.py")],
            capture_output=True, env=ASCII_LOCALE_ENV,
        )
        combined = proc.stdout + proc.stderr
        self.assertNotIn(b"Traceback", combined,
                         combined.decode("utf-8", "replace"))
        self.assertNotIn(b"UnicodeEncodeError", combined)
        combined.decode("utf-8")  # must be valid UTF-8
        self.assertEqual(proc.returncode, 0, combined.decode("utf-8", "replace"))

    def test_doctor_runs_under_ascii_locale(self):
        with tempfile.TemporaryDirectory() as tmp:  # noqa: F841 - isolate cwd-independent run
            proc = subprocess.run(
                [sys.executable, str(WRAPPER), "tools/doctor.py"],
                capture_output=True,
                env=ASCII_LOCALE_ENV,
            )
        self.assertNotIn(b"Traceback", proc.stdout + proc.stderr,
                         (proc.stdout + proc.stderr).decode("utf-8", "replace"))
        # doctor exits 0 when core is satisfied; the run must not crash on output.
        self.assertEqual(proc.returncode, 0, (proc.stdout + proc.stderr).decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
