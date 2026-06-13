#!/usr/bin/env python3
"""Phase 4 audit: hard-table checks for registers, parameters, and quotes."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import anchors  # noqa: E402
from lib import ir as IR  # noqa: E402
from lib import issues as ISS  # noqa: E402
from lib import paths as P  # noqa: E402

FOUND_BY = "audit_tables.py"
HEX_RE = re.compile(r"^(0x[0-9a-f]+|[0-9a-f]{2,}h|[0-9]+)$", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text).lower())


def _row_width(row: list[dict]) -> int:
    total = 0
    for cell in row:
        if not isinstance(cell, dict):
            return -1
        try:
            total += int(cell.get("colspan", 1))
        except (TypeError, ValueError):
            return -1
    return total


def _match_col(columns: list[str], words: tuple[str, ...]) -> int | None:
    for idx, col in enumerate(columns):
        n = _norm(col)
        if any(w in n for w in words):
            return idx
    return None


def _classify(title: str, columns: list[str]) -> tuple[str, dict[str, int | None]]:
    hay = _norm(title + " " + " ".join(columns))
    reg_mapping = {
        "address": _match_col(columns, ("address", "addr", "地址")),
        "name": _match_col(columns, ("register", "reg", "寄存器", "name", "名称")),
        "description": _match_col(columns, ("description", "desc", "说明", "描述")),
        "reset": _match_col(columns, ("reset", "default", "复位", "默认")),
    }
    if reg_mapping["address"] is not None and any(
        reg_mapping[k] is not None for k in ("name", "description", "reset")
    ):
        return "register", reg_mapping
    if any(w in hay for w in ("parameter", "electrical", "参数", "特性")):
        mapping = {
            "parameter": _match_col(columns, ("parameter", "参数", "characteristic", "特性")),
            "unit": _match_col(columns, ("unit", "单位")),
            "limit": _match_col(columns, ("min", "typ", "max", "最小", "典型", "最大")),
        }
        return "parameter", mapping
    if any(w in hay for w in ("quote", "price", "报价", "单价", "金额")):
        mapping = {
            "item": _match_col(columns, ("item", "part", "物料", "项目", "名称")),
            "quantity": _match_col(columns, ("qty", "quantity", "数量")),
            "unit_price": _match_col(columns, ("unitprice", "price", "单价")),
            "amount": _match_col(columns, ("amount", "total", "金额", "小计")),
        }
        return "quote", mapping
    return "generic", {}


def _cell_text(row: list[dict], idx: int | None) -> str:
    if idx is None or idx >= len(row) or not isinstance(row[idx], dict):
        return ""
    return str(row[idx].get("text", "")).strip()


def _issue(block: dict, code: str, severity: str, text: str, action: str) -> dict:
    return ISS.new_issue(
        issue_id=f"table_{block.get('id', 'missing')}_{code}",
        severity=severity,
        category="table",
        source_block_id=str(block.get("id", "")),
        source_anchor=anchors.format_anchor(block.get("source_anchor")),
        issue=text,
        required_action=action,
        found_by=FOUND_BY,
    )


def audit_blocks(blocks: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for block in [b for b in blocks if b.get("type") == "table"]:
        table = block.get("table") or {}
        columns = table.get("columns") if isinstance(table.get("columns"), list) else []
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        kind, mapping = _classify(str(block.get("title", "")), [str(c) for c in columns])
        audit = table.setdefault("audit", {})
        audit["hard_table_type"] = kind
        audit["column_roles"] = mapping
        expected = len(columns)
        bad_rows = [i + 1 for i, row in enumerate(rows) if not isinstance(row, list) or _row_width(row) != expected]
        missing_roles = [role for role, idx in mapping.items() if idx is None]
        audit["row_width_check"] = "fail" if bad_rows else "pass"
        audit["hard_column_check"] = "fail" if missing_roles else "pass"
        if kind != "generic" and missing_roles:
            findings.append(_issue(
                block, "missing_required_columns", "major",
                f"{kind} table is missing required semantic columns: {', '.join(missing_roles)}.",
                "Compare the table against the source and add/rename the missing hard columns.",
            ))
        if bad_rows:
            findings.append(_issue(
                block, "row_width_mismatch", "major",
                f"Structured rows do not match the declared column count: rows {bad_rows[:10]}.",
                "Rebuild or manually correct the structured table rows before packaging.",
            ))
        if kind == "register" and mapping.get("address") is not None and rows:
            addr_idx = mapping["address"]
            bad_addr = [i + 1 for i, row in enumerate(rows)
                        if isinstance(row, list) and _cell_text(row, addr_idx)
                        and not HEX_RE.match(_cell_text(row, addr_idx))]
            audit["register_address_check"] = "fail" if bad_addr else "pass"
            if bad_addr:
                findings.append(_issue(
                    block, "register_address_format", "major",
                    f"Register address cells look non-address-like in rows {bad_addr[:10]}.",
                    "Check address column OCR against the source register table.",
                ))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Audit hard tables and write review/issues.jsonl.")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_root = Path(args.job).expanduser().resolve()
    try:
        blocks, doc = IR.load_ir(job_root)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] IR unreadable: {e}", file=sys.stderr)
        return 1
    findings = audit_blocks(blocks)
    IR.save_all(job_root, blocks, doc)
    issues, errors = ISS.upsert_generated(job_root / P.REVIEW_ISSUES, FOUND_BY, findings)
    unresolved = ISS.unresolved_entries(issues)
    (job_root / P.REVIEW_UNRESOLVED).write_text(ISS.render_unresolved(unresolved), encoding="utf-8")
    print(f"[ok] audit_tables: findings={len(findings)}")
    if errors:
        print(f"[warn] preserved existing issue parse errors: {errors[:3]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
