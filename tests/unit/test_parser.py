# -*- coding: utf-8 -*-
"""
CAD解析器单元测试
"""

import unittest
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

import ezdxf

from src.cad_parser import CADParser, DXFParser
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

    def test_backward_compatibility(self):
        """测试向后兼容性（DXFParser别名）"""
        if self.sample_dxf.exists():
            parser = DXFParser(str(self.sample_dxf))
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


if __name__ == "__main__":
    unittest.main()
