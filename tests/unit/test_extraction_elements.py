"""Tests for Phase 1 normalized extraction elements."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import extraction_elements as EE  # noqa: E402
from lib import paths as P  # noqa: E402


class TestExtractionElements(unittest.TestCase):
    def test_skeleton_maps_to_elements_and_back(self):
        text = "# Title\n\nBody\n\n| A |\n| --- |\n| 1 |\n"
        elements = EE.elements_from_skeleton(text, "source/doc.md", ".md")
        self.assertEqual([e["element_type"] for e in elements], ["heading", "paragraph", "table"])
        self.assertTrue(all(e["evidence_level"] == "native" for e in elements))
        self.assertIn("source_anchor.line_range", elements[0]["native_metadata"]["unavailable"])

        blocks = EE.blocks_from_elements(elements)
        self.assertEqual([b["type"] for b in blocks], ["heading", "para", "table"])
        self.assertEqual(blocks[0]["id"], "block_heading_001")
        self.assertEqual(blocks[1]["evidence_level"], "native")

    def test_write_and_read_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            P.ensure_skeleton(root)
            elements = EE.elements_from_skeleton("Body\n", "source/doc.txt", ".txt")
            EE.write_elements(root, elements)
            self.assertTrue((root / P.EXTRACT_ELEMENTS).is_file())
            self.assertEqual(EE.read_elements(root), elements)

    def test_meta_patch_records_stats(self):
        elements = EE.elements_from_skeleton("# T\n\nBody\n", "source/doc.md", ".md")
        meta = EE.update_extract_meta({"source_format": ".md"}, elements, ".md")
        self.assertEqual(meta["backend"]["element_output"], "compatibility_shim")
        self.assertEqual(meta["element_count"], 2)
        self.assertEqual(meta["evidence_level_stats"]["native"], 2)
        self.assertEqual(meta["coverage"]["elements_without_source_anchor"], 0)


if __name__ == "__main__":
    unittest.main()
