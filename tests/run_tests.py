#!/usr/bin/env python3
"""Run the v0.x test suite (stdlib unittest; no third-party deps).

    python3 scripts/run_python.py tests/run_tests.py
    # or directly:
    python3 tests/run_tests.py

Discovers tests/unit and tests/integration. Exits non-zero on any failure so
it can gate a commit.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for sub in ("unit", "integration"):
        d = PROJECT_ROOT / "tests" / sub
        if d.is_dir():
            suite.addTests(loader.discover(str(d), pattern="test_*.py", top_level_dir=str(PROJECT_ROOT)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
