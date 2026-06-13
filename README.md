# agent-friendly-md

<div align="center">

**可追溯文档编译流水线 · 文档中间表示（IR）· 质量检查 · 视觉验收 · 可移植输出包**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)](https://www.python.org/)
[![Markdown](https://img.shields.io/badge/输出-Markdown-111111?style=flat-square)](README.md)
[![IR](https://img.shields.io/badge/核心-Document%20IR-5B5BD6?style=flat-square)](docs/ir-schema.md)
[![QA](https://img.shields.io/badge/质量-视觉验收%20%2B%20溯源-0F766E?style=flat-square)](docs/quality-standards.md)

</div>

## 目录

- [适合什么场景](#适合什么场景)
- [核心设计](#核心设计)
- [产物长什么样](#产物长什么样)
- [安装与自检](#安装与自检)
- [最小运行方式](#最小运行方式)
- [Agent 操作约定](#agent-操作约定)
- [测试](#测试)
- [仓库地图](#仓库地图)
- [当前边界](#当前边界)

把 PDF、DOCX、PPTX、XLSX、Markdown、TXT 等源文档，编译成适合人和 Agent 共同使用的
Markdown 知识包。

它不是一次性抽文本脚本，也不是把文件丢给模型后“看起来像 Markdown”就结束。这个仓库关心的是一件更踏实的事：
转换结果能不能追到来源，能不能复查，能不能交给下一位人或 Agent 继续加工。

完整流程会依次完成源文件建档、内容提取、文档中间表示（IR）建模、结构整理、质量检查、视觉验收和最终打包。
每一步都有明确产物、验证步骤、内容指纹和停止条件。

## 适合什么场景

适合：

- 把长 PDF、Word、PPT、Excel 或混合资料整理成可阅读、可引用、可继续加工的 Markdown。
- 需要保留表格、公式、图片、图注、页码、幻灯片页码、表格区域和内容块级溯源信息。
- 输出会被其他 Agent、研究流程、审阅流程或知识库继续使用。
- 转换结果需要质量报告、视觉验收、未解决问题清单和可移植输出包。

不适合：

- 只想快速看一眼正文、做摘要或跑一次粗略 OCR。
- 不关心溯源信息、视觉证据、验证步骤、输出包或后续复查。
- 期待工具自动替代人或 Agent 对复杂图表、扫描件和语义结构的判断。

如果你只要快速提取，请直接说明“只要粗提取/预览/摘要”。否则，在本仓库上下文中对支持格式说
“转成 md”，默认会走完整 0-7 阶段流程。

## 核心设计

- **文档中间表示（IR）是唯一正文载体**：正文内容块进入 `ir/blocks.jsonl`，其他索引、资产和溯源信息都从它派生，避免多份正文互相漂移。
- **内容块级溯源**：重要内容块尽量保留来源信息，支持从最终 Markdown 追到源页、幻灯片、表格区域或原始资产。
- **验证优先于赶进度**：验证失败、内容指纹过期、缺少视觉证据、泄露本机路径、存在未关闭的阻塞问题，都会停止流程。
- **视觉验收是正式阶段**：第 6 阶段会生成渲染截图、页面汇总图、源文档对照证据、质量报告和未解决事项。
- **输出包可移植**：最终输出使用相对路径，读者入口、资产、拆分文件和 `_agent-md/` 证据目录一起交付。
- **方便 Agent 接手**：角色说明、运行手册、状态文件、问题台账和机器可读清单，让下一位操作者能从中断处恢复，而不是重新猜。

## 产物长什么样

第 7 阶段默认以源文档名生成一个 `*-agent-md/` 输出包：

```text
<源文件名>-agent-md/
├── <源文件名>.md                  # 面向读者的 Markdown
├── assets/                         # Markdown 实际引用的图片和资产
├── parts/                          # 拆分输出时出现
└── _agent-md/
    ├── index.md                    # 输出包说明
    ├── index.json                  # 机器可读索引
    ├── manifest.json
    ├── provenance.json
    ├── qa_report.md
    ├── visual_acceptance.md
    ├── unresolved.md
    └── package_metadata.json
```

读者通常先看根目录 Markdown；审阅者和 Agent 再进入 `_agent-md/` 查看证据、状态、质量报告和未解决事项。

## 安装与自检

建议使用 Python 3.10+ 和项目虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

安装视觉验收所需浏览器：

```bash
python -m playwright install chromium
```

还需要系统安装 `pandoc`。如果文档包含 Mermaid，建议安装 `@mermaid-js/mermaid-cli`。
公式渲染资产已随仓库放在 [vendor/katex/](vendor/katex/)，第 1 阶段提取后端已随仓库放在
[vendor/doc-to-agent-markdown/](vendor/doc-to-agent-markdown/)，因此完整流程不依赖外部技能目录。

开始正式任务前，先从仓库根目录运行严格自检：

```bash
python3 scripts/run_python.py tools/doctor.py --strict
```

`--strict` 要求 `core`、`extract`、`visual` 三组就绪。若任何一组 `NOT READY`，先按自检输出补齐依赖。

## 最小运行方式

创建任务目录：

```bash
python3 scripts/run_python.py tools/init_document_job.py --source "<源文件路径>"
```

然后按阶段生产产物并运行验证。常规顺序见下方；更完整的操作细节、停机条件和恢复规则见
[docs/runbook.md](docs/runbook.md)。

```bash
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/run_extraction.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/build_ir.py --job "<任务目录>"
python3 scripts/run_python.py tools/link_assets.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/compile_structure.py --job "<任务目录>"
python3 scripts/run_python.py tools/normalize_tables.py --job "<任务目录>"
python3 scripts/run_python.py tools/normalize_formulas.py --job "<任务目录>"
python3 scripts/run_python.py tools/semanticize_figures.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/run_audits.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/assemble_agent_md.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/build_visual_review_packet.py --job "<任务目录>"
python3 scripts/run_python.py tools/run_validators.py --job "<任务目录>"

python3 scripts/run_python.py tools/package_output.py --job "<任务目录>"
```

所有命令都应从仓库根目录执行，并通过 `scripts/run_python.py` 进入工具。路径含空格或中文时，请把
`<源文件路径>` / `<任务目录>` 整体加引号。

## Agent 操作约定

Agent 进入本仓库后先读：

1. [README.md](README.md)
2. [docs/runbook.md](docs/runbook.md)

只有在需要实现细节、验证调试、IR 判断或质量标准时，再读：

- [docs/design/WORKFLOW.md](docs/design/WORKFLOW.md)
- [docs/ir-schema.md](docs/ir-schema.md)
- [docs/quality-standards.md](docs/quality-standards.md)
- [docs/design/](docs/design/)

完整触发规则、停止条件和汇报字段见 [AGENTS.md](AGENTS.md)。原则上：不绕过验证，不删除源文件，不删除任务目录，
不把缺失证据包装成成功。

## 测试

```bash
python3 scripts/run_python.py tests/run_tests.py
PYTHONUTF8=0 LC_ALL=C LANG=C python3 scripts/run_python.py tests/run_tests.py
```

测试覆盖 0-7 阶段、Windows/POSIX 路径处理、非 UTF-8 运行环境、视觉验证、输出包验证、质量基线和关键回归。
发布前建议两组都跑绿。

## 仓库地图

- [AGENTS.md](AGENTS.md)：Agent 身份、默认触发规则、最小阅读顺序、停止条件和汇报要求。
- [docs/runbook.md](docs/runbook.md)：日常运行入口，包含 0-7 阶段、失败恢复、人工必做步骤和最终汇报格式。
- [docs/runtime.md](docs/runtime.md)：Python、系统工具、依赖安装和自检说明。
- [docs/ir-schema.md](docs/ir-schema.md)：文档中间表示（IR）、内容块结构、来源定位和资产命名。
- [docs/quality-standards.md](docs/quality-standards.md)：Markdown 质量标准、视觉验收和复杂内容处理准则。
- [docs/design/](docs/design/)：设计基线与历史上下文。它是设计档案，不是日常运行入口。
- [tools/](tools/)：各阶段生产工具。
- [validators/](validators/)：链接、溯源、质量、输出包等验证器。
- [roles/](roles/)：0-7 阶段的 Agent 角色说明。
- [vendor/](vendor/)：随仓库携带的提取后端与 KaTeX 资产。

## 当前边界

- 对纯扫描件，当前流程更强调整页渲染、视觉审阅、来源标注和低置信提示；全文 OCR 不是默认硬承诺。
- 复杂图表、公式、版面语义和跨页结构仍需要 Agent 按质量标准审阅，不能只信自动转换。
- 完整流程偏重可追溯和可复查，速度会慢于普通文本抽取。
- `docs/design/` 保留设计与历史脉络；面向日常使用和 GitHub 读者时，以本 README 与运行手册为准。
