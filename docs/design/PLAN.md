# Agent Friendly Markdown Workflow Project Plan

创建日期：2026-06-12  
修订日期：2026-06-12  
版本：v3，基于 `review-002.md` 修订  
修订范围：收口运行命令、IR 存储契约、视觉验收定位、分卷输出、产物晋升、gate 协议、风险分级和测试资产规则。

## 1. 项目定位

本项目不是一个简单的 `doc-to-md` 转换 skill，而是一个独立的文档编译工作流项目。目标是把多类型源文档编译成 Agent 可长期使用、可追溯、可复查、可继续加工的 Markdown 知识包。

建议正式项目目录名使用：

```text
agent-friendly-md
```

当前讨论目录 `agent friendly md` 可作为方案存放目录；真正建仓时使用连字符命名，避免命令行、wrapper、脚本路径中的空格转义问题。

核心定位：

- 不是压缩摘要器，而是文档编译器。
- 不是一次性 Markdown 生成器，而是 job bundle + 显式 gate + 质量审计系统。
- 不是替代现有 `doc-to-agent-markdown` skill，而是把它降级为 extraction backend，并补足状态、IR、provenance、validators、视觉验收和 package 管理。

## 2. 完美 Agent Friendly Markdown 标准

最终 `main.md` 应满足以下硬标准：

- **不压缩、不中断、不过度转义原文**：正文应忠实保留原文信息密度，不把重要段落压成摘要，不让公式、代码、寄存器、参数表退化成散乱自然语言。
- **清除噪声**：删除重复页眉页脚、页码、反馈链接、重复公司名、重复 logo、网站导航、装饰性图片等低价值内容；但免责声明、关键版权声明、表注脚、法律条款、重要水印不得误删。
- **所有表格转为 Markdown 表格或结构化附表**：包括 PDF 文本层表格、Word/Excel/PPT 表格、图片里的表格、跨页表格。复杂硬表应有结构化审计记录。
- **所有公式使用 LaTeX**：保留方程编号，校对上下标、根号、分数、希腊字母、符号方向，不保留 OCR 式线性碎片。
- **所有图片独立保存并语义命名**：图片应保存到 `assets/`，按内容命名，并在 `main.md` 中以相对路径插入。图片文件名建议带源页码或 slide，如 `fig_3_3_purepath_biquad_example_p006.png`。
- **图片必须图文绑定**：每张图应有图号、caption、来源页、简要语义说明。复杂框图可额外生成 Mermaid 重绘，但原图必须保留。
- **源页码可追溯**：PDF 中每个 block 级内容、图、表、公式、代码块必须能追溯到原文页码；PPT 对应 slide；Excel 对应 sheet/range；Word 对应页码或章节路径+段落锚点。
- **原文与编者加工分层**：修正、重绘、估读、推断、疑似原文错误都必须用“编者注 / 审计注 / 估读标注”标明，不能混进原文。
- **低置信度内容显性化**：OCR 不确定、截图估读、表格合并失败、图片文字太小、源文档疑似错误，都进入 `unresolved.md` 或文内明确标注。
- **渲染后可读**：Markdown 通过文本检查不够，最终必须渲染成 HTML/截图，经过视觉验收，确认图片、公式、表格、Mermaid、版面在人眼视角下正常。

一句话标准：

```text
忠实原文、清除噪声、结构重建、视觉可验、来源可追、低置信度可见。
```

## 3. 现有 Skill 的真实差距

现有 `doc-to-agent-markdown` 已经具备可复用基础能力：

- 多格式基础提取。
- Markdown skeleton。
- 图片提取。
- 视觉描述缓存。
- 清洗决策留痕。
- 摘要与组装。
- 基础质量报告。

因此本项目不应重复造基础 extractor。真实差距是：

- 没有跨会话 `STATE.json` 和 job bundle，无法系统恢复、复查、批处理。
- 质量报告偏“汇报”，不是阻断式 gate。
- 没有统一 Document IR 作为单一事实源。
- 没有 block 级 provenance/confidence，最终 Markdown 难以机械追溯。
- 图片描述、图号、caption、正文引用、资产文件没有稳定关系模型。
- 复杂表格缺结构化中间层，无法支持跨页合并、合并单元格审计、寄存器表硬列校验。
- 公式校对和 LaTeX 化不是独立 gate。
- 批注、修订痕迹、附件、Excel 图表等全量文档要素仍需新增开发或复用其他 skill。
- 视觉验收没有成为交付前强制步骤。

v0.2 集成时，应把现有 skill 的中间产物映射进 job bundle：

| 现有产物 | 新项目归宿 |
| --- | --- |
| skeleton Markdown | `extracted/text/` |
| extract metadata | `extracted/extract_meta.json` |
| extracted images | `extracted/images/` |
| vision cache | `review/vision_cache.json` |
| cleaning decisions | `review/cleaning_decisions.json` |
| summary | `ir/summary.seed.md` 或 `output/main.md` 摘要来源 |
| quality report | `review/imported_quality_report.md` |

