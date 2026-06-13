"""Unit tests for the IR parser and projections (backend-free)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import ir as IR
from lib.skeleton_parser import Parser

DOCX_SKEL = """# 标题一
- 项一
- 项二
普通段落 $E=mc^2$
$$a^2+b^2=c^2$$
<!-- IMAGE: pic_001.png -->
[VISION_PLACEHOLDER_pic_001.png]
| A | B |
| --- | --- |
| 1 | 2 |
"""


class TestParser(unittest.TestCase):
    def setUp(self):
        self.Parser = Parser

    def test_docx_block_types(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        types = [b["type"] for b in p.blocks]
        self.assertEqual(types, ["heading", "list", "para", "formula", "figure", "table"])

    def test_list_items(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        lst = next(b for b in p.blocks if b["type"] == "list")
        self.assertEqual(lst["content"]["items"], ["项一", "项二"])

    def test_table_structured(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        t = next(b for b in p.blocks if b["type"] == "table")["table"]
        self.assertEqual(t["columns"], ["A", "B"])
        self.assertEqual(t["audit"]["row_count"], 1)
        self.assertEqual(t["audit"]["hard_column_check"], "pass")
        self.assertEqual(t["rows"][0][0]["text"], "1")

    def test_figure_asset(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        fig = next(b for b in p.blocks if b["type"] == "figure")["figure"]
        self.assertEqual(fig["asset_id"], "asset_pic_001")
        self.assertEqual(fig["asset_file"], "extracted/images/pic_001.png")

    def test_figure_image_comment_strips_metadata(self):
        p = self.Parser("source/x.pdf", ".pdf")
        p.parse("<!-- IMAGE: image_001.jpg zone=body -->\n[VISION_PLACEHOLDER_image_001.jpg]\n")
        block = next(b for b in p.blocks if b["type"] == "figure")
        self.assertEqual(block["source_zone"], "body")
        self.assertEqual(block["figure"]["asset_id"], "asset_image_001")
        self.assertEqual(block["figure"]["asset_file"], "extracted/images/image_001.jpg")

    def test_page_render_image_comment_is_source_artifact_not_figure(self):
        p = self.Parser("source/x.pdf", ".pdf")
        p.parse("<!-- IMAGE: page_001.png zone=body page_render=true -->\n[VISION_PLACEHOLDER_page_001.png]\n正文\n")
        self.assertNotIn("figure", [b["type"] for b in p.blocks])
        self.assertEqual(len(p.blocks), 1)
        self.assertEqual(p.blocks[0]["content"]["text"], "正文")

    def test_standalone_formula(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        f = next(b for b in p.blocks if b["type"] == "formula")["formula"]
        self.assertIn("a^2+b^2=c^2", f["latex"])

    def test_inline_formula_stays_para(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        para = next(b for b in p.blocks if b["type"] == "para")
        self.assertIn("$E=mc^2$", para["content"]["text"])

    def test_docx_heading_path(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse(DOCX_SKEL)
        para = next(b for b in p.blocks if b["type"] == "para")
        self.assertEqual(para["source_anchor"]["heading_path"], ["标题一"])

    def test_pdf_page_anchor(self):
        p = self.Parser("source/x.pdf", ".pdf")
        p.parse("<!-- meta:page_start page=3 -->\n正文内容\n")
        para = next(b for b in p.blocks if b["type"] == "para")
        self.assertEqual(para["source_anchor"]["kind"], "pdf_page")
        self.assertEqual(para["source_anchor"]["page"], 3)

    def test_pptx_slide_anchor(self):
        p = self.Parser("source/x.pptx", ".pptx")
        p.parse("## Slide 2: 标题\n内容\n")
        para = next(b for b in p.blocks if b["type"] == "para")
        self.assertEqual(para["source_anchor"]["slide"], 2)

    def test_xlsx_sheet_anchor(self):
        p = self.Parser("source/x.xlsx", ".xlsx")
        p.parse("## Sheet: 数据\n| A |\n| --- |\n| 1 |\n")
        t = next(b for b in p.blocks if b["type"] == "table")
        self.assertEqual(t["source_anchor"]["sheet"], "数据")

    def test_table_with_caption_row(self):
        # separator at index 2: a caption row precedes the header
        p = self.Parser("source/x.docx", ".docx")
        p.parse("| 表3-4 系数寄存器 |\n| 地址 | 寄存器 |\n| --- | --- |\n| 0x08 | reg1 |\n")
        t = next(b for b in p.blocks if b["type"] == "table")
        self.assertEqual(t["table"]["columns"], ["地址", "寄存器"])      # header, not the caption
        self.assertEqual(t["table"]["rows"][0][0]["text"], "0x08")        # data not eaten
        self.assertIn("表3-4", t["title"])                                # caption captured, not dropped
        self.assertTrue(t["needs_review"])

    def test_formula_has_schema_fields(self):
        p = self.Parser("source/x.docx", ".docx")
        p.parse("$$a^2+b^2=c^2$$\n")
        f = next(b for b in p.blocks if b["type"] == "formula")["formula"]
        for key in ("equation_no", "latex", "plain_text_source", "visual_check", "control_source"):
            self.assertIn(key, f)

    def test_numbered_multiline_formula(self):
        p = self.Parser("source/x.pdf", ".pdf")
        p.parse("H z =\n\nb0 + b1z−1 + b2z−2\n\n1 + a1z−1 + a2z−2 (2)\n")
        f = next(b for b in p.blocks if b["type"] == "formula")["formula"]
        self.assertEqual(f["equation_no"], "2")
        self.assertIn(r"\frac", f["latex"])
        self.assertIn("b_{0}", f["latex"])
        self.assertIn("a_{2}", f["latex"])

    def test_plain_equals_before_heading_not_consumed_as_multiline_formula(self):
        p = self.Parser("source/x.pdf", ".pdf")
        p.parse("a = b\n\n## Heading (2)\n\n正文\n")
        self.assertNotIn("formula", [b["type"] for b in p.blocks])
        self.assertEqual([b["type"] for b in p.blocks], ["para", "heading", "para"])

    def test_placeholder_type_captured(self):
        p = self.Parser("source/x.pptx", ".pptx")
        p.parse("## Slide 1: t\n> [图表: 销量曲线] 说明\n")
        para = next(b for b in p.blocks if b["type"] == "para")
        self.assertEqual(para["content"].get("placeholder_type"), "图表")


class TestProjections(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            IR.new_block("block_para_001", "para", {"kind": "text_anchor", "source_file": "s"},
                         confidence=1.0, needs_review=False, content={"text": "x"}),
            IR.new_block("block_figure_001", "figure", {"kind": "text_anchor", "source_file": "s"},
                         confidence=0.5, needs_review=True,
                         figure={"asset_id": "asset_a", "asset_file": "extracted/images/a.png"}),
        ]

    def test_project_provenance_covers_all(self):
        prov = IR.project_provenance(self.blocks)
        self.assertEqual(set(prov["blocks"]), {"block_para_001", "block_figure_001"})

    def test_project_assets_index(self):
        idx = IR.project_assets_index(self.blocks, "/nonexistent")
        self.assertIn("asset_a", idx["assets"])
        self.assertEqual(idx["assets"]["asset_a"]["referenced_by"], ["block_figure_001"])
        self.assertFalse(idx["assets"]["asset_a"]["exists"])  # path doesn't exist

    def test_canonical_stable(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        self.assertEqual(IR.canonical(a), IR.canonical(b))

    def test_new_block_rejects_bad_type(self):
        with self.assertRaises(ValueError):
            IR.new_block("x", "bogus", {}, confidence=1.0, needs_review=False)


if __name__ == "__main__":
    unittest.main()
