# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from gui_example import read_project_env, write_project_env


class TestGuiSettingsEnv(unittest.TestCase):
    def test_write_project_env_preserves_comments_and_updates_known_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\nDEEPSEEK_API_KEY=old\nOTHER=value\n",
                encoding="utf-8",
            )

            write_project_env(
                {
                    "DEEPSEEK_API_KEY": "new-key",
                    "FREECAD_BIN_PATH": r"D:\FreeCAD 1.0\bin",
                },
                env_path,
            )

            text = env_path.read_text(encoding="utf-8")
            values = read_project_env(env_path)

        self.assertIn("# comment", text)
        self.assertIn("OTHER=value", text)
        self.assertEqual("new-key", values["DEEPSEEK_API_KEY"])
        self.assertEqual(r"D:\FreeCAD 1.0\bin", values["FREECAD_BIN_PATH"])

    def test_read_project_env_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n# API\nDEEPSEEK_API_KEY='quoted-key'\nFREECAD_BIN_PATH=\"D:/FreeCAD/bin\"\n",
                encoding="utf-8",
            )

            values = read_project_env(env_path)

        self.assertEqual("quoted-key", values["DEEPSEEK_API_KEY"])
        self.assertEqual("D:/FreeCAD/bin", values["FREECAD_BIN_PATH"])


if __name__ == "__main__":
    unittest.main()