## 4. 最终交付包和 Job Bundle 边界

每个任务先生成 job bundle，最终 package 是 job 的 `output/` 快照。`output/` 中的人读文件只能由上游 review 产物晋升生成，不允许手工复制后绕过 gate。

默认 job 根路径建议：

- 优先放在源文档所在项目目录下的 `.agent-friendly-md/jobs/`，方便跟随业务项目。
- 也允许通过 `--jobs-root` 指定集中目录。
- 大文件、渲染页、截图、缓存不得默认进入项目 git；`.agent-friendly-md/` 应默认加入 `.gitignore`，除非用户明确要求归档。

Job bundle：

```text
.agent-friendly-md/jobs/<document_slug>-<date>/
├── STATE.json
├── source/
├── extracted/
│   ├── extract_meta.json
│   ├── text/
│   ├── pages/
│   ├── images/
│   ├── tables/
│   ├── comments/
│   └── attachments/
├── ir/
│   ├── document.ir.json
│   ├── blocks.jsonl
│   ├── assets.index.json
│   └── provenance.json
├── review/
│   ├── visual_acceptance/
│   ├── vision_cache.json
│   ├── cleaning_decisions.json
│   ├── imported_quality_report.md
│   ├── semantic_compile.md
│   ├── table_review.md
│   ├── formula_review.md
│   ├── issues.jsonl
│   └── unresolved.md
├── output/
│   ├── main.md
│   ├── parts/
│   ├── assets/
│   ├── manifest.json
│   ├── provenance.json
│   ├── qa_report.md
│   ├── visual_acceptance.md
│   └── unresolved.md
└── logs/
    ├── gates/
    └── hashes/
```

最终 package：

