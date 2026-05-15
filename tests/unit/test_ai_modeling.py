# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.intelligent_analyzer.modeling_generator import FreeCADInstructionGenerator
from src.intelligent_analyzer.reconstruction_context import ReconstructionContextBuilder
from src.intelligent_analyzer.semantic_schema import PartSemanticsValidator
from src.intelligent_analyzer.pipeline import IntelligentEngineeringAnalyzer
from src.model_generator.freecad_bridge import FreeCADBridge
from src.model_generator.ai_script_runner import AIScriptRunner


class TestAIModeling(unittest.TestCase):
    def test_multiview_prompt_has_orthographic_guardrails(self):
        prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

        self.assertIn("不得把右视图或俯视图当成附加在主视图旁边的新实体", prompt)
        self.assertIn("右视图的水平尺寸应优先解释为零件深度", prompt)
        self.assertIn("不得默认把所有同心圆都切成贯通孔", prompt)
        self.assertIn("传入 Part.Wire 的每一项必须是 Shape", prompt)
        self.assertIn("若轮廓点写成 `(x, y, 0)`", prompt)

    def test_reconstruction_context_preserves_views_dimensions_and_relationships(self):
        context = ReconstructionContextBuilder().build(
            {
                "_local_relationships": {
                    "summary": "2 entities",
                    "entity_pairs": [{"id1": 1, "id2": 2, "relationship": "包含"}],
                }
            },
            {
                "drawing_type": "two_view",
                "reason_summary": "orthographic",
                "views": [
                    {
                        "name": "main",
                        "type": "主视图",
                        "bbox": [0, 0, 10, 10],
                        "centroid": [5, 5],
                        "entities": [
                            {"type": "CIRCLE", "layer": "轮廓线", "center": [5, 5], "radius": 2},
                        ],
                    }
                ],
            },
            {
                "dimensions": [
                    {"text": "10", "value": 10.0, "type": "线性", "position": [1, 2, 0]},
                ]
            },
        )

        self.assertEqual("two_view", context["view_analysis"]["drawing_type"])
        self.assertEqual("main", context["view_analysis"]["views"][0]["name"])
        self.assertEqual({"CIRCLE": 1}, context["view_analysis"]["views"][0]["entity_type_count"])
        self.assertEqual("10", context["dimensions"][0]["text"])
        self.assertEqual("包含", context["local_geometry"]["entity_pairs"][0]["relationship"])

    def test_prompt_uses_supplied_reconstruction_context(self):
        generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
        generator.MAX_PROMPT_CHARS = 10000
        prompt = generator._build_prompt(
            {"entities": []},
            None,
            None,
            10.0,
            reconstruction_context={"context_version": "custom_v1", "marker": "keep-me"},
        )

        self.assertIn('"context_version": "custom_v1"', prompt)
        self.assertIn('"marker": "keep-me"', prompt)

    def test_prompt_includes_part_semantics(self):
        generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
        generator.MAX_PROMPT_CHARS = 10000
        prompt = generator._build_prompt(
            {"entities": []},
            None,
            None,
            10.0,
            reconstruction_context={"context_version": "custom_v1"},
            part_semantics={"part_type": "bracket"},
        )

        self.assertIn("=== 零件语义 ===", prompt)
        self.assertIn('"part_type": "bracket"', prompt)

    def test_part_semantics_validator_requires_core_fields(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "plate",
                "confidence": 0.9,
                "summary": "",
                "evidence": [],
                "candidate_interpretations": [],
                "coordinate_system": {},
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertTrue(valid)
        self.assertEqual([], errors)

    def test_part_semantics_validator_rejects_invalid_confidence(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "plate",
                "confidence": 1.5,
                "summary": "",
                "evidence": [],
                "candidate_interpretations": [],
                "coordinate_system": {},
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertFalse(valid)
        self.assertIn("confidence must be between 0 and 1", errors)

    def test_low_semantic_confidence_blocks_modeling(self):
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.config = {"semantic_min_confidence": 0.7}
        self.assertFalse(analyzer._is_semantic_confidence_sufficient({"confidence": 0.4}))
        self.assertTrue(analyzer._is_semantic_confidence_sufficient({"confidence": 0.8}))

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

    def test_bridge_script_fails_without_valid_shape(self):
        bridge = FreeCADBridge.__new__(FreeCADBridge)
        bridge.freecad_python = r"D:\FreeCAD 1.0\bin\python.exe"
        script = bridge._build_subprocess_script("doc = App.newDocument('Empty')", "C:/tmp/out")

        self.assertIn('print("BRIDGE_ERROR:NO_VALID_SHAPE"', script)


if __name__ == "__main__":
    unittest.main()
