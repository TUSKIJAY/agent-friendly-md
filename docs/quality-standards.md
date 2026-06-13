# Quality Standards

最终 `main.md`（及分卷 `parts/`）的硬标准（PLAN §2）。

## 完美 Agent Friendly Markdown 标准

- **不压缩、不中断、不过度转义原文**：正文忠实保留信息密度；公式/代码/寄存器/参数表不退化为散乱自然语言。
- **清除噪声**：删重复页眉页脚、页码、反馈链接、重复公司名/logo、导航、装饰图；但免责声明、版权、表注脚、
  法律条款、重要水印不得误删。
- **所有表格转 Markdown 表或结构化附表**：含 PDF 文本层表、Office 表、图片表、跨页表；复杂硬表有结构化审计记录。
- **所有公式用 LaTeX**：保留方程编号，校对上下标/根号/分数/希腊字母/符号方向。
- **所有图片独立保存并语义命名**：存 `assets/`，按内容命名（见 [ir-schema.md](ir-schema.md) §6），相对路径插入。
- **图文绑定**：每张图有图号、caption、来源页、语义说明；复杂框图可加 Mermaid 重绘，但原图必须保留。
- **源页码可追溯**：每个 block / 图 / 表 / 公式 / 代码块可追溯到 PDF 页 / PPT slide / Excel sheet-range /
  Word 页或章节路径+段落锚点。
- **原文与编者加工分层**：修正/重绘/估读/推断/疑似原文错误用「编者注 / 审计注 / 估读标注」标明。
- **低置信度显性化**：OCR 不确定、截图估读、表格合并失败、图小、源疑似错误 → 进 `unresolved.md` 或文内标注。
- **渲染后可读**：最终渲染成 HTML/截图，经视觉验收确认图片/公式/表格/Mermaid/版面在人眼下正常。

## 风险分级与视觉验收强度（PLAN §14）

| risk_level | 适用文档 | 视觉验收强度 |
| --- | --- | --- |
| low | 纯文本 `.md/.txt`、简单 Word | validator-only + 首屏截图 |
| medium | 普通 PDF/PPT、含少量图片/表格 | HTML 渲染 + 抽样截图 + 关键 assets 检查 |
| high | 技术/数据手册、扫描件、大表/公式密集、图纸/框图密集 | 全量视觉验收包 + contact sheet + 多模态审阅 |

contact sheet 抽样：≤30 页全量；31–100 页首尾+每章首页+所有图表公式页+随机 10%；>100 页每章首页+
所有 high-risk block 页+随机 5%（记 seed）。

`risk_level` 可自动上调；**下调必须写入 `qa_report.md`**，说明依据和责任 phase（PLAN §6）。

## 降维分级（继承自 backend）

| 等级 | 含义 | 典型对象 |
| --- | --- | --- |
| L0 无损结构化 | 原生数据精确还原 | 原生表→MD表、OMML→LaTeX、原生图表→数据表 |
| L1 估读结构化 | 从图像重建并标"估读" | 图表截图→估读表、流程图→mermaid、公式截图→LaTeX |
| L2 散文描述 | 视觉模型语义描述 | UI 截图、照片、设计稿 |
| L3 诚实占位 | `[未解析: xxx]` | 一切解析失败对象 |

三条铁律：绝不静默丢失（最低落 L3）；估读必须标注；删除需用户确认。

## Golden 回归检查

ZHCAEJ4 / TAA5212 类技术文档在 Phase 6/7 前后运行：

```bash
python3 scripts/run_python.py tools/check_golden_quality.py --job "<job-dir>" \
  --baseline-md "<skill-output.md>" --expect figure --expect formula --expect register
```

该检查把本页标准机械化为 `review/golden_quality.json`：图片资产完整、公式 LaTeX 化、寄存器表审计、
低置信度追踪、来源锚点、placeholder 清零，以及 workflow 输出相对基础 skill 输出的结构差异。
