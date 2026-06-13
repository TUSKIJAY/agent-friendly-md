# WORKFLOW

agent-friendly-md 的执行契约。[PLAN.md](./PLAN.md)（v3，已冻结）是设计基线；本文件把 review-003
要求落定的 gate 协议与产物契约固化为可执行规则。冲突时以本文件为准。

> 适用范围：阶段模型、命令形态、gate 协议、产物晋升、hash 失效检测、job bundle 目录、
> issues.jsonl 条目 schema。IR 内部结构见 [docs/ir-schema.md](../ir-schema.md)。

---

## 1. 命令形态

所有命令在**项目根目录** `agent-friendly-md/` 执行，统一通过 wrapper 入口，传入**项目内相对路径**：

```bash
# POSIX（本机 python 命令名为 python3）
python3 scripts/run_python.py tools/init_document_job.py --source "<file>"
python3 scripts/run_python.py validators/validate_state.py --job "<job-dir>"
python3 scripts/run_python.py tools/doctor.py
```

Windows PowerShell 等价写法：

```powershell
python scripts\run_python.py tools\init_document_job.py --source "<file>"
python scripts\run_python.py validators\validate_state.py --job "<job-dir>"
```

约定：

- wrapper 接收项目内相对路径，**禁止**要求调用者从父目录传入 `agent-friendly-md/tools/...`。
- wrapper 拒绝逃逸出项目根的目标路径。
- 路径含空格时必须加引号（`doctor.py` 会对含空格的项目路径给出非阻断警告）。
- 工具也可直接运行（`python3 tools/xxx.py`）；每个工具自带 sys.path bootstrap，两种方式都能 `import lib`。
- 命令前缀 `python3` 是**环境相关**的：Windows / 部分 Linux 用 `python` 或 `py`（见上方 PowerShell 等价写法）。
  `doctor.py`（及 `--json` 输出的 `python_executable` 字段）报告当前解释器；文档与角色示例里的 `python3` 按此替换。
  含中文/`—` 的输出在非 UTF-8 控制台（Windows 默认代码页、`LC_ALL=C`）也不会崩：wrapper 强制其 stdout/stderr 为 UTF-8，
  直接运行（`python3 tools/x.py`）时由 `lib/__init__`（`lib.subproc.force_utf8_stdio`）在 import 时同样强制，
  子进程统一经 `lib/subproc.run_text`（UTF-8）。

---

## 2. 唯一阶段模型

阶段枚举是唯一的，定义在 `lib/jobstate.py:PHASES`，所有工具、validator、STATE 共用。

| Phase | 名称 | 角色 | 必产物 | Gate |
| --- | --- | --- | --- | --- |
| 0 | Intake | `00-intake-curator.md` | `STATE.json`、`output/manifest.json`(draft) | `validate_state.py`、`validate_manifest.py --mode draft` |
| 1 | Extraction | `01-extraction-engineer.md` | `extracted/`、`extracted/extract_meta.json` | `validate_extraction.py` |
| 2 | IR Build | `02-ir-architect.md` | `ir/document.ir.json`、`ir/blocks.jsonl`、`ir/assets.index.json`、`ir/provenance.json` | `validate_ir.py`、`validate_provenance.py` |
| 3 | Semantic Compile | `03-semantic-compiler.md` | updated IR、`review/semantic_compile.md` | `validate_ir.py`、`validate_links.py --mode ir` |
| 4 | Audit | `04-audit-reviewer.md` | `review/audit_summary.json`、`review/issues.jsonl`、`review/unresolved.md` | `validate_audit_summary.py`、`validate_tables.py`、`validate_provenance.py`、`validate_unresolved.py` |
| 5 | Assembly | `05-agent-md-editor.md` | `output/main.md`、`output/index.md`、`output/index.json`、可选 `output/parts/`、`output/assets/` | `validate_agent_md_quality.py`、`validate_placeholders.py`、`validate_links.py --mode markdown` |
| 6 | Validation | `06-qa-visual-reviewer.md` | `output/qa_report.md`、`output/visual_acceptance.md`、`output/unresolved.md`、`review/visual_acceptance/source_comparisons/` | `validation_gate.py` |
| 7 | Package | `07-package-operator.md` | `<source-document-stem>-agent-md/` | `package_gate.py` |

> review-003 minor 10：`ir/provenance.json` 由 `build_ir.py` 在 Phase 2 一并生成，列入 Phase 2 必产物。

### 阶段推进规则

- **回退允许，跳过禁止**。`validate_state.py` 机械检查：current 之前的 phase 必须 `done`，之后必须 `pending`。
- `current_phase` 只能取 `PHASES` 枚举；`phase_status` 只能取 `pending|in_progress|done|failed`。
- 一个 phase 的**全部 gate** 通过后，用 `tools/run_validators.py --job <dir>` 编排：它会先做 stale 输入检查，
  再跑齐该 phase 的 gates，写 `logs/hashes/<phase>.json`，最后调用 `advance_phase.py` 推进。
  `advance_phase.py` 保留为低层推进器，不再是推荐的日常入口。
