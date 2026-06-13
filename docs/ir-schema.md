# Document IR Schema

Document IR 是单一事实源。本文件定义其存储契约、block 子 schema、source_anchor 规范和资产命名规则。
对应 `PLAN.md` §9–§10，并落定 review-003 minor 1/6/8/9/10 中归属 IR 的部分。

> 实现里程碑：v0.3（`build_ir.py` + `validate_ir.py` + `validate_provenance.py`）。
> 本文件先于实现冻结契约，使 v0.3 编码有据可依。

---

## 1. 存储契约：唯一载体 + 可再生成投影

| 文件 | 角色 | 是否手工维护 |
| --- | --- | --- |
| `ir/blocks.jsonl` | **block 内容唯一载体**（每行一个 block） | 由工具写，不手工编辑 |
| `ir/document.ir.json` | 只存 metadata、stores 路径、`block_order`、`relations`、`stats` | 由工具写 |
| `ir/assets.index.json` | **投影**：可由 block 的 asset 引用 + 实体文件再生成 | 否 |
| `ir/provenance.json` | **投影**：可由 `blocks.jsonl` 的 `source_anchor` 再生成 | 否 |
| `output/provenance.json` | **投影**：同上，Phase 5 编译产出 | 否 |
| `ir/summary.seed.md` | 摘要种子，组装时作为 `main.md` 摘要输入（review-003 minor 1） | 由 Agent 在语义阶段写 |

`validate_ir.py` 五条机械检查：

1. `document.ir.json.block_order` 中的 id 在 `blocks.jsonl` 中全部存在。
2. `blocks.jsonl` 中不存在重复 id。
3. `assets.index.json` 可由 block asset 引用 + 实体文件重新生成（再生成结果须与磁盘一致）。
4. `ir/provenance.json` 与 `output/provenance.json` 都可由 `blocks.jsonl` 的 `source_anchor` 投影生成。
5. 任一投影与唯一载体不一致 → fail。

### document.ir.json 顶层

```json
{
  "schema_version": "agent-document-ir/0.1",
  "document_id": "zhcaej4",
  "metadata": {"title": "...", "source_type": "pdf", "source_file": "source/zhcaej4.pdf", "language": "zh-CN"},
  "stores": {"blocks": "blocks.jsonl", "assets_index": "assets.index.json", "provenance": "provenance.json"},
  "block_order": ["block_heading_001", "block_para_001", "block_figure_003"],
  "relations": [{"from": "block_figure_003", "to": "asset_fig_3_3", "type": "uses_asset"}],
  "stats": {"block_count": 128, "asset_count": 24}
}
```

### block 公共字段（blocks.jsonl 每行）

每个 block 必须有：`id`、`type`、`source_anchor`、`confidence`、`content` 或结构化子字段、`needs_review`。

block id 前缀约定：`block_heading_`、`block_para_`、`block_list_`、`block_table_`、`block_figure_`、
`block_formula_`、`block_code_`。asset id 前缀 `asset_`。

---

## 2. source_anchor 规范

每个 block 级内容必须可追溯到原文位置。

PDF：

```json
{"kind": "pdf_page", "source_file": "source/zhcaej4.pdf", "page": 6, "page_label": "p.6", "bbox": [72, 144, 520, 680]}
```

PPTX：

```json
{"kind": "slide", "source_file": "source/deck.pptx", "slide": 3, "shape_id": "shape_12"}
```

XLSX：

```json
{"kind": "sheet_range", "source_file": "source/model.xlsx", "sheet": "Sheet1", "range": "A12:D30"}
```

DOCX：

```json
{"kind": "docx_anchor", "source_file": "source/report.docx", "page": 12,
 "heading_path": ["2 技术方案", "2.3 实施步骤"], "paragraph_index": 84}
```

Word 页码不可稳定获取时，使用 `heading_path + paragraph_index`，并在 `qa_report.md` 说明页码限制。

---

## 3. Table 子 schema

表格 block 不能只存 Markdown 字符串，必须存结构化单元格：

