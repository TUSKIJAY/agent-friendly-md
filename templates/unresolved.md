# Unresolved

> 机器可判定的未决问题清单。`unresolved.md` 是 `review/issues.jsonl` 中未关闭问题的人读投影；
> 字段口径以 issues.jsonl 条目为准（见 WORKFLOW.md「issues.jsonl 条目 schema」）。
> `package_gate.py` 据此判定能否打包。

## unresolved_001

- severity: blocker | major | minor | info
- status: open | accepted | fixed
- accepted_by: ""
- accepted_reason: ""
- source_block_id: block_table_003
- source_anchor: p.12
- category: ocr | table | formula | figure | provenance | source_conflict | rendering
- issue: 表格第 4 列疑似跨页错位。
- required_action: 人工核对源页 p.12-p.13。