- 任一 gate `fail`（exit 1）时，gate 自动把对应 phase 写 `failed`，禁止推进。
- 回退：把 `current_phase` 改回较早 phase，把其后所有 phase 重置 `pending`，并删除被重置 phase 的
  `logs/gates/gate_<phase>_*.json`——否则 `advance_phase` 会误信旧的通过记录（pre-v0.7 不做 hash 失效检测）。

---

## 3. Gate 协议

所有 gate 是显式命令，不藏在 hook 里。统一输出协议（`lib/gates.py`）：

| 退出码 | 含义 | phase_status 影响 |
| --- | --- | --- |
| 0 | pass | 不变 |
| 1 | fail | 该 phase 写 `failed` |
| 2 | pass_with_notes | 不变，须进 qa_report |

- 机器结果固定写 `logs/gates/gate_<phase>_<name>.json`。**phase 进文件名**，避免同一 validator 在
  Phase 2/3 复跑互相覆盖、审计链断裂（review-003 minor 3）。
- 人读摘要追加到 `review/gate_log.md`，**不**直接写 `output/qa_report.md`（见 §4 晋升规则，review-003 medium 1）。
- check 分三级：`error` 失败 → fail；`warn` 失败 → pass_with_notes；`info` 不阻断。

### Validator 模式

部分 validator 因 phase 不同而检查内容不同，用 `--mode` 区分：

- `validate_manifest.py --mode draft|final`：draft（Phase 0）只校验 schema/id/源条目；final（Phase 6/7）追加
  outputs、split parts、input_hashes（review-003 minor 7）。
- `validate_links.py --mode ir|markdown`：ir 模式查 asset 引用关系；markdown 模式查 `main.md`+`parts/`+本地链接+assets。
- `validate_extraction.py`：除检查 extraction 产物外，**复核 `document_profile` 并把 `risk_level` 确认/上调**，
  将 `profile_status` 置 `confirmed`、写 `confirmed_by`（review-003 minor 8 / PLAN §6）。

### Phase 4 专项审计

Phase 4 先运行审计工具，再运行 gate：

```bash
python3 scripts/run_python.py tools/run_audits.py --job "<job-dir>"
python3 scripts/run_python.py tools/run_validators.py --job "<job-dir>"
```

`run_audits.py` 顺序调用：

- `tools/audit_tables.py`：寄存器表、参数表、报价表等硬表语义列/行宽/寄存器地址审计。
- `tools/audit_formulas.py`：公式 LaTeX/括号平衡/visual_check/低置信度审计。
- `tools/audit_assets.py`：图表/截图资产、caption、description、估读 basis 审计。
- `tools/audit_provenance.py`：高价值 block provenance 与 `extracted/comments/` 批注/修订锚点审计。

审计发现统一 upsert 到 `review/issues.jsonl`；同一工具重跑时，消失的问题标 `fixed`，不会静默删除历史发现。
`review/unresolved.md` 始终由未关闭条目投影生成。`validate_audit_summary.py` 要求四项审计均已执行。

### v1.0 Golden Quality

`tools/check_golden_quality.py` 用于 ZHCAEJ4/TAA5212 等 golden job 的质量基线检查：

```bash
python3 scripts/run_python.py tools/check_golden_quality.py --job "<job-dir>" \
  --baseline-md "<skill-output.md>" --expect figure --expect formula --expect register
```

检查项覆盖图片资产完整、公式 LaTeX 化、寄存器表审计、低置信度追踪、`main.md` 来源锚点/placeholder，
并把 workflow 输出与基础 skill 输出的结构指标差异写入 `review/golden_quality.json`。

---

## 4. 产物晋升规则（review-003 medium 1）

`output/` 内文件按生成来源分两类，互不混淆：

| 产物 | 来源 | 何时生成 |
| --- | --- | --- |
| `output/qa_report.md`、`output/visual_acceptance.md`、`output/unresolved.md` | 由 review 产物**晋升刷新** | Phase 6 |
| `output/main.md`、`output/index.md`、`output/index.json`、`output/parts/`、`output/assets/` | 由 IR **编译生成** | Phase 5 |
| `output/manifest.json`、`output/provenance.json` | 由源文件 / IR / gate 结果**工具生成** | manifest：Phase 0 init 出 draft，Phase 6 后由 IR+gate 刷成 final；provenance：Phase 5 |

由此消解 review-003 medium 1 指出的三处碰撞：

