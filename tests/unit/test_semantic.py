"""Unit tests for the Phase 3 semantic transforms (backend-free)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import ir as IR


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _heading(bid, level, text):
    return IR.new_block(bid, "heading", {"kind": "pdf_page", "source_file": "s", "page": 1},
                        confidence=1.0, needs_review=False, heading={"level": level, "text": text})


def _para(bid, text, page=1):
    return IR.new_block(bid, "para", {"kind": "pdf_page", "source_file": "s", "page": page},
                        confidence=1.0, needs_review=False, content={"text": text})


def _table(bid, columns, page):
    return IR.new_block(bid, "table", {"kind": "pdf_page", "source_file": "s", "page": page},
                        confidence=0.95, needs_review=False, title=None,
                        table={"columns": columns, "header_rows": [0], "rows": [],
                               "continues_from": None, "continues_to": None,
                               "audit": {"row_count": 0, "column_count": len(columns), "hard_column_check": "pass"}})


def _formula(bid, latex):
    return IR.new_block(bid, "formula", {"kind": "pdf_page", "source_file": "s", "page": 1},
                        confidence=0.9, needs_review=True,
                        formula={"equation_no": None, "latex": latex, "plain_text_source": latex,
                                 "visual_check": "pending", "control_source": None})


def _figure(bid, asset_file):
    return IR.new_block(bid, "figure", {"kind": "pdf_page", "source_file": "s", "page": 1},
                        confidence=0.5, needs_review=True,
                        figure={"figure_no": None, "caption": None, "asset_id": f"asset_{bid}",
                                "asset_file": asset_file, "description": None, "estimated_values": []})


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.mod = _load("compile_structure")

    def test_heading_level_remap(self):
        blocks = [_heading("h1", 1, "A"), _heading("h2", 3, "B"), _heading("h3", 5, "C")]
        n = self.mod.normalize_headings(blocks)
        self.assertEqual([b["heading"]["level"] for b in blocks], [1, 2, 3])
        self.assertEqual(n, 2)  # levels 3->2 and 5->3 changed
        self.assertEqual(blocks[1]["heading"]["raw_level"], 3)

    def test_noise_flag(self):
        blocks = [_para(f"p{i}", "第 1 页 公司名", page=i) for i in range(1, 4)] + [_para("p9", "正文")]
        n = self.mod.flag_noise(blocks)
        self.assertEqual(n, 3)
        self.assertTrue(blocks[0]["content"]["likely_noise"])
        self.assertNotIn("likely_noise", blocks[3]["content"])

    def test_noise_does_not_flag_caption(self):
        # 3 non-caption repeats (reaches threshold) + 1 caption with identical text
        blocks = [_para(f"p{i}", "图 1 重复标题", page=i) for i in range(1, 4)]
        cap = _para("pc", "图 1 重复标题", page=4)
        cap["content"]["is_caption_for"] = "block_figure_001"
        blocks.append(cap)
        n = self.mod.flag_noise(blocks)
        self.assertEqual(n, 3)  # only the 3 non-caption paras are flagged
        self.assertNotIn("likely_noise", cap["content"])  # caption never flagged

    def test_zone_header_footer_and_page_links_flagged_noise(self):
        header = _para("ph", "Application Note", page=1)
        header["source_zone"] = "header"
        link = _para("pl", "> [页面链接] https://example.test", page=1)
        body = _para("pb", "正文")
        n = self.mod.flag_noise([header, link, body])
        self.assertEqual(n, 2)
        self.assertTrue(header["content"]["likely_noise"])
        self.assertTrue(link["content"]["likely_noise"])
        self.assertNotIn("likely_noise", body["content"])

    def test_numbered_paragraphs_promoted_to_headings(self):
        blocks = [_para("p1", "3.1 使用 PurePath Console 的滤波器设计")]
        n = self.mod.promote_numbered_headings(blocks)
        self.assertEqual(n, 1)
        self.assertEqual(blocks[0]["type"], "heading")
        self.assertEqual(blocks[0]["heading"]["level"], 2)

    def test_caption_label_not_promoted_to_heading(self):
        # Q1: a number-prefixed device/figure label must NOT become a section
        # heading (this is what put "6 to 4 Mux" at the top of ZHCAEJ4's TOC).
        labels = [_para("p1", "6 to 4 Mux"), _para("p2", "图 3 滤波器响应"),
                  _para("p3", "4 × 4 交叉开关")]
        real = _para("p4", "6 参考资料")
        blocks = [*labels, real]
        n = self.mod.promote_numbered_headings(blocks)
        self.assertEqual(n, 1, "only the real numbered section should be promoted")
        for b in labels:
            self.assertEqual(b["type"], "para", f"{b['content']['text']} must stay a paragraph")
        self.assertEqual(real["type"], "heading")

    def test_number_prefixed_prose_not_promoted(self):
        # A bare integer + prose sentence must NOT become a section heading
        # (years, listicles, quantities), or it corrupts the TOC/title.
        prose = [_para("p1", "2024 was a good year"),
                 _para("p2", "5 things you should know about security"),
                 _para("p3", "3 apples and 2 oranges were on the table"),
                 _para("p4", "2024 年是产品发展的关键一年")]
        real = [_para("r1", "6 参考资料"), _para("r2", "2 寄存器映射")]
        blocks = [*prose, *real]
        n = self.mod.promote_numbered_headings(blocks)
        for b in prose:
            self.assertEqual(b["type"], "para", f"prose {b['content']['text']!r} must stay a paragraph")
        for b in real:
            self.assertEqual(b["type"], "heading", f"real section {b!r} must promote")
        self.assertEqual(n, len(real))


class TestTables(unittest.TestCase):
    def setUp(self):
        self.mod = _load("normalize_tables")

    def test_link_same_columns_across_pages(self):
        blocks = [_table("t1", ["A", "B"], 1), _table("t2", ["A", "B"], 2)]
        n = self.mod.link_continued_tables(blocks)
        self.assertEqual(n, 1)
        self.assertEqual(blocks[0]["table"]["continues_to"], "t2")
        self.assertEqual(blocks[1]["table"]["continues_from"], "t1")

    def test_no_link_different_columns(self):
        blocks = [_table("t1", ["A", "B"], 1), _table("t2", ["X", "Y"], 2)]
        self.assertEqual(self.mod.link_continued_tables(blocks), 0)

    def test_no_link_same_page(self):
        blocks = [_table("t1", ["A"], 1), _table("t2", ["A"], 1)]
        self.assertEqual(self.mod.link_continued_tables(blocks), 0)

    def test_page_zero_not_treated_as_missing(self):
        self.assertEqual(self.mod._page_of(_table("t", ["A"], 0)), ("page", 0))
        blocks = [_table("t1", ["A"], 0), _table("t2", ["A"], 1)]
        self.assertEqual(self.mod.link_continued_tables(blocks), 1)  # 0 != 1 -> linked


class TestFormulas(unittest.TestCase):
    def setUp(self):
        self.mod = _load("normalize_formulas")

    def test_clean_and_number_and_check(self):
        blocks = [_formula("f1", "$E=mc^2$"), _formula("f2", "\\frac{a}{b")]  # f2 unbalanced
        cleaned, flagged = self.mod.normalize_formulas(blocks)
        self.assertEqual(blocks[0]["formula"]["latex"], "E=mc^2")     # stray $ stripped
        self.assertEqual(blocks[0]["formula"]["equation_no"], "1")
        self.assertEqual(blocks[0]["formula"]["visual_check"], "ok")
        self.assertEqual(blocks[1]["formula"]["visual_check"], "needs_review")
        self.assertTrue(blocks[1]["needs_review"])
        self.assertEqual(flagged, 1)

    def test_escaped_dollar_not_corrupted(self):
        blocks = [_formula("f1", "cost = 5 \\$")]   # trailing escaped dollar, no delimiters
        self.mod.normalize_formulas(blocks)
        self.assertEqual(blocks[0]["formula"]["latex"], "cost = 5 \\$")  # unchanged, not "cost = 5 \\"

    def test_idempotent_renumber(self):
        blocks = [_formula("f1", "$a$"), _formula("f2", "$b$")]
        self.mod.normalize_formulas(blocks)
        first = [(b["formula"]["latex"], b["formula"]["equation_no"]) for b in blocks]
        self.mod.normalize_formulas(blocks)  # second run
        second = [(b["formula"]["latex"], b["formula"]["equation_no"]) for b in blocks]
        self.assertEqual(first, second)  # no re-numbering / re-stripping drift


class TestSemanticize(unittest.TestCase):
    def setUp(self):
        self.mod = _load("semanticize_figures")

    def test_backfill_from_cache(self):
        blocks = [_figure("block_figure_001", "extracted/images/fig_p001_a.png")]
        n_desc, n_undesc = self.mod.backfill(blocks, {"fig_p001_a.png": "界面截图"})
        self.assertEqual((n_desc, n_undesc), (1, 0))
        self.assertEqual(blocks[0]["figure"]["description"], "界面截图")
        self.assertFalse(blocks[0]["needs_review"])

    def test_backfill_uses_original_asset_file_after_rename(self):
        blocks = [_figure("block_figure_001", "extracted/images/fig_p001_semantic.png")]
        blocks[0]["figure"]["original_asset_file"] = "extracted/images/image_001.jpg"
        n_desc, n_undesc = self.mod.backfill(blocks, {"image_001.jpg": "图 3-3：旧文件名描述"})
        self.assertEqual((n_desc, n_undesc), (1, 0))
        self.assertEqual(blocks[0]["figure"]["description"], "图 3-3：旧文件名描述")
        self.assertEqual(blocks[0]["figure"]["figure_no"], "图 3-3")
        self.assertEqual(blocks[0]["figure"]["caption"], "图 3-3：旧文件名描述")
        self.assertGreaterEqual(blocks[0]["confidence"], 0.85)

    def test_load_vision_cache_single_line_jsonl(self):
        # regression: a single-line JSONL record must NOT be read as a flat dict
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "review").mkdir()
            (root / "review" / "vision_cache.json").write_text(
                json.dumps({"file": "fig_p001_a.png", "text": "界面截图"}) + "\n", encoding="utf-8")
            cache = self.mod.load_vision_cache(root)
            self.assertEqual(cache, {"fig_p001_a.png": "界面截图"})

    def test_load_vision_cache_multiline_and_flat(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "review").mkdir()
            cache_file = root / "review" / "vision_cache.json"
            cache_file.write_text('{"file":"a.png","text":"one"}\n{"file":"b.png","text":"two"}\n',
                                  encoding="utf-8")
            self.assertEqual(self.mod.load_vision_cache(root), {"a.png": "one", "b.png": "two"})
            cache_file.write_text(json.dumps({"a.png": "flat"}), encoding="utf-8")  # old flat dict
            self.assertEqual(self.mod.load_vision_cache(root), {"a.png": "flat"})

    def test_mark_noise_figures_document_artifacts_and_duplicate_assets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "extracted/images").mkdir(parents=True)
            (root / "extracted/images/logo.png").write_bytes(b"logo")
            (root / "extracted/images/chart_a.png").write_bytes(b"same-chart")
            (root / "extracted/images/chart_b.png").write_bytes(b"same-chart")
            blocks = [
                _figure("block_figure_001", "extracted/images/logo.png"),
                _figure("block_figure_002", "extracted/images/chart_a.png"),
                _figure("block_figure_003", "extracted/images/chart_b.png"),
            ]
            blocks[0]["figure"]["description"] = "MSIG insurance company logo."
            blocks[1]["figure"]["description"] = "A useful chart."
            blocks[2]["figure"]["description"] = "The same useful chart repeated."
            n = self.mod.mark_noise_figures(blocks, root)
            self.assertEqual(n, 2)
            self.assertEqual(blocks[0]["figure"]["noise_reason"], "decorative_or_document_artifact")
            self.assertNotIn("likely_noise", blocks[1]["figure"])
            self.assertEqual(blocks[2]["figure"]["noise_reason"], "duplicate_asset")


class TestReport(unittest.TestCase):
    def test_upsert_idempotent(self):
        from lib import report
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "semantic_compile.md"
            report.upsert_section(path, "Semantic Compile", "toolA", "- first run")
            report.upsert_section(path, "Semantic Compile", "toolB", "- other")
            report.upsert_section(path, "Semantic Compile", "toolA", "- second run")  # replace
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("# Semantic Compile"), 1)
            self.assertEqual(text.count("## toolA"), 1)       # not duplicated
            self.assertIn("- second run", text)
            self.assertNotIn("- first run", text)            # old content replaced
            self.assertIn("## toolB", text)                  # other sections preserved


if __name__ == "__main__":
    unittest.main()
