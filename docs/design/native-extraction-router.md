# Native Structure Extraction Router

创建日期：2026-06-14

本设计把 Phase 1 抽取从“后端直接给 Markdown skeleton”扩展为“先生成规范化
extraction elements，再进入 Document IR”。Phase 0-7 阶段模型不变，`ir/blocks.jsonl`
仍是唯一正文载体。

## 目标

每种源格式优先使用自己的原生结构层：

- PDF 优先 text layer、页码、layout 和 bbox。
- DOCX 优先 OOXML paragraph、style、table、comment、relationship。
- PPTX 优先 slide shape tree、placeholder、table、picture、notes。
- XLSX 优先 workbook、sheet、range、formula、hidden state、chart。
- Markdown/TXT 优先 AST 或 line range。

原生证据不足时，再显式进入 OCR、VLM 或 Agent review。所有路径最终进入同一套
Document IR、provenance、QA、visual acceptance 和 package gate。

## 当前实现边界

当前 vendored backend 仍输出：

```text
extracted/text/*_skeleton.md
extracted/extract_meta.json
extracted/images/
extracted/pages/
```

因此 R1 采用兼容 shim：

```text
skeleton/meta
  -> extracted/elements.jsonl
  -> build_ir.py
  -> ir/blocks.jsonl
```

shim 不宣称无损恢复原生结构。bbox、shape id、cell range、line range 等当前 skeleton 无法
提供的字段，必须写入 `native_metadata.unavailable`，不得伪造。

## Element Contract

`extracted/elements.jsonl` 每行一个 element：

```json
{
  "schema_version": "agent-extraction-elements/0.1",
  "element_id": "element_000001",
  "source_type": "pdf|docx|pptx|xlsx|md|txt",
  "element_type": "heading|paragraph|list|table|formula|image|chart|note|comment|code",
  "content": {},
  "source_anchor": {"kind": "pdf_page", "source_file": "source/example.pdf", "page": 1},
  "native_metadata": {
    "compatibility_source": "skeleton",
    "ir_block_type": "para",
    "unavailable": ["source_anchor.bbox"]
  },
  "evidence_level": "native",
  "confidence": 0.95,
  "needs_review": false
}
```

`source_anchor` 复用 `docs/ir-schema.md` 中的既有 kind，不新增旁路 locator。`evidence_level`
只描述内容证据来源；定位可靠性由 anchor 完整度和 Phase 6 源侧证据覆盖表达。

## Validator Rules

Phase 1 gate 必须检查：

- `elements.jsonl` 存在并可解析。
- 每个 element 有 `source_anchor`、`confidence`、`needs_review` 和已知 `element_type`。
- `evidence_level` 属于 `native|ocr|vlm|agent_reviewed`。
- `vlm` element 不能在未审阅状态下标记为 `needs_review=false`。
- skeleton shim 生成的 element 必须声明无法恢复的高精度字段。

Phase 2 `build_ir.py` 优先读取 `elements.jsonl`。仅当 element 文件不存在时，才使用旧
`skeleton_parser.py` 回退路径。

## Native Router Probes

当前实现仍以 skeleton 为兼容输入，但 Phase 1 会额外读取源文件的原生结构并只写入可验证字段：

- PDF: PyMuPDF text layer coverage、`extracted/pdf_text_blocks.jsonl`、真实 text block
  `bbox`、`backend_element_id`、`layout_zone`。
- DOCX: OOXML table 顺序、image relationship id、comments.xml comment id、隐藏/删除文本审计。
- PPTX: slide shape id、shape name、z-order、EMU bbox、placeholder、table cell range、chart/picture shape、speaker notes/off-slide 审计。
- XLSX: worksheet used range、Excel table name/range、formula cell、chart id/anchor cell、merged range、hidden sheet/row/column 审计。
- MD/TXT: 原文 line range。

如果探针无法唯一定位对象，字段继续留在 `native_metadata.unavailable`，不得用估算值填充。
图片、图表和低 coverage PDF 页只会设置 `needs_vlm`、`needs_ocr` 或
`needs_agent_review` 标记；OCR/VLM 结论必须作为 evidence 进入审阅链路，不能冒充
`native` 正文。

## Review Evidence

PDF text-layer 探针会在可用时生成 bbox overlay：

```text
review/visual_acceptance/extraction_overlays/pdf_page_bbox_overlay/
review/visual_acceptance/evidence_manifest.json
```

Phase 6 的 visual review packet 会把 `evidence_manifest.json` 纳入已审阅 artifact 列表，并在
`output/qa_report.md` 汇总 `evidence_level` 分布。

## OKF-Style Export

`tools/export_okf.py` 是可选下游导出器，不属于 Phase 0-7 阶段模型：

```bash
python3 scripts/run_python.py tools/export_okf.py --job "<job-dir>" --package "<package-dir>" --out "<okf-dir>"
```

导出器先运行 `validators/package_gate.py --job ...`，失败则不写 OKF 输出。通过后生成独立的
Markdown concept bundle：

```text
index.md
document.md
parts/*.md
log.md
```

concept frontmatter 映射 `type: Reference`、`title`、`description`、`resource`、`tags`、
`timestamp`，并保留 `afmd_manifest`、`afmd_provenance`、`afmd_qa_report`、
`afmd_visual_acceptance` 指向原 package/support 文件。OKF-style 输出不替代 `_agent-md/`
中的 QA、provenance、manifest 和 package metadata。