```text
<source-document-stem>-agent-md/
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

默认 package 落盘到源文档同级目录，目录名为 `<source-document-stem>-agent-md/`，外发主 Markdown 命名为 `<source-document-stem>.md`。大文档启用 split 时，外发主 Markdown 是入口索引，不承载全文；正文放入 `parts/`，并同步生成 `_agent-md/index.md` / `_agent-md/index.json`，供其他 agent 先读取导航、source range 和内容计数后再按需加载正文。`package_output.py --out "<dir>"` 可覆盖默认位置。`work/` 不默认进入最终 package；若用户需要完整复现包，可使用 `package_output.py --include-work` 在 `_agent-md/work/` 附带 `extracted/`、`ir/`、`review/` 和 `logs/`。

产物晋升规则：

- `review/issues.jsonl` 是全量审计发现。
- `review/unresolved.md` 是 `issues.jsonl` 中未关闭问题的人读投影。
- Phase 6 汇总 validators 和视觉验收后，刷新 `output/qa_report.md`、`output/visual_acceptance.md`、`output/unresolved.md`。
- `output/provenance.json`、`output/manifest.json` 只能由 IR 和 gate 结果生成，不能手工维护。
- `manifest.json` 记录关键输入 hash。回退重跑上游 phase 后，下游旧产物 hash 不一致即判定为 stale，必须重跑对应 gate。

分卷输出规则：

- 默认优先单文件 `main.md`。
- 超过规模阈值的长文档、多章节技术手册、多 sheet 工作簿，`main.md` 作为总索引与摘要，正文写入 `parts/`。
- 初始分卷阈值：源文档超过 100 页、工作簿超过 3 个有效 sheet、单个 Markdown 预计超过 300 KB、或 block 数超过 1500。
- `manifest.json` 记录 `parts/` 清单、顺序、标题、source range 和 hash。
- `validate_links.py` 和 `package_gate.py` 必须把 `main.md`、`parts/`、`assets/` 作为一个整体校验。

## 5. 唯一阶段模型

本项目采用唯一阶段枚举。Visual Acceptance 并入 Phase 6 Validation，不再作为独立 phase。MVP 默认不依赖自动 hooks，采用显式 gate 命令；hooks 作为 v1 之后的可选增强。

| Phase | 名称 | 角色 | 允许工具 | 必产物 | Gate |
| --- | --- | --- | --- | --- | --- |
| 0 | Intake | `00-intake-curator.md` | `init_document_job.py`, `doctor.py` | `STATE.json`, `output/manifest.json` 初稿 | `validate_state.py`, `validate_manifest.py` |
| 1 | Extraction | `01-extraction-engineer.md` | `extract_pdf.py`, `extract_docx.py`, `extract_pptx.py`, `extract_xlsx.py`, `extract_text.py`, `render_pages.py` | `extracted/`, `extracted/extract_meta.json` | `validate_extraction.py` |
| 2 | IR Build | `02-ir-architect.md` | `build_ir.py`, `link_assets.py` | `ir/document.ir.json`, `ir/blocks.jsonl`, `ir/assets.index.json` | `validate_ir.py`, `validate_provenance.py` |
| 3 | Semantic Compile | `03-semantic-compiler.md` | `compile_structure.py`, `semanticize_figures.py`, `normalize_tables.py`, `normalize_formulas.py` | updated IR, `review/semantic_compile.md` | `validate_ir.py`, `validate_links.py --mode ir` |
| 4 | Audit | `04-audit-reviewer.md` | `audit_tables.py`, `audit_formulas.py`, `audit_assets.py`, `audit_provenance.py` | `review/issues.jsonl`, `review/unresolved.md` | `validate_tables.py`, `validate_provenance.py`, `validate_unresolved.py` |
| 5 | Assembly | `05-agent-md-editor.md` | `assemble_agent_md.py` | `output/main.md`, `output/index.md`, `output/index.json`, optional `output/parts/`, `output/assets/` | `validate_agent_md_quality.py`, `validate_placeholders.py`, `validate_links.py --mode markdown` |
| 6 | Validation | `06-qa-visual-reviewer.md` | `run_validators.py`, `render_agent_md_preview.py`, `build_visual_review_packet.py` | `output/qa_report.md`, `output/visual_acceptance.md`, `output/unresolved.md` | `validation_gate.py` |
| 7 | Package | `07-package-operator.md` | `package_output.py` | `<source-document-stem>-agent-md/` | `package_gate.py` |

阶段推进规则：

- 回退允许，跳过禁止。
- `STATE.json.current_phase` 必须只取上表枚举。
- `phase_status` 只能取 `pending`、`in_progress`、`done`、`failed`。
- 每个 phase 结束必须显式运行 gate；gate 通过后才允许推进。
- `package_output.py` 是最终总门禁，必须重新检查所有必要报告和状态。

## 6. STATE.json Schema

```json
{
  "schema_version": "agent-friendly-md-state/0.1",
  "job_id": "zhcaej4-20260612",
  "source_files": ["source/zhcaej4.pdf"],
  "current_phase": "2_ir_build",
  "phase_status": {
    "0_intake": "done",
    "1_extraction": "done",
    "2_ir_build": "in_progress",
    "3_semantic_compile": "pending",
    "4_audit": "pending",
    "5_assembly": "pending",
    "6_validation": "pending",
    "7_package": "pending"
  },
  "document_profile": {
    "profile_status": "confirmed",
    "confirmed_by": "validate_extraction.py",
    "primary_type": "pdf",
    "pages": 38,
    "has_images": true,
    "has_tables": true,
    "has_formulas": true,
    "has_comments": false,
    "has_attachments": false,
    "is_scanned": false,
    "risk_level": "high",
    "risk_level_history": [
      {"phase": "0_intake", "risk_level": "medium", "basis": "source extension and page count"},
      {"phase": "1_extraction", "risk_level": "high", "basis": "tables and formulas detected"}
    ]
  },
  "paths": {
    "job_root": ".agent-friendly-md/jobs/zhcaej4-20260612",
    "output_dir": "output"
  }
}
```

`STATE.json` 由工具和 gate 显式更新，不依赖隐藏 hook 自动改写。

`document_profile` 采用两段式：

- Phase 0 只能写入 `profile_status=provisional`。
- `validate_extraction.py` 根据提取结果复核后改为 `confirmed`。
- `risk_level` 可由自动规则上调；下调必须写入 `qa_report.md`，说明依据和责任 phase。

## 7. 项目结构

```text
agent-friendly-md/
├── README.md
├── WORKFLOW.md
├── requirements.txt
├── scripts/
│   └── run_python.py
├── roles/
│   ├── 00-intake-curator.md
│   ├── 01-extraction-engineer.md
│   ├── 02-ir-architect.md
│   ├── 03-semantic-compiler.md
│   ├── 04-audit-reviewer.md
│   ├── 05-agent-md-editor.md
│   ├── 06-qa-visual-reviewer.md
│   └── 07-package-operator.md
├── templates/
│   ├── main.md
│   ├── manifest.json
│   ├── unresolved.md
│   ├── visual_acceptance.md
│   ├── qa_report.md
│   └── STATE.json
├── tools/
│   ├── doctor.py
│   ├── init_document_job.py
│   ├── extract_pdf.py
│   ├── extract_docx.py
│   ├── extract_pptx.py
│   ├── extract_xlsx.py
│   ├── extract_text.py
│   ├── render_pages.py
│   ├── build_ir.py
│   ├── link_assets.py
│   ├── compile_structure.py
│   ├── semanticize_figures.py
│   ├── normalize_tables.py
│   ├── normalize_formulas.py
│   ├── audit_tables.py
│   ├── audit_formulas.py
│   ├── audit_assets.py
│   ├── audit_provenance.py
│   ├── assemble_agent_md.py
│   ├── run_validators.py
│   ├── render_agent_md_preview.py
│   ├── build_visual_review_packet.py
│   └── package_output.py
├── validators/
│   ├── validate_state.py
│   ├── validate_manifest.py
│   ├── validate_extraction.py
│   ├── validate_ir.py
│   ├── validate_links.py
│   ├── validate_placeholders.py
│   ├── validate_tables.py
│   ├── validate_provenance.py
│   ├── validate_unresolved.py
│   ├── validate_agent_md_quality.py
│   ├── validation_gate.py
│   └── package_gate.py
├── hooks/
│   └── README.md
├── docs/
│   ├── ir-schema.md
│   ├── runtime.md
│   ├── quality-standards.md
│   └── migration-from-skill.md
├── tests/
│   ├── _fixtures/
│   ├── unit/
│   ├── integration/
│   └── visual/
└── examples/
    ├── zhcaej4/
    └── mixed-doc-sample/
