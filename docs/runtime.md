# Runtime & Dependencies

## Python

- 需要 Python ≥ 3.10。本机为 3.13（Homebrew），命令名是 `python3`（无 `python`）。
- v0.1 的工具/validator 是**纯 stdlib**，无需安装任何第三方包即可运行与测试。

## 推荐：项目 venv

```bash
cd "agent-friendly-md"
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
```

`.venv/` 已在 `.gitignore`。建好后 `scripts/run_python.py` 会沿用当前解释器。

## 按里程碑安装依赖

`doctor.py` 报告每个 phase 组的就绪状态。按需安装：

```bash
# Phase 1 提取（v0.2）—— 本机已有 PyMuPDF/openpyxl，通常只缺这三个
python -m pip install python-docx python-pptx Pillow

# Phase 6 视觉验收（v0.8）
python -m pip install playwright
python -m playwright install chromium
brew install pandoc          # 系统二进制，非 pip 包
npm install -g @mermaid-js/mermaid-cli
# 离线公式：vendor/katex/ 已存放 KaTeX dist 资产
```

## 系统工具（已在本机确认）

| 工具 | 状态 | 用途 |
| --- | --- | --- |
| pandoc 3.9 | ✓ | Markdown→HTML 渲染（视觉验收） |
| node v22 / npx | ✓ | mermaid 本地渲染 |
| mmdc 11.15 | ✓ | Mermaid CLI |
| KaTeX vendor assets | ✓ | 离线公式渲染资产 |
| tesseract | ✓ | 可选 OCR（v1.x） |
| playwright + chromium | ✓ | 视觉验收截图/contact sheet |

## OCR 策略

- v0.x 不把扫描件全文 OCR 作为硬承诺。
- 扫描件首期走「整页渲染 + 多模态视觉描述 + 低置信度标注」。
- OCR 引擎选型放 v1.x（Tesseract / PaddleOCR / 云端），但必须保留来源页与置信度。

## doctor 自检

```bash
python3 scripts/run_python.py tools/doctor.py        # 人读
python3 scripts/run_python.py tools/doctor.py --json  # 机器读
```

退出 0 表示 core（v0.1 运行时）就绪；缺失的 phase/可选依赖只报告不阻断。
项目路径含空格时会给出非阻断警告——命令一律加引号即可。
