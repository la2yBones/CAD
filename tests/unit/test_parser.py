# -*- coding: utf-8 -*-
"""
CAD解析器单元测试
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

import ezdxf

from src.cad_parser import CADParser
from src.intelligent_analyzer.dimension_extractor import DimensionExtractor


class TestCADParser(unittest.TestCase):
    """测试CAD解析器（支持DXF和DWG）"""

    def setUp(self):
        """测试前准备"""
        self.test_dir = project_root / "examples" / "cad_files"
        self.test_dir.mkdir(exist_ok=True)
        self.sample_dxf = self.test_dir / "sample.dxf"

    def test_parser_initialization(self):
        """测试解析器初始化"""
        if self.sample_dxf.exists():
            parser = CADParser(str(self.sample_dxf))
            self.assertIsNotNone(parser)

    def test_file_not_found(self):
        """测试文件不存在情况"""
        with self.assertRaises(Exception):
            parser = CADParser("nonexistent.dxf")
            parser.parse()

    def test_dimension_text_from_anonymous_block(self):
        """DIMENSION rendered text should be extracted from its anonymous block."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dxf_path = Path(tmp_dir) / "dimension_text.dxf"
            doc = ezdxf.new()
            msp = doc.modelspace()
            dim = msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(12, 0))
            dim.render()
            doc.saveas(dxf_path)

            parser = CADParser(str(dxf_path))
            geometry = parser.parse()
            dimensions = [e for e in geometry["entities"] if e.get("type") == "DIMENSION"]

            self.assertEqual(1, len(dimensions))
            self.assertEqual("12", dimensions[0].get("rendered_text"))
            self.assertTrue(dimensions[0].get("block_texts"))

            result = DimensionExtractor().extract_dimensions(geometry)
            self.assertEqual(1, result["total"])
            self.assertEqual(12.0, result["dimensions"][0]["value"])

    def test_dxf_unicode_diameter_escape_is_decoded(self):
        parser = CADParser("dummy.dxf")

        self.assertEqual("⌀16", parser._clean_text_content(r"\U+220516"))
        self.assertEqual("φ120", parser._format_dimension_text_for_preview(r"\U+2205120"))

        extractor = DimensionExtractor()
        result = extractor.extract_dimensions({
            "entities": [
                {"type": "TEXT", "text": r"\U+220522", "position": [0, 0, 0]},
            ]
        })

        self.assertEqual(1, result["total"])
        self.assertEqual("⌀22", result["dimensions"][0]["text"])
        self.assertEqual(22.0, result["dimensions"][0]["value"])
        self.assertEqual("直径", result["dimensions"][0]["type"])

    def test_flange_diameter_dimensions_are_extracted(self):
        dxf_path = self.test_dir / "法兰盘二视图.dxf"
        if not dxf_path.exists():
            self.skipTest("法兰盘二视图.dxf not available")

        parser = CADParser(str(dxf_path))
        geometry = parser.parse()
        result = DimensionExtractor().extract_dimensions(geometry)
        diameters = {
            item["text"]: item["value"]
            for item in result["dimensions"]
            if item["type"] == "直径"
        }

        self.assertEqual(16.0, diameters["⌀16"])
        self.assertEqual(22.0, diameters["⌀22"])
        self.assertEqual(120.0, diameters["⌀120"])

    def test_preview_normalizes_dimension_block_texts(self):
        dxf_path = self.test_dir / "法兰盘二视图.dxf"
        if not dxf_path.exists():
            self.skipTest("法兰盘二视图.dxf not available")

        parser = CADParser(str(dxf_path))
        parser.parse()
        parser._normalize_dimension_block_texts_for_preview()

        block_texts = []
        for dim in parser.doc.modelspace().query("DIMENSION"):
            block_texts.extend(item["text"] for item in parser._extract_dimension_block_texts(dim))

        self.assertIn("φ16", block_texts)
        self.assertIn("φ22", block_texts)
        self.assertIn("φ120", block_texts)
        self.assertNotIn(r"\U+220516", block_texts)

    def test_dimension_overlay_auto_threshold(self):
        """Auto overlay should only target tiny dimension text."""
        parser = CADParser("dummy.dxf")
        ax = Mock()
        ax.get_xlim.return_value = (0.0, 400.0)
        ax.get_ylim.return_value = (0.0, 200.0)

        self.assertTrue(parser._is_dimension_overlay_enabled("auto"))
        self.assertTrue(parser._is_auto_dimension_overlay("auto"))
        self.assertFalse(parser._is_dimension_overlay_enabled(False))
        self.assertEqual(3.2, parser._auto_dimension_overlay_max_height(ax))
        self.assertEqual(10.0, parser._dimension_overlay_fontsize(1.0, 3.2))
        self.assertEqual(12.0, parser._dimension_overlay_fontsize(2.0, None))

    def test_preview_normalizes_annotation_colors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dxf_path = Path(tmp_dir) / "annotation_color.dxf"
            doc = ezdxf.new()
            doc.layers.add("文本层", color=212)
            msp = doc.modelspace()
            msp.add_text("R=4x1.5", dxfattribs={"layer": "文本层", "color": 256})
            dim = msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(12, 0), dxfattribs={"layer": "文本层"})
            dim.render()
            doc.saveas(dxf_path)

            parser = CADParser(str(dxf_path), {"preview_annotation_color": 7})
            parser.parse()
            parser._normalize_annotation_colors_for_preview()

            self.assertEqual(7, parser.doc.layers.get("文本层").dxf.color)
            text = list(parser.doc.modelspace().query("TEXT"))[0]
            self.assertEqual(7, text.dxf.color)
            dimension_text_colors = []
            for dim in parser.doc.modelspace().query("DIMENSION"):
                block = parser.doc.blocks.get(dim.dxf.geometry)
                dimension_text_colors.extend(
                    sub.dxf.color
                    for sub in block
                    if sub.dxftype() in ("TEXT", "MTEXT")
                )
            self.assertTrue(dimension_text_colors)
            self.assertTrue(all(color == 7 for color in dimension_text_colors))


if __name__ == "__main__":
    unittest.main()