1. gate 人读摘要落 `review/gate_log.md`，Phase 6 汇总晋升进 `qa_report.md`，不再由各 gate 直接追加、被 Phase 6 覆盖。
2. `manifest.json` 在 Phase 0 由 init 从源文件生成 draft（彼时无 IR），Phase 6 后刷成 final，不违反"只能由 IR/gate 生成"。
3. "人读文件只能晋升生成"仅指上表第一类三件；`main.md` 由 IR 编译，不在晋升约束内。

晋升与编译产物一律不手工维护。`review/issues.jsonl` 是全量审计发现；`review/unresolved.md` /
`output/unresolved.md` 是其未关闭条目的人读投影。

---

## 5. Hash 失效检测（review-003 minor 4）

两个落点分工明确：

- `logs/hashes/`：各阶段**输入/输出 hash 快照**，是 stale 判定依据。回退重跑上游 phase 后，下游旧产物
  的输入 hash 与新快照不一致即判 stale，必须重跑对应 gate。
- `output/manifest.json` 的 `input_hashes` / `output_hashes`：**最终交付物 hash**，随 package 发布。
  `output_hashes` 覆盖所有被打包的输出文件（`manifest.json` 自身除外，避免自引用 hash）。

`tools/run_validators.py` 默认遇到 stale 输入会写 `gate_<phase>_hash_stale.json` 并 fail；人工确认下游产物已重跑后，
可加 `--refresh-stale` 重新跑 gate 并刷新快照。

`package_gate.py` 在打包前比对两者，发现 stale 下游产物、缺失 hash、断开的最终 Markdown 图片链接、
或 `output/unresolved.md` 与 `review/issues.jsonl` 投影不一致即 fail。

---

## 6. issues.jsonl 条目 schema（review-003 minor 5）

`review/issues.jsonl` 每行一个 JSON 对象，是 severity/status 等字段的**唯一定义源**；`unresolved.md`
只是其未关闭条目（`status != fixed`）的人读投影。

```json
{
  "id": "unresolved_001",
  "severity": "blocker",
  "status": "open",
  "accepted_by": "",
  "accepted_reason": "",
  "source_block_id": "block_table_003",
  "source_anchor": "p.12",
  "category": "table",
  "issue": "表格第 4 列疑似跨页错位。",
  "required_action": "人工核对源页 p.12-p.13。",
  "found_by": "audit_tables.py",
  "created_at": "2026-06-12T00:00:00Z"
}
```

枚举：

- `severity`：`blocker | major | minor | info`
- `status`：`open | accepted | fixed`
- `category`：`ocr | table | formula | figure | provenance | source_conflict | rendering`

`package_gate.py` 判定：

- `severity=blocker` 且 `status=open` → 禁止 package。
- `severity=blocker` 且 `status=accepted` → `accepted_by` 与 `accepted_reason` 必须非空，否则 fail。
- `major/open` 可 `pass_with_notes`，但必须进 `qa_report.md`。
- `main.md` 出现 `[未解析: ...]` 时，`unresolved.md` 必须有对应条目，否则 fail。

---

## 7. Job Bundle 目录

由 `init_document_job.py` 创建，目录骨架定义在 `lib/paths.py:JOB_DIRS`。

```text
<jobs-root>/<document_slug>-<date>/
├── STATE.json
├── source/
├── extracted/{extract_meta.json,text/,pages/,images/,tables/,comments/,attachments/}
├── ir/{document.ir.json,blocks.jsonl,assets.index.json,provenance.json,summary.seed.md}
├── review/{visual_acceptance/,visual_acceptance/source_comparisons/,vision_cache.json,cleaning_decisions.json,
│           imported_quality_report.md,semantic_compile.md,audit_summary.json,
│           golden_quality.json,issues.jsonl,unresolved.md,gate_log.md}
├── output/{main.md,index.md,index.json,parts/,assets/,manifest.json,provenance.json,
│           qa_report.md,visual_acceptance.md,unresolved.md}
└── logs/{gates/,hashes/}
```

- 默认 `jobs-root` = `<源文档目录>/.agent-friendly-md/jobs/`；可用 `--jobs-root` 覆盖。
- `.agent-friendly-md/` 默认进 `.gitignore`，不污染业务项目 git。
- 分卷阈值默认值见 `lib/jobstate.py:DEFAULT_SPLIT_THRESHOLDS`；可经 init/assemble 的 `--max-pages` 等覆盖，
  **生效值写入 `STATE.json.config.split_thresholds`** 以便复现（review-003 minor 9）。

---

## 8. 最终 Package

`tools/package_output.py`（Phase 7）在 `validators/package_gate.py` 通过后，把 `output/` 快照晋升为：

```text
<source-document-stem>-agent-md/   # 默认落源文档同级目录，--out 可覆盖
├── <source-document-stem>.md
├── assets/
├── parts/                         # 启用分卷时保留在根目录，供主文档链接
└── _agent-md/
    ├── index.md
    ├── index.json
    ├── manifest.json
    ├── provenance.json
    ├── qa_report.md
    ├── visual_acceptance.md
    ├── unresolved.md
    └── package_metadata.json
```