```

`hooks/` 首期只放说明，不进入关键路径。若后续要支持编辑器或运行时 hook 自动化，必须在 v1 之后单独设计注册、跨平台兼容、降级路径和测试。

## 8. 运行环境与依赖策略

本项目需要自己的 wrapper，不复用其他仓库的 `scripts/run_python.py`。所有示例命令默认在 `agent-friendly-md/` 项目根目录执行，入口统一通过：

```bash
python scripts/run_python.py tools/init_document_job.py --source "<file>"
python scripts/run_python.py tools/build_ir.py --job "<job-dir>"
python scripts/run_python.py tools/run_validators.py --job "<job-dir>"
python scripts/run_python.py tools/package_output.py --job "<job-dir>"
```

命令约定：

- 文档中的命令以 POSIX shell 写法为准。
- Windows PowerShell 必须在 `WORKFLOW.md` 中给出等价示例。
- wrapper 接收项目内相对路径，禁止要求调用者从项目父目录传入 `agent-friendly-md/tools/...`。

基础依赖：

- Python 3.10+。
- PyMuPDF / pdfplumber 等 PDF 解析库。
- python-docx 或等价 DOCX 解析库。
- python-pptx。
- openpyxl。
- Pillow。
- pandas，可在 v0.3 实测后降级为可选依赖。
- pytest。

视觉验收依赖：

- pandoc 或项目内 Markdown-to-HTML 渲染器。
- Playwright + Chromium。
- Mermaid 本地渲染支持。
- MathJax 或 KaTeX 本地资源。

OCR 策略：

- v0.x 不把扫描件全文 OCR 作为硬承诺。
- 扫描件首期走“整页渲染 + 多模态视觉描述 + 低置信度标注”。
- OCR 引擎选型放入 v1.x，可评估 Tesseract、PaddleOCR 或云端 OCR，但必须保留来源页和置信度。

`doctor.py` 必须检查：

- Python 版本。
- 必需 Python 包。
- pandoc 是否可用。
- Playwright Chromium 是否已安装。
- Mermaid 与公式渲染资源是否可离线工作。
- 可选 OCR 引擎状态。
- 当前项目路径是否含空格并给出警告。

## 9. Document IR 设计

Document IR 是单一事实源。`ir/blocks.jsonl` 是 block 内容唯一载体；`document.ir.json` 只保存 metadata、store 路径、block 顺序和统计信息；`ir/assets.index.json`、`ir/provenance.json`、`output/provenance.json` 都是可再生成投影，不是第二份手工维护数据。

### 9.1 基础结构

```json
{
  "schema_version": "agent-document-ir/0.1",
  "document_id": "zhcaej4",
  "metadata": {
    "title": "TAC5x1x 和 TAC5x1x-Q1 可编程双二阶滤波器",
    "source_type": "pdf",
    "source_file": "source/zhcaej4.pdf",
    "language": "zh-CN"
  },
  "stores": {
    "blocks": "blocks.jsonl",
    "assets_index": "assets.index.json",
    "provenance": "provenance.json"
  },
  "block_order": ["block_heading_001", "block_para_001", "block_figure_003"],
  "relations": [
    {"from": "block_figure_003", "to": "asset_fig_3_3", "type": "uses_asset"}
  ],
  "stats": {
    "block_count": 128,
    "asset_count": 24
  }
}
```

每个 block 必须有：

- `id`
- `type`
- `source_anchor`
- `confidence`
- `content` 或结构化子字段
- `needs_review`

`validate_ir.py` 必须检查：

- `document.ir.json.block_order` 中的 id 在 `blocks.jsonl` 中全部存在。
- `blocks.jsonl` 中不存在重复 id。
- `assets.index.json` 可由 block asset 引用和实体文件重新生成。
- `ir/provenance.json` 与 `output/provenance.json` 都可由 `blocks.jsonl` 的 `source_anchor` 投影生成。
- 任一投影与唯一载体不一致时 fail。

### 9.2 source_anchor 规范

PDF：

```json
{
  "kind": "pdf_page",
  "source_file": "source/zhcaej4.pdf",
  "page": 6,
  "page_label": "p.6",
  "bbox": [72, 144, 520, 680]
}
```

PPTX：

```json
{
  "kind": "slide",
  "source_file": "source/deck.pptx",
  "slide": 3,
  "shape_id": "shape_12"
}
```

XLSX：

```json
{
  "kind": "sheet_range",
  "source_file": "source/model.xlsx",
  "sheet": "Sheet1",
  "range": "A12:D30"
}
```

DOCX：

```json
{
  "kind": "docx_anchor",
  "source_file": "source/report.docx",
  "page": 12,
  "heading_path": ["2 技术方案", "2.3 实施步骤"],
  "paragraph_index": 84
}
```

若 Word 页码不可稳定获取，使用 `heading_path + paragraph_index`，并在 `qa_report.md` 中说明页码限制。

### 9.3 Table 子 schema

表格 block 不应只保存 Markdown 字符串，必须保存结构化单元格：

```json
{
  "id": "block_table_001",
  "type": "table",
  "title": "表 3-4. 数字双二阶滤波器 1-6 的可编程系数寄存器",
  "source_anchor": {"kind": "pdf_page", "page": 9},
  "table": {
    "columns": ["地址", "寄存器", "寄存器说明", "复位值"],
    "header_rows": [0],
    "rows": [
      [
        {"text": "0x08", "rowspan": 1, "colspan": 1},
        {"text": "ADC_BQ1_N0_BYT1[7:0]", "rowspan": 1, "colspan": 1},
        {"text": "可编程 ADC 双二阶滤波器 1，N0 系数字节[31:24]", "rowspan": 1, "colspan": 1},
        {"text": "0x7F", "rowspan": 1, "colspan": 1}
      ]
    ],
    "continues_from": null,
    "continues_to": "block_table_002",
    "audit": {
      "row_count": 120,
      "column_count": 4,
      "hard_column_check": "pass"
    }
  },
  "confidence": 0.95,
  "needs_review": false
}
```

### 9.4 Figure 子 schema

```json
{
  "id": "block_figure_003",
  "type": "figure",
  "figure": {
    "figure_no": "图 3-3",
    "caption": "PurePath(TM) Console 可编程双二阶滤波器示例",
    "asset_id": "asset_fig_3_3",
    "description": "Programmable Biquads 页，ADC 选项卡...",
    "estimated_values": [
      {"label": "60Hz notch depth", "value": "约 -36dB", "basis": "图上估读"}
    ]
  },
  "source_anchor": {"kind": "pdf_page", "page": 6},
  "confidence": 0.88,
  "needs_review": true
}
```

### 9.5 Formula 子 schema

```json
{
  "id": "block_formula_001",
  "type": "formula",
  "formula": {
    "equation_no": "1",
    "latex": "H(z)=\\frac{b_{0}+b_{1}z^{-1}+b_{2}z^{-2}+\\dots+b_{M}z^{-M}}{1+a_{1}z^{-1}+a_{2}z^{-2}+\\dots+a_{N}z^{-N}}",
    "plain_text_source": "H z = ...",
    "visual_check": "pass",
    "control_source": "source/slaaeh6.pdf p.3"
  },
  "source_anchor": {"kind": "pdf_page", "page": 3},
  "confidence": 0.96,
  "needs_review": false
}
```

## 10. Markdown 输出约定

`main.md` 中每个主要 block 必须显式携带来源锚点。若启用分卷，`main.md` 作为总索引，正文分卷写入 `parts/`，每个分卷仍必须保留同样的来源锚点。推荐格式：

```markdown
## 3.1 使用 PurePath(TM) Console 的滤波器设计　〔源 p.4-5〕

