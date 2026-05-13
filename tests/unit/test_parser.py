"""
CAD解析器单元测试
"""

import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

from src.cad_parser import CADParser, DXFParser


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


if __name__ == "__main__":
    unittest.main()
