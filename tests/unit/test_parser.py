"""
CAD解析器单元测试
"""
import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

from src.cad_parser import CADParser
from src.utils import load_config


class TestCADParser(unittest.TestCase):

    def setUp(self):
        self.test_dir = project_root / "examples" / "cad_files"
        self.test_dir.mkdir(exist_ok=True)
        self.sample_dxf = self.test_dir / "sample.dxf"
        self.config = load_config()

    def test_parser_initialization(self):
        parser = CADParser(self.config)
        self.assertIsNotNone(parser)

    def test_parse_dxf(self):
        if self.sample_dxf.exists():
            parser = CADParser(self.config)
            result = parser.parse(str(self.sample_dxf))
            self.assertTrue(result.is_ok)
            self.assertIn("entities", result.value)

    def test_file_not_found(self):
        parser = CADParser(self.config)
        result = parser.parse("nonexistent.dxf")
        self.assertTrue(result.is_err)
        self.assertIn("文件", result.error)


if __name__ == "__main__":
    unittest.main()