![图 3-3. PurePath(TM) Console 可编程双二阶滤波器示例](assets/fig_3_3_purepath_biquad_example_p006.png)

**图 3-3. PurePath(TM) Console 可编程双二阶滤波器示例**　〔源 p.6〕
```

约定：

- PDF 页码：`〔源 p.N〕` 或跨页 `〔源 p.N-M〕`。
- PPT：`〔源 slide N〕`。
- Excel：`〔源 Sheet1!A12:D30〕`。
- Word：`〔源 p.N〕`，不可得时用 `〔源 2.3 实施步骤 / paragraph 84〕`。
- 编者加工：`> **编者注**：...`
- 审计说明：`> **审计注**：...`
- 估读：必须写“图上估读”。

表格、公式、代码块都应在标题或前后说明中携带源锚点。

资产命名规则：

- 文件名只使用 ASCII 小写字母、数字、短横线、下划线和扩展名。
- 命名格式建议为 `<kind>_<source_ref>_<semantic_slug>.<ext>`，如 `fig_p006_purepath_biquad_example.png`。
- 中文 caption 可转为短英文语义 slug；无法可靠转写时使用 `fig_p006_asset_003.png`。
- 文件名主体不超过 96 字符。
- 冲突时追加稳定序号，如 `_02`。
- `validate_links.py` 必须校验文件名字符集、长度和碰撞。

## 11. Unresolved Schema

`unresolved.md` 必须可被机械判断。条目格式：

```markdown
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
```

`package_gate.py` 判定：

- 存在 `severity=blocker` 且 `status=open` 时禁止 package。
- `severity=blocker` 且 `status=accepted` 时，`accepted_by` 和 `accepted_reason` 必须非空，否则 fail。
- `major/open` 可允许 `pass_with_notes`，但必须进入 `qa_report.md`。
- `[未解析: ...]` 标记允许出现在 `main.md`，但必须在 `unresolved.md` 有对应条目，否则 fail。

## 12. Validators 与显式 Gate

MVP 不把执行逻辑藏在 hooks 里。所有 gate 都是显式命令，并使用统一输出协议：

- 退出码 `0`：pass。
- 退出码 `1`：fail。
- 退出码 `2`：pass_with_notes。
- 每个 gate 固定写入 `logs/gates/gate_<name>.json`。
- 人读摘要写入或追加到 `output/qa_report.md`。
- gate 失败时，对应 `phase_status` 写为 `failed`。

Validators：

- `validate_state.py`：检查 phase 枚举、状态推进、路径存在。
- `validate_manifest.py`：检查源文件、输出文件、统计字段。
- `validate_extraction.py`：检查 extraction metadata、图片/页面/表格目录。
- `validate_ir.py`：检查 IR schema、block id、asset id、relations、source_anchor。
- `validate_links.py`：支持 `--mode ir` 和 `--mode markdown`；IR 模式检查 asset 引用关系，Markdown 模式检查 `main.md`、`parts/`、本地相对链接、assets 文件。
- `validate_placeholders.py`：检查 `[VISION_PLACEHOLDER_]`、`[TODO]`、`待补充`、`[未解析: ...]` 是否有 unresolved 对应条目。
- `validate_tables.py`：检查 Markdown 表格列数、表头、空列瀑布、结构化 table 与 Markdown 投影一致性。
- `validate_provenance.py`：检查 block 级 source anchor、PDF 页码、PPT slide、XLSX sheet/range、图表公式代码来源。
- `validate_unresolved.py`：检查 unresolved schema、blocker 状态、分类完整性。
- `validate_agent_md_quality.py`：检查标题、摘要、来源、U+FFFD、控制字符、乱码风险、图片/表格/公式说明。
- `validation_gate.py`：Phase 6 总 gate，汇总 validators 和视觉验收。
- `package_gate.py`：最终 gate，不通过则 `package_output.py` 拒绝生成 package。

## 13. Hooks 策略

review 指出 hooks 与当前工作区已验证模式存在冲突。因此本 plan 修订为：

- MVP 主路径采用显式 gate，不依赖 hooks。
- hooks 不负责自动修改 `STATE.json`。
- hooks 不作为 package 的唯一阻断机制。
- hooks 可作为 v1 之后的可选增强，用于提醒、注入 brief 或提前拦截错误命令。

若未来启用 hooks，必须补齐：

- 注册位置：项目级还是用户级 settings。
- Windows / PowerShell / bash 兼容策略。
- hook 失效时的降级路径。
- 每个 hook 的单元测试。
- 与显式 gate 的职责边界。

可选 hooks：

- `inject_job_brief.py`：提醒当前 phase 和应读文件。
- `phase_tool_gate.py`：提前拦截明显越权工具。
- `post_write_hint.py`：写入阶段产物后提示运行哪个 gate。

关键原则：

```text
gate 是事实裁判，hook 只是提醒和提前拦截。
```

## 14. 视觉验收策略

视觉验收并入 Phase 6 Validation，按风险分级执行。

### 14.1 风险分级

| risk_level | 适用文档 | 视觉验收强度 |
| --- | --- | --- |
| low | 纯文本 `.md/.txt`、简单 Word | validator-only + 首屏截图 |
| medium | 普通 PDF、PPT、含少量图片/表格文档 | HTML 渲染 + 抽样截图 + 关键 assets 检查 |
| high | 技术手册、数据手册、扫描件、大表/公式密集、图纸/框图密集 | 全量视觉验收包 + contact sheet + 多模态审阅 |

### 14.2 视觉验收包

```text
review/visual_acceptance/
├── rendered.html
├── anchor_map.json
├── screenshots/
├── source_comparisons/
├── screenshot_contact_sheet.png
├── render_diagnostics.json
├── asset_link_report.json
└── visual_acceptance.md
```

截图对象定义：

- `render_agent_md_preview.py` 渲染 `main.md` 和 `parts/`，保留 block id 与来源锚点文本。
- `build_visual_review_packet.py` 通过 `〔源 p.N〕`、`〔源 slide N〕`、`〔源 Sheet!A1:B2〕` 等锚点定位 HTML 区段，生成 `anchor_map.json`。
- PDF/PPT 的截图必须与 `extracted/pages/` 或 slide 渲染图并排生成对照图，放入 `source_comparisons/`。
- Excel 分卷按 sheet/range 截图；没有页概念时，抽样单位为 sheet 或 table region。

contact sheet 规则：

- 文档 ≤ 30 页：全量截图。
- 31-100 页：首尾页、每章首页、所有含图/表/公式页、随机抽样 10%。
- >100 页：每章首页、所有 high-risk block 对应页、随机抽样 5%，并记录抽样 seed。

`visual_acceptance.md` 模板：

```markdown
# Visual Acceptance Report

