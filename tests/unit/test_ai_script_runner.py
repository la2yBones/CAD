# -*- coding: utf-8 -*-

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from src.model_generator.ai_script_runner import AIScriptRunner
from src.model_generator.freecad_bridge import FreeCADBridge
from src.reconstruction.modeling_constraints import ModelingConstraints


class TestAIScriptRunner(unittest.TestCase):
    def test_bridge_outputs_are_normalized_to_requested_paths(self):
        runner = AIScriptRunner.__new__(AIScriptRunner)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bridge_step = temp_path / "model.step"
            bridge_fcstd = temp_path / "model.FCStd"
            requested_step = temp_path / "named" / "drawing.step"
            bridge_step.write_text("step", encoding="utf-8")
            bridge_fcstd.write_text("fcstd", encoding="utf-8")

            result = runner._normalize_bridge_outputs(
                {
                    "success": True,
                    "step_path": str(bridge_step),
                    "fcstd_path": str(bridge_fcstd),
                },
                requested_step,
            )

            self.assertEqual(str(requested_step), result["step_path"])
            self.assertEqual(str(requested_step.with_suffix(".FCStd")), result["fcstd_path"])
            self.assertTrue(requested_step.exists())
            self.assertTrue(requested_step.with_suffix(".FCStd").exists())

    def test_bridge_output_preserves_partial_metadata(self):
        runner = AIScriptRunner.__new__(AIScriptRunner)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bridge_step = temp_path / "model.step"
            requested_step = temp_path / "named" / "drawing.step"
            bridge_step.write_text("step", encoding="utf-8")

            result = runner._normalize_bridge_outputs(
                {
                    "success": True,
                    "step_path": str(bridge_step),
                    "skipped_features": [{"name": "slot", "reason": "missing width"}],
                    "partial_completion_reason": "主体已导出，槽跳过",
                },
                requested_step,
            )

            self.assertTrue(result["success"])
            self.assertEqual("slot", result["skipped_features"][0]["name"])
            self.assertEqual("主体已导出，槽跳过", result["partial_completion_reason"])

    def test_ai_script_runner_rejects_script_that_violates_modeling_constraints(self):
        class Bridge:
            freecad_available = True
            mode = "subprocess"

        runner = AIScriptRunner.__new__(AIScriptRunner)
        runner.bridge = Bridge()
        runner.constraints = ModelingConstraints()

        result = runner.run_script("import os\n", None)

        self.assertFalse(result["success"])
        self.assertIn("建模约束校验", result["error"])
        self.assertTrue(result["validation_errors"])

    def test_bridge_copy_failure_is_reported(self):
        runner = AIScriptRunner.__new__(AIScriptRunner)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bridge_step = temp_path / "model.step"
            bridge_fcstd = temp_path / "model.FCStd"
            requested_step = temp_path / "named" / "drawing.step"
            bridge_step.write_text("step", encoding="utf-8")
            bridge_fcstd.write_text("fcstd", encoding="utf-8")

            with patch("src.model_generator.ai_script_runner.shutil.copy2", side_effect=OSError("denied")):
                result = runner._normalize_bridge_outputs(
                    {
                        "success": True,
                        "step_path": str(bridge_step),
                        "fcstd_path": str(bridge_fcstd),
                    },
                    requested_step,
                )

            self.assertFalse(result["success"])
            self.assertIn("copy STEP failed", result["error"])

    def test_generated_script_normalizes_wire_geometry(self):
        runner = AIScriptRunner.__new__(AIScriptRunner)
        script = "\n".join(
            [
                "line_bottom = Part.LineSegment(p1, p2)",
                "arc_br = Part.ArcOfCircle(c, p1, p2)",
                "already = Part.LineSegment(p1, p2).toShape()",
            ]
        )

        normalized = runner._normalize_generated_script(script)

        self.assertIn("line_bottom = Part.LineSegment(p1, p2).toShape()", normalized)
        self.assertIn("arc_br = Part.ArcOfCircle(c, p1, p2).toShape()", normalized)
        self.assertIn("already = Part.LineSegment(p1, p2).toShape()", normalized)

    def test_partial_metadata_from_script_variables_is_normalized(self):
        metadata = AIScriptRunner._extract_partial_metadata_from_vars({
            "completed_features": ["base body"],
            "skipped_features": [{"name": "fillet", "reason": "topology failed"}],
            "partial_completion_reason": "主体已导出，圆角跳过",
        })

        self.assertEqual("base body", metadata["completed_features"][0]["name"])
        self.assertEqual("fillet", metadata["skipped_features"][0]["name"])
        self.assertEqual("主体已导出，圆角跳过", metadata["partial_completion_reason"])

    def test_bridge_script_fails_without_valid_shape(self):
        bridge = FreeCADBridge.__new__(FreeCADBridge)
        bridge.freecad_python = r"D:\FreeCAD 1.0\bin\python.exe"
        script = bridge._build_subprocess_script("doc = App.newDocument('Empty')", "C:/tmp/out")

        self.assertIn('print("BRIDGE_ERROR:NO_VALID_SHAPE"', script)

    def test_bridge_script_recomputes_before_selecting_shape(self):
        bridge = FreeCADBridge.__new__(FreeCADBridge)
        bridge.freecad_python = r"D:\FreeCAD 1.0\bin\python.exe"
        script = bridge._build_subprocess_script("Part.show(final_shape, 'GeneratedModel')", "C:/tmp/out")

        self.assertIn("doc.recompute()", script)
        self.assertIn('getattr(value, "Shape", None)', script)

    def test_bridge_parses_partial_modeling_marker(self):
        bridge = FreeCADBridge.__new__(FreeCADBridge)
        payload = {
            "completed_features": [{"name": "base body", "kind": "base"}],
            "skipped_features": [{"name": "R2 fillet", "kind": "fillet"}],
            "partial_completion_reason": "主体已导出，圆角跳过",
        }

        result = bridge._parse_marker_output(
            "\n".join([
                "BRIDGE_EXPORT:STEP:C:/tmp/model.step",
                f"PARTIAL_MODELING_RESULT:{json.dumps(payload, ensure_ascii=False)}",
                "BRIDGE_SUCCESS",
            ]),
            "C:/tmp",
        )

        self.assertTrue(result["success"])
        self.assertEqual("C:/tmp/model.step", result["step_path"])
        self.assertEqual("R2 fillet", result["skipped_features"][0]["name"])
        self.assertEqual("主体已导出，圆角跳过", result["partial_completion_reason"])

    def test_ai_script_runner_includes_runtime_warning_in_error(self):
        runner = AIScriptRunner.__new__(AIScriptRunner)
        result = runner._format_bridge_error(
            {
                "error": "NO_VALID_SHAPE",
                "stdout": "BRIDGE_START\nRuntime warnings: ['建模失败: bad arc']\n",
            }
        )

        self.assertIn("NO_VALID_SHAPE", result)
        self.assertIn("Runtime warnings", result)


if __name__ == "__main__":
    unittest.main()
