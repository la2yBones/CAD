# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from src.model_generator.freecad_bridge import FreeCADBridge


class TestFreeCADBridgeDiscovery(unittest.TestCase):
    def test_project_freecad_bundle_candidates_are_preferred_by_version_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "tools" / "freecad" / "FreeCAD-1.0.1" / "bin" / "python.exe"
            newer = root / "tools" / "freecad" / "FreeCAD-1.0.2" / "bin" / "python.exe"
            older.parent.mkdir(parents=True)
            newer.parent.mkdir(parents=True)
            older.write_text("", encoding="utf-8")
            newer.write_text("", encoding="utf-8")

            candidates = FreeCADBridge._find_project_freecad_candidates(root)

        self.assertEqual(str(newer), candidates[0])
        self.assertEqual(str(older), candidates[1])

    def test_project_freecad_bundle_ignores_non_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme = root / "tools" / "freecad" / "README.md"
            readme.parent.mkdir(parents=True)
            readme.write_text("docs only", encoding="utf-8")

            candidates = FreeCADBridge._find_project_freecad_candidates(root)

        self.assertEqual([], candidates)


if __name__ == "__main__":
    unittest.main()
