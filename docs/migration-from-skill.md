# Backend 迁移：doc-to-agent-markdown → agent-friendly-md

v0.2 不重造基础 extractor，而是把现有 `doc-to-agent-markdown` skill 作为 **extraction backend**，
把它的中间产物映射进 job bundle。

## Backend 位置与接口（已核查）

源：`<...>/LLM/anti_skills/doc-to-agent-markdown/`

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `SKILL.md` | 251 | 六阶段执行流程说明 |
| `doc_to_md_extractor.py` | 1490 | 提取器：docx/pdf/pptx/xlsx/md/txt → skeleton + meta + images |
| `doc_to_md_assembler.py` | 418 | 组装器：skeleton + 视觉描述 + 摘要 → `{name}_agent.md` |
| `tests/run_tests.py` | 609 | 自带回归测试（v0.2 验收要求全 PASS） |

> 注意：backend 旧名 `docx_to_llm_markdown` / `doc-to-llm-markdown` 已废弃，现名 `doc-to-agent-markdown`。
> 本仓库已把它 vendor 在 [vendor/doc-to-agent-markdown/](../vendor/doc-to-agent-markdown/)（`lib/backend.py` 默认指向它），
> 无需任何外部 checkout 或工具特定的 skill 目录。

### Extractor CLI

```bash
python3 "<backend>/doc_to_md_extractor.py" "<输入文件>" [-o <workdir>] \
  [--force-page-render] [--max-rows N] [--keep-formulas] [--no-pdf-headings]
```

产出 `{name}_workdir/`：`{name}_skeleton.md`、`{name}_extract_meta.json`、`extracted_images/`。

### Assembler CLI

```bash
python3 "<backend>/doc_to_md_assembler.py" "<workdir>/<name>_skeleton.md" \
  "<workdir>/vision_descriptions_cache.jsonl" "<out>/<name>_agent.md" \
  --summary-file "<workdir>/summary.txt" --clean-decisions "<workdir>/cleaning_decisions.json"
```

## 产物映射（PLAN §3）

| Backend 产物 | job bundle 归宿 |
| --- | --- |
| `{name}_skeleton.md` | `extracted/text/` |
| `{name}_extract_meta.json` | `extracted/extract_meta.json` |
| `extracted_images/` | `extracted/images/` |
| `vision_descriptions_cache.jsonl` | `review/vision_cache.json` |
| `cleaning_decisions.json` | `review/cleaning_decisions.json` |
| `summary.txt` | `ir/summary.seed.md` |
| 质量报告（控制台/报告） | `review/imported_quality_report.md` |
| 旧 assembler 的 `{name}_agent.md` | 临时 `output/main.md`（v0.2 过渡产物，v0.6 由 IR 编译取代） |

## v0.2 验收

- backend 自带回归测试全 PASS。
- 对 PDF/DOCX/PPTX/XLSX/MD/TXT 样例跑通 Phase 0–1。
- 经旧 assembler 产出临时 `output/main.md`。
- §3 映射表全部槽位落盘到 job bundle。
- `validate_extraction.py` 复核 `document_profile` 并确认 `risk_level`（review-003 minor 8）。

## 依赖现状（本机 doctor 结果）

已装：PyMuPDF、openpyxl、pandas、tesseract、pandoc、node/npx。
缺：python-docx、python-pptx、Pillow（v0.2 前 `pip install` 即可）；playwright（v0.8）。

## 边界

- backend 是 extraction/assembly 后端，不承担 IR、provenance、gate、视觉验收——这些是本项目新增层。
- backend 的"删除需用户确认"铁律保留：本项目同样绝不自动删除 workdir / job bundle。