status: pass | pass_with_notes | fail
reviewed_at: 2026-06-12
reviewer: visual-reviewer
risk_level: high

## Reviewed Artifacts

- rendered.html
- anchor_map.json
- screenshot_contact_sheet.png
- screenshots/page_001.png
- source_comparisons/page_001_compare.png

## Human-Eye Checks

- Layout readability:
- Image placement:
- Table rendering:
- Formula rendering:
- Mermaid rendering:
- Source anchors visible:
- Noise / repeated header-footer:

## Issues

| Severity | Location | Issue | Required Action |
| --- | --- | --- | --- |

## Decision

pass / pass_with_notes / fail
```

`validation_gate.py` 判定：

- high-risk job 缺 `visual_acceptance.md` 时 fail。
- low-risk job 可无完整 contact sheet，但必须有 validator 结果。
- `status=fail` 禁止 package。

## 15. Extractor 策略

### PDF

必须保留：

- 文本层。
- 页面渲染图。
- 嵌入图片。
- 表格候选。
- 公式候选。
- 链接、脚注、页码。

高风险 PDF 自动启用页面渲染和视觉抽查。

### DOCX

必须保留：

- 标题层级。
- 段落样式。
- 表格。
- 图片。
- 批注。
- 页眉页脚。
- 脚注尾注。
- 修订痕迹，如可读取。

批注提取可优先评估复用现有 `docx-comment-requirements` 相关逻辑。

### PPTX

必须保留：

- slide 顺序。
- slide 标题。
- shape 文本。
- 图片。
- 表格。
- speaker notes。
- 图形布局。

PPTX 不能只抽文字，必须保留每页 slide 作为页面级上下文。

### XLSX

必须保留：

- workbook 元信息。
- sheet 名称。
- used range。
- 表头和表格区域。
- 公式。
- 合并单元格。
- 图片和图表。
- 单元格批注。

Excel 应按 sheet / table region 编译，不强行转成一篇长 Markdown。默认 `main.md` 写 workbook 总览、sheet 清单和关键表索引；每个 sheet 或 table region 写入 `parts/<sheet_slug>__<range_slug>.md`。

### Markdown / TXT

职责是：

- 清理噪声。
- 标准化标题层级。
- 修复本地图片引用。
- 建立 provenance。
- 生成 manifest 和 QA。

## 16. MVP 实现路线

### v0.1：项目骨架与运行环境

目标：

- 建立项目目录、`README.md`、`WORKFLOW.md`。
- 建立 `scripts/run_python.py`。
- 建立 `requirements.txt` 和 `doctor.py`。
- 建立唯一 phase schema、`STATE.json` 模板、`manifest.json` 模板。

验收：

- `doctor.py` 可检测 Python 包、pandoc、Playwright、Mermaid/公式本地渲染资源、OCR 状态。
- `init_document_job.py` 可创建稳定 job bundle。
- 示例命令均可在项目根目录运行，不依赖父目录 wrapper。

### v0.2：接入现有 skill backend

目标：

- 将现有 `doc-to-agent-markdown` 的 extractor/assembler 作为 backend。
- 映射 skeleton、extract_meta、vision cache、cleaning decisions、quality report 到 job bundle。

验收：

- 现有 skill 自带回归测试全 PASS。
- 对 PDF/DOCX/PPTX/XLSX/MD/TXT 样例跑通 Phase 0-1。
- 经旧 assembler 产出临时 `output/main.md`。
- §3 映射表中的全部槽位落盘到 job bundle。

### v0.3：Document IR

目标：

- 实现 `build_ir.py`。
- 定义并实现 table / figure / formula 子 schema。
- 明确 `blocks.jsonl` 是 block 唯一载体，`assets.index.json` 和 `provenance.json` 是投影。
- 同步交付 `validate_ir.py` 和 `validate_provenance.py`。

验收：

- IR 可通过 `validate_ir.py`。
- 表格、图、公式 block 均有 source_anchor。

### v0.4：Asset 管理与图文绑定

目标：

- 实现 `link_assets.py`。
- 图片语义命名。
- 图号、caption、正文引用、图片资产建立 relation。
- 同步交付 `validate_links.py --mode ir`。

验收：

- 输出 assets 无断链。
- 图片说明不再漂浮在文档末尾或脱离上下文。

### v0.5：语义编译

目标：

- 实现 `compile_structure.py`、`semanticize_figures.py`、`normalize_tables.py`、`normalize_formulas.py`。
- 支持标题层级重建、噪声删除、表格合并、公式 LaTeX 化、图像说明回填。

验收：

- ZHCAEJ4 的图、表、公式核心结构可进入 IR。

### v0.6：Agent MD Assembly

目标：

- 实现 `assemble_agent_md.py`。
- 从 IR 生成 `output/main.md`、可选 `output/parts/`、`output/assets/`、`output/provenance.json`。

验收：

- `main.md` 使用统一来源锚点格式。
- 大文档和多 sheet 文档按阈值生成 `parts/`。
- 源页码、图片、表格、公式、代码块可追溯。

### v0.7：Validators 与 Unresolved

目标：

- 补齐跨阶段 validators。
- 实现 gate 统一输出协议。
- 实现 hash 失效检测。
- 实现 `run_validators.py`。

验收：

- `[VISION_PLACEHOLDER_]`、`[TODO]`、U+FFFD、控制字符、`[未解析: ...]` 均可被检查。
- blocker unresolved 会阻断后续 package。
- stale 下游产物会被 gate 判定为 fail。

### v0.8：视觉验收 Gate

目标：

- 实现 `render_agent_md_preview.py`。
- 实现 `build_visual_review_packet.py`。
- 生成 HTML、截图、contact sheet、render diagnostics。
- 生成 `anchor_map.json` 和源页并排对照图。
- 建立风险分级视觉验收。

验收：

- high-risk 文档必须生成 `visual_acceptance.md`。
- 可基于视觉验收包检查渲染结果与源页一致性。
- `status=fail` 时无法 package。

### v0.9：专项审计

目标：

- 寄存器表、参数表、报价表等硬表审计。
- 公式视觉校对。
- 图表/截图专项审计。
- 批注与修订内容保留。

验收：

- ZHCAEJ4 的寄存器表可做硬列审计。
- Word 批注样例可保留锚点。

### v1.0：Golden Example

目标：

- 以 ZHCAEJ4 / TAA5212 文档作为 golden example。
- 对比基础 skill 输出与 workflow 输出。
- 固化质量标准和回归测试。

验收：

- 图片资产完整。
- 公式 LaTeX 化。
- 寄存器表可校验。
- 低置信度内容可追踪。
- `main.md` 达到人工完善版的主要结构质量。

## 17. 测试策略

第一批测试文档：

1. 技术 PDF：ZHCAEJ4 / TAA5212 应用手册。
2. 数据手册 PDF：含大量电气参数、寄存器表、图表。
3. Word 文档：含标题、表格、图片、批注。
4. PPTX：含图文布局、流程图、截图、speaker notes。
5. XLSX：含多 sheet、公式、合并单元格、图表。
6. 扫描 PDF：首期验证页面渲染+视觉描述，不承诺全文 OCR。

测试层级：

- 单元测试：tools、validators、IR schema。
- fixture 测试：各格式最小样例。
- golden path：ZHCAEJ4 完整链路。
- visual regression：HTML 渲染截图和 contact sheet 生成。
- package gate：有 blocker、断链、placeholder、U+FFFD 时必须 fail。

测试资产约束：

- `tests/_fixtures/` 只放可再分发的小样例或人工构造样例。
- 厂商源 PDF、客户文档、大体积渲染图默认不进仓库。
- `examples/` 可保留脱敏后的输出子集、manifest 和 QA 报告，用于说明预期结构。

## 18. 成功标准

项目第一阶段是否成功，不看“能否转出 Markdown”，而看：

- 任意源文档都能生成稳定 job bundle。
- 阶段枚举唯一，`STATE.json`、roles、tools、gates 全部对齐。
- 所有中间产物可追踪、可恢复、可审计。
- 所有 block 级关键内容可追溯到原文页码、slide 或 sheet range。
- 图片不丢失，并与正文上下文绑定。
- 表格不再只是抽取碎片，而能进入结构化校验。
- 公式、图表、代码、寄存器、批注等高价值内容有专项处理路径。
- 所有低置信度内容进入 `unresolved.md`。
- 大文档和多 sheet 工作簿可稳定生成 `main.md` + `parts/`。
- gate 结果有固定机器输出，hash 失效能阻断 stale 产物。
- 视觉验收可从 HTML 截图对回源页或 sheet/range。
- 最终 package 前通过 validators 和必要的视觉验收。
- `main.md` 能成为 Agent 后续问答、分析、写作、投标、研发、知识库构建的可靠资料。

## 19. 下一步建议

执行起点先做三件事：

1. 创建正式项目目录 `agent-friendly-md`，避免空格路径。
2. 定稿 `WORKFLOW.md`：唯一 phase table、项目根命令形态、显式 gate 协议、产物晋升、hash 失效检测、job bundle 目录。
3. 写 `docs/ir-schema.md`：`blocks.jsonl` 唯一载体、table / figure / formula 子 schema、source_anchor 规范、资产命名规则。

然后再接入现有 skill backend。这样不会把工作流再次写成一个超长 skill，而会形成一个可运行、可验证、可扩展的文档编译 OS。
