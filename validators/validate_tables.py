#!/usr/bin/env python3
"""Phase 4 gate: validate structured tables and their Markdown projection."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import gates  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import jobstate as js  # noqa: E402
from lib import md_render as MD  # noqa: E402
from lib.gates import Check  # noqa: E402

PHASE = "4_audit"


def _cell_width(cell: dict) -> int:
    if not isinstance(cell, dict):
        return 0
    try:
        width = int(cell.get("colspan", 1))
    except (TypeError, ValueError):
        return 0
    return width if width > 0 else 0


def _row_width(row: list[dict]) -> int:
    return sum(_cell_width(c) for c in row)


def _md_col_counts(markdown: str) -> list[int]:
    counts = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            inner = stripped[1:-1]
            count, escaped = 1, False
            for ch in inner:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "|":
                    count += 1
            counts.append(count)
    return counts


def build_checks(job_root: Path) -> list[Check]:
    checks: list[Check] = []
    blocks_file = job_root / IR.IR_BLOCKS
    checks.append(Check("blocks_present", blocks_file.is_file(), message=str(blocks_file)))
    if not blocks_file.is_file():
        return checks
    try:
        blocks = IR.read_blocks(job_root)
    except (OSError, json.JSONDecodeError) as e:
        checks.append(Check("blocks_parseable", False, message=f"blocks.jsonl unreadable: {e}"))
        return checks

    tables = [b for b in blocks if b.get("type") == "table"]
    checks.append(Check("table_blocks_read", True, level="info", message=f"{len(tables)} table block(s)"))
    bad_columns: list[str] = []
    bad_rows: list[str] = []
    bad_headers: list[str] = []
    empty_waterfalls: list[str] = []
    bad_projection: list[str] = []

    for block in tables:
        bid = block.get("id", "<missing-id>")
        table = block.get("table") or {}
        columns = table.get("columns")
        rows = table.get("rows")
        if not isinstance(columns, list) or not columns:
            bad_columns.append(bid)
            continue
        if not isinstance(rows, list):
            bad_rows.append(f"{bid}: rows not list")
            continue
        expected = len(columns)
        row_bad = False
        for i, row in enumerate(rows):
            if not isinstance(row, list) or _row_width(row) != expected:
                bad_rows.append(f"{bid}[{i}]")
                row_bad = True
        header_rows = table.get("header_rows") or []
        if (not isinstance(header_rows, list)
                or any(not isinstance(i, int) or i < 0 or i >= len(rows) for i in header_rows)):
            bad_headers.append(bid)
        if rows and expected:
            blank_cols = []
            for col in range(expected):
                vals = [(row[col].get("text") if col < len(row) and isinstance(row[col], dict) else "") for row in rows]
                if all(not str(v).strip() for v in vals):
                    blank_cols.append(col + 1)
            if blank_cols and len(blank_cols) < expected:
                empty_waterfalls.append(f"{bid}: columns {blank_cols[:5]}")
        if not row_bad:
            counts = _md_col_counts(MD.render_table_markdown(table))
            if counts and any(n != expected for n in counts):
                bad_projection.append(bid)

    checks.append(Check("columns_present", not bad_columns,
                        message="all tables have columns" if not bad_columns else f"bad: {bad_columns[:5]}"))
    checks.append(Check("row_widths_match_columns", not bad_rows,
                        message="all rows match columns" if not bad_rows else f"bad rows: {bad_rows[:5]}"))
    checks.append(Check("header_rows_valid", not bad_headers,
                        message="header rows valid" if not bad_headers else f"bad: {bad_headers[:5]}"))
    checks.append(Check("no_empty_column_waterfall", not empty_waterfalls, level="warn",
                        message="none" if not empty_waterfalls else f"{empty_waterfalls[:5]}"))
    checks.append(Check("markdown_projection_columns", not bad_projection,
                        message="projection columns match" if not bad_projection else f"bad: {bad_projection[:5]}"))
    return checks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate table blocks")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)

    job_root = Path(args.job).expanduser().resolve()
    if not (job_root / "STATE.json").is_file():
        return gates.write_gate_result(
            job_root=job_root, gate_name="validate_tables", phase=PHASE,
            checks=[Check("state_present", False, message="STATE.json missing")],
        )
    return gates.write_gate_result(
        job_root=job_root, gate_name="validate_tables", phase=PHASE,
        checks=build_checks(job_root),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
