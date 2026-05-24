# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from src.batch_processor import CADProcessResult
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

    def test_pending_item_resume_restores_previous_result_metadata(self):
        result = CADProcessResult.from_pending_item({
            "input_file": "drawing.dxf",
            "mode": "intelligent",
            "modeling_path": "semantic_reconstruction",
            "clarification_questions": [{"id": "user_modeling_hint"}],
            "clarification_context": {"partial_modeling_recovery": True},
            "output_paths": {
                "analysis_full": "out/drawing_full.json",
                "model_step": "out/drawing.step",
            },
            "completed_features": [{"name": "base_body"}],
            "skipped_features": [{"name": "R15"}],
            "partial_completion_reason": "主体已生成，R15 跳过",
        })

        self.assertEqual("semantic_reconstruction", result.modeling_path)
        self.assertEqual("out/drawing_full.json", result.output_paths["analysis_full"])
        self.assertEqual("base_body", result.completed_features[0]["name"])
        self.assertEqual("R15", result.skipped_features[0]["name"])
        self.assertEqual("主体已生成，R15 跳过", result.partial_completion_reason)


if __name__ == "__main__":
    unittest.main()
