"""Doctor readiness mode tests."""
from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_doctor():
    spec = importlib.util.spec_from_file_location("doctor", PROJECT_ROOT / "tools" / "doctor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDoctorStrictMode(unittest.TestCase):
    def test_default_requires_only_core(self):
        doctor = _load_doctor()
        report = {
            "python": "3.13",
            "python_executable": "/python",
            "project_root": str(PROJECT_ROOT),
            "checks": [],
            "readiness": {"core": True, "extract": False, "visual": False},
        }
        with mock.patch.object(doctor, "gather", return_value=report), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main([]), 0)

    def test_strict_requires_full_workflow(self):
        doctor = _load_doctor()
        report = {
            "python": "3.13",
            "python_executable": "/python",
            "project_root": str(PROJECT_ROOT),
            "checks": [],
            "readiness": {"core": True, "extract": True, "visual": False},
        }
        with mock.patch.object(doctor, "gather", return_value=report), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(["--strict"]), 1)

        report["readiness"]["visual"] = True
        with mock.patch.object(doctor, "gather", return_value=report), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(["--require", "full", "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
