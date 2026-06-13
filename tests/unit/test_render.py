"""Unit tests for anchor formatting, block rendering, and assembly split logic."""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import ir as IR
from lib import anchors
from lib import md_render as MD


def _load_assemble():
    spec = importlib.util.spec_from_file_location("assemble_agent_md", PROJECT_ROOT / "tools" / "assemble_agent_md.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _blk(bid, btype, anchor, **fields):
    return IR.new_block(bid, btype, anchor, confidence=1.0, needs_review=False, **fields)


class TestAnchors(unittest.TestCase):
    def test_pdf(self):
        self.assertEqual(anchors.format_anchor({"kind": "pdf_page", "page": 6}), "〔源 p.6〕")

    def test_slide(self):
        self.assertEqual(anchors.format_anchor({"kind": "slide", "slide": 3}), "〔源 slide 3〕")

    def test_sheet(self):
        self.assertEqual(anchors.format_anchor({"kind": "sheet_range", "sheet": "Data", "range": "A1:B2"}),
                         "〔源 Data!A1:B2〕")
        self.assertEqual(anchors.format_anchor({"kind": "sheet_range", "sheet": "Data", "range": None}),
                         "〔源 Data〕")

    def test_docx_heading_path(self):
        a = {"kind": "docx_anchor", "page": None, "heading_path": ["2 方案", "2.3 步骤"], "paragraph_index": 84}
        self.assertEqual(anchors.format_anchor(a), "〔源 2.3 步骤 / 段 84〕")


class TestRender(unittest.TestCase):
    def test_heading_with_anchor(self):
        b = _blk("h", "heading", {"kind": "pdf_page", "page": 3}, heading={"level": 2, "text": "标题"})
        self.assertEqual(MD.render_block(b), "## 标题　〔源 p.3〕")

    def test_noise_para_dropped(self):
        b = _blk("p", "para", {"kind": "pdf_page", "page": 1},
                 content={"text": "公司名", "likely_noise": True})
        self.assertIsNone(MD.render_block(b))

    def test_plain_para(self):
        b = _blk("p", "para", {"kind": "pdf_page", "page": 1}, content={"text": "正文内容"})
        self.assertEqual(MD.render_block(b), "正文内容")

    def test_figure_undescribed_marker(self):
        b = _blk("f", "figure", {"kind": "pdf_page", "page": 6},
                 figure={"figure_no": "图 1", "caption": "标题", "asset_id": "a",
                         "asset_file": "extracted/images/fig_p006_x.png", "description": None,
                         "estimated_values": []})
        out = MD.render_block(b)
        self.assertIn("![标题](assets/fig_p006_x.png)", out)
        self.assertIn("未解析", out)
        self.assertIn("〔源 p.6〕", out)

    def test_figure_described(self):
        b = _blk("f", "figure", {"kind": "pdf_page", "page": 6},
                 figure={"figure_no": "图 1", "caption": "标题", "asset_id": "a",
                         "asset_file": "extracted/images/x.png", "description": "界面截图",
                         "estimated_values": []})
        out = MD.render_block(b)
        self.assertIn("界面截图", out)
        self.assertNotIn("未解析", out)

    def test_figure_likely_noise_dropped(self):
        b = _blk("f", "figure", {"kind": "pdf_page", "page": 6},
                 figure={"figure_no": None, "caption": None, "asset_id": "a",
                         "asset_file": "extracted/images/logo.png", "description": "Company logo",
                         "likely_noise": True, "noise_reason": "decorative_or_document_artifact",
                         "estimated_values": []})
        self.assertIsNone(MD.render_block(b))

    def test_figure_multiline_description_is_fully_blockquoted(self):
        desc = "图 1：响应图\n\n| 频率 | 增益 |\n| --- | --- |\n| 1k | 3dB |"
        b = _blk("f", "figure", {"kind": "pdf_page", "page": 6},
                 figure={"figure_no": "图 1", "caption": "标题", "asset_id": "a",
                         "asset_file": "extracted/images/x.png", "description": desc,
                         "estimated_values": []})
        out = MD.render_block(b)
        self.assertIn("> | 频率 | 增益 |", out)
        self.assertNotIn("\n| --- | --- |", out)

    def test_formula(self):
        b = _blk("f", "formula", {"kind": "pdf_page", "page": 3},
                 formula={"equation_no": "1", "latex": "E=mc^2", "plain_text_source": "",
                          "visual_check": "ok", "control_source": None})
        out = MD.render_block(b)
        self.assertIn("$$\nE=mc^2\n$$", out)
        self.assertIn("公式 1", out)

    def test_table(self):
        b = _blk("t", "table", {"kind": "pdf_page", "page": 9}, title="表 1",
                 table={"columns": ["A", "B"], "header_rows": [0],
                        "rows": [[{"text": "1"}, {"text": "2"}]],
                        "continues_from": None, "continues_to": None,
                        "audit": {"row_count": 1, "column_count": 2, "hard_column_check": "pass"}})
        out = MD.render_block(b)
        self.assertIn("| A | B |", out)
        self.assertIn("| 1 | 2 |", out)
        self.assertIn("表 1", out)


class TestFrontMatterAndToc(unittest.TestCase):
    def test_front_matter_escapes_colon(self):
        fm = MD.render_front_matter({"title": "Sheet: 数据", "source_file": "C:\\a", "source_type": "xlsx"},
                                    {"risk_level": "high"}, {}, False)
        self.assertIn('title: "Sheet: 数据"', fm)        # colon quoted -> valid YAML
        self.assertIn('source_file: "C:\\\\a"', fm)       # backslash escaped

    def test_gfm_slug(self):
        self.assertEqual(MD.gfm_slug("Hello, World!"), "hello-world")  # punctuation dropped
        self.assertEqual(MD.gfm_slug("1.1 子节"), "11-子节")           # dot dropped, CJK kept

    def test_assign_slugs_dedup(self):
        blocks = [_blk("h1", "heading", {"kind": "pdf_page", "page": 1}, heading={"level": 1, "text": "概述"}),
                  _blk("h2", "heading", {"kind": "pdf_page", "page": 2}, heading={"level": 1, "text": "概述"})]
        self.assertEqual(set(MD.assign_heading_slugs(blocks).values()), {"概述", "概述-1"})

    def test_toc_link_matches_heading_anchor(self):
        blocks = [_blk("h1", "heading", {"kind": "pdf_page", "page": 1}, heading={"level": 1, "text": "概述"})]
        toc = MD.render_toc(blocks)
        slug = MD.assign_heading_slugs(blocks)["h1"]
        body = MD.render_block(blocks[0], heading_slug=slug)
        frag = re.search(r"\(#([^)]+)\)", toc).group(1)
        self.assertIn(f'id="{frag}"', body)  # TOC link target exists as an <a id> in the heading

    def test_table_empty_columns_keeps_cells(self):
        b = _blk("t", "table", {"kind": "pdf_page", "page": 1}, title=None,
                 table={"columns": [], "header_rows": [], "rows": [[{"text": "a"}, {"text": "b"}]],
                        "continues_from": None, "continues_to": None,
                        "audit": {"row_count": 1, "column_count": 0, "hard_column_check": "fail"}})
        out = MD.render_block(b)
        self.assertIn("a", out)
        self.assertIn("b", out)  # neither cell dropped when columns is empty


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.mod = _load_assemble()

    def test_split_sections_by_top_heading(self):
        blocks = [
            _blk("h1", "heading", {"kind": "pdf_page", "page": 1}, heading={"level": 1, "text": "一"}),
            _blk("p1", "para", {"kind": "pdf_page", "page": 1}, content={"text": "x"}),
            _blk("h2", "heading", {"kind": "pdf_page", "page": 2}, heading={"level": 1, "text": "二"}),
        ]
        secs = self.mod.split_sections(blocks)
        self.assertEqual([t for t, _ in secs], ["一", "二"])

    def test_section_range(self):
        blocks = [_blk("p1", "para", {"kind": "pdf_page", "page": 4}, content={"text": "a"}),
                  _blk("p2", "para", {"kind": "pdf_page", "page": 7}, content={"text": "b"})]
        self.assertEqual(self.mod.section_range(blocks), "p.4-7")

    def test_should_split_on_blocks(self):
        blocks = [_blk(f"p{i}", "para", {"kind": "pdf_page", "page": 1}, content={"text": "x"}) for i in range(5)]
        thr = {"max_blocks": 3, "max_markdown_bytes": 10 ** 9, "max_pages": 10 ** 9, "max_sheets": 10 ** 9}
        self.assertTrue(self.mod.should_split(blocks, 100, {}, thr))
        thr["max_blocks"] = 100
        self.assertFalse(self.mod.should_split(blocks, 100, {}, thr))

    def test_copy_assets_skips_noise_figures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "extracted/images").mkdir(parents=True)
            (root / "extracted/images/keep.png").write_bytes(b"keep")
            (root / "extracted/images/logo.png").write_bytes(b"logo")
            (root / "output/assets").mkdir(parents=True)
            (root / "output/assets/logo.png").write_bytes(b"stale")
            blocks = [
                _blk("f1", "figure", {"kind": "pdf_page", "page": 1},
                     figure={"asset_id": "a1", "asset_file": "extracted/images/keep.png",
                             "description": "Chart", "estimated_values": []}),
                _blk("f2", "figure", {"kind": "pdf_page", "page": 1},
                     figure={"asset_id": "a2", "asset_file": "extracted/images/logo.png",
                             "description": "Logo", "likely_noise": True,
                             "noise_reason": "decorative_or_document_artifact",
                             "estimated_values": []}),
            ]
            copied = self.mod.copy_assets(blocks, root)
            self.assertEqual(copied, ["assets/keep.png"])
            self.assertTrue((root / "output/assets/keep.png").is_file())
            self.assertFalse((root / "output/assets/logo.png").exists())


if __name__ == "__main__":
    unittest.main()
