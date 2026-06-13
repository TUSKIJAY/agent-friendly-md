#!/usr/bin/env python3
"""Environment doctor (PLAN §8).

    python3 scripts/run_python.py tools/doctor.py [--json] [--strict]

Checks the toolchain and reports readiness per phase group:

- core    (v0.1 runtime)        : Python >= 3.10
- extract (Phase 1)             : python-docx, PyMuPDF, openpyxl, python-pptx, Pillow
- visual  (Phase 6 / v0.8)      : pandoc, Playwright+Chromium (browser, not just the
                                  pip module), Mermaid CLI (mmdc), offline formula
                                  assets (vendored MathJax/KaTeX)
- optional                      : pandas, OCR engines (tesseract, paddleocr)

By default, exit 0 if the core group is satisfied (missing optional/phase deps
are warnings, not failures — v0.1 only requires that they can be *detected*).
With --strict / --require full, exit non-zero unless core, extract, and visual
are all ready.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib import backend as backend_lib  # noqa: E402
from lib import subproc  # noqa: E402

MIN_PY = (3, 10)

# Candidate locations for vendored offline formula-render assets (PLAN §8 wants
# doctor to detect whether formula rendering can work offline). Bundling these
# is a v0.8 task; v0.1 just needs to detect their presence/absence.
FORMULA_ASSET_CANDIDATES = [
    PROJECT_ROOT / "vendor" / "katex",
    PROJECT_ROOT / "vendor" / "mathjax",
    PROJECT_ROOT / "assets" / "katex",
    PROJECT_ROOT / "assets" / "mathjax",
]


def _mod(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _cmd_version(name: str, *args: str) -> str:
    exe = shutil.which(name)
    if not exe:
        return ""
    try:
        out = subproc.run_text([exe, *args], capture_output=True, timeout=15)
        text = out.stdout or out.stderr
        return text.strip().splitlines()[0] if text.strip() else exe
    except (OSError, subprocess.SubprocessError):
        return exe


def _playwright_browsers_dir() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        return Path(env)
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", str(home))) / "ms-playwright"
    return home / ".cache" / "ms-playwright"


def _playwright_status() -> tuple[bool, str]:
    """ok only when the Chromium *browser* is installed, not just the pip module."""
    if not _mod("playwright"):
        return False, "missing (pip install playwright && python -m playwright install chromium)"
    d = _playwright_browsers_dir()
    try:
        has_chromium = d.is_dir() and any(p.name.startswith("chromium") for p in d.iterdir())
    except OSError:
        has_chromium = False
    if has_chromium:
        return True, f"module + chromium @ {d}"
    return False, "module ok but Chromium browser missing (python -m playwright install chromium)"


def _mermaid_status() -> tuple[bool, str]:
    """ok when an offline Mermaid renderer (mmdc) is resolvable."""
    exe = shutil.which("mmdc")
    if exe:
        return True, f"mmdc @ {exe}"
    local = PROJECT_ROOT / "node_modules" / ".bin" / "mmdc"
    if local.exists():
        return True, f"mmdc @ {local}"
    if shutil.which("npx"):
        return False, "mmdc not found; npx present (npm i -g @mermaid-js/mermaid-cli, or vendor locally)"
    return False, "missing (need node/npx + @mermaid-js/mermaid-cli)"


def _formula_assets_status() -> tuple[bool, str]:
    for cand in FORMULA_ASSET_CANDIDATES:
        try:
            if cand.is_dir() and any(cand.iterdir()):
                return True, f"offline assets @ {cand}"
        except OSError:
            continue
    return False, "missing (vendor KaTeX/MathJax under vendor/katex for offline formula render)"


def gather() -> dict:
    pyok = sys.version_info[:2] >= MIN_PY
    checks: list[dict] = []

    def add(group, name, ok, detail, blocking=False):
        checks.append({"group": group, "name": name, "ok": bool(ok),
                       "detail": detail, "blocking": blocking})

    add("core", "python>=3.10",
        pyok, f"{sys.version.split()[0]} @ {sys.executable}", blocking=True)
    has_space = " " in str(PROJECT_ROOT)
    add("core", "project path has no spaces", not has_space,
        str(PROJECT_ROOT) + ("  [!] contains a space — always quote paths" if has_space else ""))

    for mod, label in [("docx", "python-docx"), ("fitz", "PyMuPDF"),
                       ("openpyxl", "openpyxl"), ("pptx", "python-pptx"),
                       ("PIL", "Pillow")]:
        present = _mod(mod)
        add("extract", label, present, "import ok" if present else "missing")
    backend_ok, backend_detail = backend_lib.check_available()
    add("extract", "doc-to-agent-markdown backend", backend_ok,
        backend_detail if backend_ok
        else f"{backend_detail} — vendored at vendor/doc-to-agent-markdown, "
             "or set AFM_BACKEND_DIR / pass --backend")

    pandoc_v = _cmd_version("pandoc", "--version")
    add("visual", "pandoc", bool(pandoc_v), pandoc_v or "missing")
    node_v = _cmd_version("node", "--version")
    add("visual", "node", bool(node_v), node_v or "missing")
    pw_ok, pw_detail = _playwright_status()
    add("visual", "playwright+chromium", pw_ok, pw_detail)
    mer_ok, mer_detail = _mermaid_status()
    add("visual", "mermaid (mmdc)", mer_ok, mer_detail)
    fa_ok, fa_detail = _formula_assets_status()
    add("visual", "formula assets (offline)", fa_ok, fa_detail)

    add("optional", "pandas", _mod("pandas"), "import ok" if _mod("pandas") else "missing (optional)")
    tess = shutil.which("tesseract")
    add("optional", "tesseract (OCR)", bool(tess), tess or "missing (optional)")
    add("optional", "paddleocr (OCR)", _mod("paddleocr"),
        "import ok" if _mod("paddleocr") else "missing (optional)")

    def group_ready(group: str) -> bool:
        return all(c["ok"] for c in checks if c["group"] == group)

    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "project_root": str(PROJECT_ROOT),
        "checks": checks,
        "readiness": {
            "core": pyok,  # path-space is a warning, not a blocker
            "extract": group_ready("extract"),
            "visual": group_ready("visual"),
        },
    }


def render(report: dict) -> None:
    print("agent-friendly-md doctor")
    print(f"  python      : {report['python']}  ({report['python_executable']})")
    print(f"  project root: {report['project_root']}")
    print()
    for group in ("core", "extract", "visual", "optional"):
        group_checks = [c for c in report["checks"] if c["group"] == group]
        if not group_checks:
            continue
        print(f"  [{group}]")
        for c in group_checks:
            mark = "ok " if c["ok"] else "MISS"
            flag = " *blocking*" if (c["blocking"] and not c["ok"]) else ""
            print(f"    {mark} {c['name']:<28} {c['detail']}{flag}")
    print()
    r = report["readiness"]
    print("  readiness:")
    print(f"    core    (v0.1 runtime) : {'READY' if r['core'] else 'NOT READY'}")
    print(f"    extract (Phase 1)      : {'ready' if r['extract'] else 'backend missing or extract deps not installed — see [extract] checks above'}")
    print(f"    visual  (Phase 6/v0.8) : {'ready' if r['visual'] else 'install pandoc/playwright/mermaid + formula assets before visual acceptance'}")


def _required_groups(require: str) -> tuple[str, ...]:
    if require == "full":
        return ("core", "extract", "visual")
    return (require,)


def _ready(report: dict, require: str) -> bool:
    readiness = report["readiness"]
    return all(bool(readiness.get(group)) for group in _required_groups(require))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Check the agent-friendly-md toolchain.")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--strict", action="store_true",
                    help="require core, extract, and visual readiness (alias for --require full)")
    ap.add_argument("--require", choices=["core", "extract", "visual", "full"], default="core",
                    help="readiness group required for exit 0 (default: core)")
    args = ap.parse_args(argv)

    report = gather()
    require = "full" if args.strict else args.require
    report["required_readiness"] = require
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render(report)
    return 0 if _ready(report, require) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
