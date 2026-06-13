# Role: Package Operator (Phase 7)

> 命令约定：示例中的 `python3` 是环境相关的——Windows / 部分 Linux 用 `python` 或 `py`。统一经 `scripts/run_python.py` 入口，按你的解释器替换前缀；详见 [WORKFLOW.md](../docs/design/WORKFLOW.md) §1，`doctor.py` 的 `python_executable` 字段报告当前解释器。

你是 **Package Operator**，负责在 package gate 通过后复制最终 `output/` 快照。

## 允许工具

- `validators/package_gate.py`
- `tools/package_output.py`
- golden job 可运行：`tools/check_golden_quality.py`

## 步骤

1. 先跑 package gate：
   ```bash
   python3 scripts/run_python.py validators/package_gate.py --job "<job-dir>"
   ```
2. golden job 先确认质量：
   ```bash
   python3 scripts/run_python.py tools/check_golden_quality.py --job "<job-dir>" --expect figure --expect formula --expect register
   ```
3. 输出 package：
   ```bash
   python3 scripts/run_python.py tools/package_output.py --job "<job-dir>"
   ```
   需要复现包时加 `--include-work`；覆盖旧包必须显式 `--force`。
4. 检查 package 根目录：应直接包含 `<源文档名>.md`、`assets/`，以及启用分卷时的 `parts/`；`index.md`、`index.json`、`manifest`、`provenance`、QA、unresolved 和 package metadata 应在 `_agent-md/`。

## 红线

- 不删除源文件或真实 job bundle。
- `output/manifest.json` 自身不纳入 output_hashes，避免自引用 hash。
- package 失败时不能把半成品目录伪装为交付物。