当 split 启用时，`<source-document-stem>.md` 是 agent 入口索引：包含摘要、分卷链接、source range 和内容计数；
正文按需读取 `parts/`，避免其他 agent 先全量加载大文档。`_agent-md/index.md` / `index.json` 提供同一导航的
辅助索引，供 agent 或程序化读取。

`--include-work` 可在 `_agent-md/work/` 附带 `extracted/`、`ir/`、`review/`、`logs/` 生成完整复现包。`--force` 先构建临时目录，
成功后替换旧包；成功写包后 `STATE.json.phase_status.7_package` 标为 `done`。

---

## 9. 里程碑现状

- **v0.1（已完成并自验）**：项目骨架、`scripts/run_python.py`、`doctor.py`、`init_document_job.py`、
  `STATE.json`/`manifest.json` 模板与 Phase 0 gate（`validate_state.py`、`validate_manifest.py`）。
- **v0.2（已完成并自验）**：接入 `doc-to-agent-markdown` backend 作 Phase 1 提取后端。
  - `lib/backend.py`：定位 backend（`--backend` > 环境变量 `AFM_BACKEND_DIR` > 默认路径）。
  - `tools/run_extraction.py`：调用 backend 提取器，把 skeleton/extract_meta/images/pages 映射进 bundle，
    写 `review/imported_quality_report.md`，seed vision_cache/cleaning_decisions/summary.seed 槽位。
    它是当前的 Phase 1 提取**驱动**，统一代替 PLAN §5 设想的 per-format `extract_*.py`（若日后改用原生
    per-format 提取器再拆分）。
  - `validators/validate_extraction.py`：Phase 1 gate，检查提取产物并**复核确认 document_profile**
    （profile_status→confirmed、写 confirmed_by、按内容上调 risk，review-003 minor 8）。
  - `tools/advance_phase.py`：gate-pass-gated 的相位推进器。
  - `tools/assemble_backend_md.py`：用旧 assembler 产出**临时** `output/main.md`（v0.2 过渡桥，v0.6 由 IR
    assembler 取代，不晋升不打包）。
  - 已在 PDF/DOCX/PPTX/XLSX/MD 五种样例跑通 Phase 0→1，§3 全部映射槽位落盘。backend 自带回归 41/41 PASS。
- **v0.3（已完成并自验）**：Document IR（`lib/ir.py`+`lib/skeleton_parser.py`+`build_ir.py`，blocks.jsonl 唯一载体
  +document.ir.json+assets/provenance 投影，`validate_ir`/`validate_provenance`）。见 [docs/ir-schema.md](../ir-schema.md)。
- **v0.4（已完成并自验）**：Asset 图文绑定（`lib/naming.py`+`tools/link_assets.py` 语义命名/caption-figure_no/正文引用
  relation + `validators/validate_links.py --mode ir|markdown`）。
- **v0.5（已完成并自验）**：语义编译 Phase 3。`compile_structure.py`（标题层级规范+噪声标记）、`normalize_tables.py`
  （跨页表格链接）、`normalize_formulas.py`（LaTeX 清理+括号校验+编号）、`semanticize_figures.py`
  （从 `review/vision_cache.json` 回填图像说明）。图像视觉描述由 Agent 完成（见 [roles/03-semantic-compiler.md](../../roles/03-semantic-compiler.md)），
  工具消费其 JSONL 缓存。IR 变换经 `lib/ir.py:load_ir/save_all` 统一读写并重生成投影。
- **v0.6（已完成并自验）**：IR→`output/main.md` 组装（`assemble_agent_md.py`），取代 v0.2 临时桥。
- **v0.7（已完成并自验）**：跨阶段 validators、`review/issues.jsonl`/`unresolved.md`、`run_validators.py`、
  hash 失效检测。
- **v0.8（已完成并自验）**：Phase 6 HTML 预览、Playwright 截图/contact sheet、视觉验收晋升、
  `validation_gate.py`。`review/visual_acceptance/source_comparisons/` 承载 high-risk source evidence：
  PDF/PPT 为并排图，DOCX/MD/TXT/XLSX 等无页图 anchor 为来源锚点、IR block、源片段和 screenshot 引用。
- **v0.9（已完成并自验）**：Phase 4 专项审计 `audit_tables/formulas/assets/provenance`、
  `run_audits.py`、`validate_audit_summary.py`。
- **v1.0（已完成并自验）**：`check_golden_quality.py` 固化 ZHCAEJ4/TAA5212 类 golden quality 标准，
  并补齐 Phase 7 `package_gate.py` / `package_output.py`。

逐里程碑目标见 [PLAN.md](./PLAN.md) §16。
