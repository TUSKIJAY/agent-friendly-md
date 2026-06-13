"""Unit tests for asset naming and figure/caption/reference binding (v0.4)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import ir as IR
from lib import naming


def _load_link_assets():
    spec = importlib.util.spec_from_file_location("link_assets", PROJECT_ROOT / "tools" / "link_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestNaming(unittest.TestCase):
    def test_ascii_slug(self):
        self.assertEqual(naming.ascii_slug("PurePath Console Example"), "purepath_console_example")
        self.assertEqual(naming.ascii_slug("双二阶滤波器"), "")  # no ASCII -> empty

    def test_source_ref(self):
        self.assertEqual(naming.source_ref({"kind": "pdf_page", "page": 6}), "p006")
        self.assertEqual(naming.source_ref({"kind": "slide", "slide": 3}), "slide03")
        self.assertEqual(naming.source_ref({"kind": "sheet_range", "sheet": "Data"}), "sheet_data")
        self.assertEqual(naming.source_ref({"kind": "docx_anchor"}), "doc")

    def test_asset_filename_fallback_and_collision(self):
        existing: set[str] = set()
        a = naming.asset_filename("fig", {"kind": "pdf_page", "page": 6}, None, 1, ".png", existing)
        self.assertEqual(a, "fig_p006_asset_001.png")
        existing.add(a)
        b = naming.asset_filename("fig", {"kind": "pdf_page", "page": 6}, None, 1, ".png", existing)
        self.assertEqual(b, "fig_p006_asset_001_02.png")  # collision suffix

    def test_asset_filename_with_caption(self):
        a = naming.asset_filename("fig", {"kind": "pdf_page", "page": 6},
                                  "PurePath Console", 1, ".png", set())
        self.assertEqual(a, "fig_p006_purepath_console.png")

    def test_is_valid_asset_name(self):
        self.assertTrue(naming.is_valid_asset_name("fig_p006_example.png"))
        self.assertFalse(naming.is_valid_asset_name("Fig 3-3.png"))   # space + uppercase
        self.assertFalse(naming.is_valid_asset_name("图_3.png"))       # non-ascii
        self.assertFalse(naming.is_valid_asset_name("fig_p006_example."))  # trailing dot, no ext
        self.assertFalse(naming.is_valid_asset_name("fig_p006_example"))   # no extension

    def test_asset_filename_empty_ext_defaults(self):
        a = naming.asset_filename("fig", {"kind": "pdf_page", "page": 6}, None, 1, "", set())
        self.assertTrue(naming.is_valid_asset_name(a))  # generator never emits an invalid name
        self.assertTrue(a.endswith(".png"))


def _fig(bid, **fig):
    base = {"figure_no": None, "caption": None, "asset_id": f"asset_{bid}",
            "asset_file": f"extracted/images/{bid}.png", "description": None, "estimated_values": []}
    base.update(fig)
    return IR.new_block(bid, "figure", {"kind": "pdf_page", "source_file": "s", "page": 6},
                        confidence=0.5, needs_review=True, figure=base)


def _para(bid, text):
    return IR.new_block(bid, "para", {"kind": "pdf_page", "source_file": "s", "page": 6},
                        confidence=1.0, needs_review=False, content={"text": text})


class TestBinding(unittest.TestCase):
    def setUp(self):
        self.mod = _load_link_assets()
        self.blocks = [
            _fig("block_figure_001"),
            _para("block_para_001", "图 3-3. 双二阶滤波器示意"),
            _para("block_para_002", "如图 3-3 所示，滤波器具有可编程系数。"),
        ]

    def test_bind_captions(self):
        n = self.mod.bind_captions(self.blocks)
        self.assertEqual(n, 1)
        fig = self.blocks[0]["figure"]
        self.assertEqual(fig["figure_no"], "图 3-3")
        self.assertIn("双二阶", fig["caption"])
        self.assertEqual(self.blocks[1]["content"]["is_caption_for"], "block_figure_001")

    def test_link_references(self):
        self.mod.bind_captions(self.blocks)
        rels = self.mod.link_references(self.blocks)
        # para_002 references the figure; the caption para_001 must NOT
        self.assertIn({"from": "block_para_002", "to": "block_figure_001", "type": "references"}, rels)
        self.assertFalse(any(r["from"] == "block_para_001" for r in rels))

    def test_shared_caption_binds_one_figure(self):
        blocks = [_fig("block_figure_001"), _para("block_para_001", "图 3-3. 共享标题"),
                  _fig("block_figure_002")]
        n = self.mod.bind_captions(blocks)
        self.assertEqual(n, 1)  # caption claimed by exactly one figure
        self.assertEqual(blocks[0]["figure"]["figure_no"], "图 3-3")
        self.assertIsNone(blocks[2]["figure"]["figure_no"])  # second figure not double-bound

    def test_reference_boundary_no_prefix_match(self):
        blocks = [_fig("block_figure_001"), _para("block_para_001", "图 3 概览"),
                  _fig("block_figure_002"), _para("block_para_002", "图 3-3 细节"),
                  _para("block_para_003", "详见 图 3-3 的说明。")]
        self.mod.bind_captions(blocks)
        rels = self.mod.link_references(blocks)
        targets = {r["to"] for r in rels if r["from"] == "block_para_003"}
        self.assertEqual(targets, {"block_figure_002"})  # cites 图 3-3, NOT 图 3

    def test_caption_letter_first_number(self):
        blocks = [_fig("block_figure_001"), _para("block_para_001", "表 A1 附录数据")]
        self.mod.bind_captions(blocks)
        self.assertEqual(blocks[0]["figure"]["figure_no"], "表 A1")


class TestRename(unittest.TestCase):
    def setUp(self):
        self.mod = _load_link_assets()

    def test_rename_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "extracted" / "images").mkdir(parents=True)
            (root / "extracted" / "images" / "image_001.png").write_bytes(b"x")
            blocks = [_fig("block_figure_001", asset_id="asset_image_001",
                           asset_file="extracted/images/image_001.png")]
            n1 = self.mod.rename_assets(blocks, root)
            name1 = blocks[0]["figure"]["asset_file"]
            n2 = self.mod.rename_assets(blocks, root)
            name2 = blocks[0]["figure"]["asset_file"]
            self.assertEqual((n1, n2), (1, 0))         # first renames, second is a no-op
            self.assertEqual(name1, name2)             # stable filename across runs
            self.assertNotIn("_02", name2)             # no oscillation suffix
            self.assertTrue((root / name2).is_file())  # file actually present


if __name__ == "__main__":
    unittest.main()
