# Design Docs

这是 agent-friendly-md 的设计/规划文档区；根目录 README 面向使用，本目录保留设计依据和里程碑上下文。

## 索引

- [PLAN.md](./PLAN.md)：v3 冻结设计基线。
- [IR Schema](../ir-schema.md)：Document IR、block schema、source anchor、资产命名。
- [Quality Standards](../quality-standards.md)：最终 Agent Markdown 的质量标准和视觉验收强度。
- [Migration From Skill](../migration-from-skill.md)：从原 skill 到本工作流的迁移映射。
- [WORKFLOW](./WORKFLOW.md)：当前执行契约；若与设计基线冲突，以 WORKFLOW 为准。
- [Roles](../../roles/)：Phase 0→7 的角色指令。

代码与文档中的 `PLAN §N` 指本目录 [PLAN.md](./PLAN.md) 的对应章节，作为设计 rationale 和溯源编号。

## 一句话标准

> 忠实原文、清除噪声、结构重建、视觉可验、来源可追、低置信度可见。

## 阶段模型概览

| Phase | 名称 | 主要角色 | 主要结果 |
| --- | --- | --- | --- |
| 0 | Intake | `00-intake-curator.md` | 创建 job bundle、draft manifest、STATE |
| 1 | Extraction | `01-extraction-engineer.md` | 提取文本、页面、图片、表格、质量报告 |
| 2 | IR Build | `02-ir-architect.md` | 构建 Document IR 和可再生成投影 |
| 3 | Semantic Compile | `03-semantic-compiler.md` | 重建标题、表格、公式、图像语义 |
| 4 | Audit | `04-audit-reviewer.md` | 专项审计与 unresolved ledger |
| 5 | Assembly | `05-agent-md-editor.md` | 生成 `output/main.md`、agent index、parts、assets、provenance |
| 6 | Validation | `06-qa-visual-reviewer.md` | 视觉验收包、QA 报告、final manifest |
| 7 | Package | `07-package-operator.md` | 输出 `<source-document-stem>-agent-md/` |

完整 gate 与产物契约见 [WORKFLOW](./WORKFLOW.md)。

## 目录结构

| 路径 | 用途 |
| --- | --- |
| `lib/` | 共享内部模块：phase 枚举、gate 协议、STATE/manifest 形态、IR IO、资产命名等 |
| `scripts/run_python.py` | wrapper 入口 |
| `tools/` | 各 phase 的执行工具 |
| `validators/` | 各 phase 的 gate |
| `templates/` | STATE / manifest / main / unresolved / qa / visual_acceptance 模板 |
| `roles/` | Phase 0→7 的角色指令 |
| `docs/` | IR schema、运行时、质量标准、backend 迁移和设计归档 |
| `tests/` | 单元、集成、视觉与可移植性回归测试 |
| `examples/` | 脱敏后的 synthetic 输出子集 |
| `hooks/` | v1 之后的可选增强说明 |
| `vendor/` | vendored 提取后端、KaTeX 等离线依赖资产 |

## 里程碑与当前进度

- **v0.1→v1.0 已实现**：Phase 0→7 全链路、Document IR、Asset 绑定、语义编译、
  validators/unresolved、hash 失效检测、视觉验收、专项审计、golden quality 检查、最终 package。
- 当前测试：`python3 scripts/run_python.py tests/run_tests.py` 全绿（167 项；含 Windows 路径、视觉 gate、
  非 UTF-8 locale 等可移植性回归），在 `PYTHONUTF8=0 LC_ALL=C` 下亦应全绿。
- Phase 1 提取后端已 vendor 在 `vendor/doc-to-agent-markdown/`，`lib/backend.py` 默认指向它；可用
  `AFM_BACKEND_DIR` 或各工具 `--backend` 覆盖到更新的工作副本。
- ZHCAEJ4/TAA5212 等大体积厂商源文档不进仓库；用 `tools/check_golden_quality.py` 在本机真实 job 上固化质量标准。