```json
{
  "id": "block_table_001",
  "type": "table",
  "title": "表 3-4. 数字双二阶滤波器 1-6 的可编程系数寄存器",
  "source_anchor": {"kind": "pdf_page", "page": 9},
  "table": {
    "columns": ["地址", "寄存器", "寄存器说明", "复位值"],
    "header_rows": [],
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
    "audit": {"row_count": 120, "column_count": 4, "hard_column_check": "pass"}
  },
  "confidence": 0.95,
  "needs_review": false
}
```

`columns` 承载表头，`rows` 只含数据行（不含表头），`header_rows` 列出 `rows` 内的额外表头行（通常为空 `[]`）。

`validate_tables.py` 校验：Markdown 投影列数 == `columns` 长度、表头行一致、结构化 table 与 Markdown 投影一致、空列瀑布检测。

---

## 4. Figure 子 schema

```json
{
  "id": "block_figure_003",
  "type": "figure",
  "figure": {
    "figure_no": "图 3-3",
    "caption": "PurePath™ Console 可编程双二阶滤波器示例",
    "asset_id": "asset_fig_p006_purepath_biquad_example",
    "asset_file": "extracted/images/fig_p006_purepath_biquad_example.png",
    "description": "Programmable Biquads 页，ADC 选项卡……",
    "estimated_values": [{"label": "60Hz notch depth", "value": "约 -36dB", "basis": "图上估读"}]
  },
  "source_anchor": {"kind": "pdf_page", "page": 6},
  "confidence": 0.88,
  "needs_review": true
}
```

图文绑定：每个 figure block 必须有 `figure_no` + `caption` + `asset_id` + 来源页；估读值必须标 `basis: 图上估读`。
`asset_file` 是 bundle 相对路径，把 `asset_id` 桥接到磁盘实体文件，`assets.index.json` 投影据此校验文件存在性。

---

## 5. Formula 子 schema

```json
{
  "id": "block_formula_001",
  "type": "formula",
  "formula": {
    "equation_no": "1",
    "latex": "H(z)=\\frac{b_{0}+b_{1}z^{-1}+b_{2}z^{-2}}{1+a_{1}z^{-1}+a_{2}z^{-2}}",
    "plain_text_source": "H z = ...",
    "visual_check": "pass",
    "control_source": "source/slaaeh6.pdf p.3"
  },
  "source_anchor": {"kind": "pdf_page", "page": 3},
  "confidence": 0.96,
  "needs_review": false
}
```

所有公式用 LaTeX，保留方程编号；不保留 OCR 式线性碎片。

---

## 6. 资产命名规则（PLAN §10，review-003 minor 6）

- 文件名只用 ASCII 小写字母、数字、短横线、下划线和扩展名。
- 命名格式：`<kind>_<source_ref>_<semantic_slug>.<ext>`。
- **统一示例**（页码 / slide / range 在 `source_ref` 段，不放尾部）：
  - `fig_p006_purepath_biquad_example.png`
  - `tbl_p009_coefficient_registers.png`
  - `fig_slide03_architecture_overview.png`
  - `chart_sheet1_a12_d30_quarterly_sales.png`
- 中文 caption 转短英文语义 slug；无法可靠转写时用 `fig_p006_asset_003.png`。
- 文件名主体 ≤ 96 字符；冲突时追加稳定序号 `_02`。
- `validate_links.py` 校验字符集、长度和碰撞。

---

## 7. Markdown 来源锚点

`main.md`（及分卷 `parts/`）每个主要 block 携带来源锚点：

- PDF：`〔源 p.N〕` 或跨页 `〔源 p.N-M〕`
- PPT：`〔源 slide N〕`
- Excel：`〔源 Sheet1!A12:D30〕`
- Word：`〔源 p.N〕`，不可得时 `〔源 2.3 实施步骤 / 段 84〕`
- 编者加工：`> **编者注**：...`；审计说明：`> **审计注**：...`；估读必须写"图上估读"。
