# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

import src
from src.reconstruction.instruction_generator import FreeCADInstructionGenerator
from src.intelligent_analyzer.pipeline import IntelligentEngineeringAnalyzer
from src.model_generator import FreeCADModeler, PlanarExtrudeModeler
from src.utils.stage_confirmation import (
    CallbackStageConfirmation,
    StageConfirmationResult,
    StageReview,
    resolve_stage_confirmation,
)
from src.reconstruction.modeling_constraints import ModelingConstraints


class TestModelingGenerator(unittest.TestCase):
    def test_package_root_uses_lazy_compat_exports(self):
        self.assertEqual("1.0.0", src.__version__)

        self.assertTrue(src.__all__)
        self.assertIs(src.PlanarExtrudeModeler, PlanarExtrudeModeler)

        with self.assertRaises(AttributeError):
            getattr(src, "MissingExport")

    def test_planar_extrude_modeler_is_primary_internal_name(self):
        self.assertIs(FreeCADModeler, PlanarExtrudeModeler)

    def test_multiview_prompt_has_orthographic_guardrails(self):
        prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

        self.assertIn("不得把右视图或俯视图当成附加在主视图旁边的新实体", prompt)
        self.assertIn("右视图/左视图表达同一零件的正交投影外形", prompt)
        self.assertIn("不得默认把所有同心圆都切成贯通孔", prompt)
        self.assertIn("倒角标注表示外部尖角被削掉形成斜面", prompt)
        self.assertIn("不得因为“FreeCAD 基本 API 限制”直接跳过", prompt)
        self.assertIn("Part.makeCone", prompt)
        self.assertIn("Shape.revolve", prompt)
        self.assertIn("import math", prompt)
        self.assertIn("Vector.x / Vector.y / Vector.z", prompt)
        self.assertIn("禁止使用 while", prompt)
        self.assertIn("Shape.makeFillet", prompt)
        self.assertIn("common / section / split / thickness", prompt)
        self.assertIn("ArcOfCircle 固定模板", prompt)
        self.assertIn("不得写成 `Part.ArcOfCircle(center, radius, start_angle, end_angle)`", prompt)
        self.assertIn("R=4x1.5", prompt)
        self.assertIn("repeat_count+radius_value", prompt)
        self.assertIn("3xφ5", prompt)
        self.assertIn("diameter_value/thread_value", prompt)
        self.assertIn("六角头螺栓主视图左侧头部的 R15 标注", prompt)
        self.assertIn("不得把它建成向实体内部凹陷的槽", prompt)
        self.assertIn("传入 Part.Wire 的每一项必须是 Shape", prompt)
        self.assertIn("若轮廓点写成 `(x, y, 0)`", prompt)
        self.assertIn("主体厚度、拉伸深度", prompt)
        self.assertIn("不得编造默认值", prompt)
        self.assertNotIn("应使用合理默认值", prompt)

    def test_prompt_uses_modeling_task_payload_only(self):
        generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
        prompt = generator._build_prompt(
            {
                "object": {"part_type": "bracket"},
                "features": {"base": [{"name": "body"}]},
                "dimensions": {"allowed_dimensions": [{"text": "30", "value": 30.0}]},
                "constraints": {"partial_modeling_policy": {}},
                "recovery_hints": {"user_modeling_hint": "优先生成主体。"},
            }
        )

        self.assertIn('"part_type": "bracket"', prompt)
        self.assertIn('"user_modeling_hint": "优先生成主体。"', prompt)
        self.assertNotIn("=== 几何实体数据 ===", prompt)
        self.assertNotIn("=== 零件语义 ===", prompt)
        self.assertNotIn("context_version", prompt)
        self.assertNotIn("内容已截断", prompt)

    def test_generate_builds_modeling_task_payload_from_context(self):
        generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
        generator.config = {}
        generator.model = "deepseek-v4-pro"
        generator.constraints = ModelingConstraints()
        calls = []

        def fake_completion(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content="{}", reasoning_content=None)
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice])

        generator._create_chat_completion = fake_completion
        generator._extract_json = lambda content: {"freecad_script": "pass"}

        result = generator.generate(
            {"entities": []},
            reconstruction_context={
                "context_version": "adjudicated_context_v1",
                "semantic_policy": {
                    "user_modeling_hint": "优先生成主体，槽可以跳过。",
                    "user_modeling_hint_policy": "drawing_facts_override_user_hint",
                    "dimension_plan": {"allowed_dimensions": []},
                },
            },
            part_semantics={"part_type": "bracket", "confidence": 0.9},
        )

        self.assertEqual({"freecad_script": "pass"}, result)
        prompt = calls[0]["messages"][1]["content"]
        self.assertIn('"part_type": "bracket"', prompt)
        self.assertIn('"user_modeling_hint": "优先生成主体，槽可以跳过。"', prompt)
        self.assertNotIn('"entities"', prompt)
        self.assertNotIn('"context_version": "adjudicated_context_v1"', prompt)

    def test_modeling_generation_retries_when_required_chamfer_is_skipped(self):
        constraints = ModelingConstraints()
        result = {
            "analysis_summary": "六角头螺栓，包含1x45°倒角",
            "modeling_strategy": "忽略倒角细节",
            "freecad_script": "runtime_warnings.append('倒角1x45°未实现')",
            "warnings": ["倒角未实现"],
        }
        reconstruction_context = {
            "semantic_policy": {
                "dimension_plan": {
                    "allowed_dimensions": [
                        {"text": "1x45%%d", "value": 1.0, "role": "chamfer"}
                    ]
                }
            }
        }

        self.assertEqual(
            "chamfer",
            constraints.retry_reason(
                result,
                reconstruction_context,
                {"part_type": "bolt"},
            )
        )
        self.assertEqual(
            "",
            constraints.retry_reason(
                {"analysis_summary": "已实现倒角斜面", "warnings": []},
                reconstruction_context,
                {"part_type": "bolt"},
            )
        )

    def test_modeling_generation_retries_when_required_radius_surface_is_skipped(self):
        constraints = ModelingConstraints()
        result = {
            "analysis_summary": "六角头螺栓，包含R15圆弧面",
            "modeling_strategy": "忽略圆角细节",
            "freecad_script": "runtime_warnings.append('R15圆角未实现')",
            "warnings": ["R15未实现"],
        }
        reconstruction_context = {
            "semantic_policy": {
                "dimension_plan": {
                    "allowed_dimensions": [
                        {"text": "R15", "value": 15.0, "role": "radius"}
                    ]
                }
            }
        }

        self.assertEqual(
            "radius_surface",
            constraints.retry_reason(
                result,
                reconstruction_context,
                {"part_type": "六角头螺栓", "summary": "R15圆弧面/承面"},
            )
        )
        retry_prompt = constraints.retry_prompt("原始提示", "radius_surface")
        self.assertIn("Shape.revolve()", retry_prompt)
        self.assertIn("球面/承面", retry_prompt)

    def test_modeling_generation_does_not_retry_when_required_feature_is_skipped(self):
        generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
        generator.config = {}
        generator.model = "deepseek-v4-pro"
        generator.constraints = ModelingConstraints()
        generator.MAX_PROMPT_CHARS = 10000
        calls = []
        first_result = {
            "analysis_summary": "六角头螺栓，包含R15圆弧面",
            "modeling_strategy": "忽略圆角细节",
            "freecad_script": "runtime_warnings.append('R15圆角未实现')",
            "warnings": ["R15未实现"],
        }

        def fake_completion(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content="{}", reasoning_content=None)
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice])

        generator._create_chat_completion = fake_completion
        generator._extract_json = lambda content: first_result

        result = generator.generate(
            {"entities": []},
            reconstruction_context={
                "semantic_policy": {
                    "dimension_plan": {
                        "allowed_dimensions": [
                            {"text": "R15", "value": 15.0, "role": "radius"}
                        ]
                    }
                }
            },
            part_semantics={"part_type": "六角头螺栓", "summary": "R15圆弧面/承面"},
        )

        self.assertEqual(first_result, result)
        self.assertEqual(1, len(calls))
        self.assertEqual({"type": "json_object"}, calls[0]["response_format"])
        self.assertEqual(
            {"thinking": {"type": "disabled"}},
            calls[0]["extra_body"],
        )

    def test_low_semantic_confidence_blocks_modeling(self):
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.config = {"semantic_min_confidence": 0.7}
        self.assertFalse(analyzer._is_semantic_confidence_sufficient({"confidence": 0.4}))
        self.assertTrue(analyzer._is_semantic_confidence_sufficient({"confidence": 0.8}))

    def test_transient_semantic_provider_failure_is_not_cacheable(self):
        result = {
            "part_semantics": {
                "confidence": 0.0,
                "warnings": ["Connection error."],
            },
            "modeling_instructions": {
                "blocked_by_semantic_confidence": True,
                "warnings": [
                    "Part semantics confidence is insufficient; automatic modeling stopped."
                ],
            },
        }

        self.assertFalse(
            IntelligentEngineeringAnalyzer._is_cacheable_analysis_result(result)
        )

    def test_non_transient_blocked_result_remains_cacheable(self):
        result = {
            "part_semantics": {
                "confidence": 0.0,
                "warnings": ["semantic adjudication needs user clarification"],
            },
            "modeling_instructions": {
                "blocked_by_semantic_confidence": True,
                "warnings": [
                    "Part semantics confidence is insufficient; automatic modeling stopped."
                ],
            },
        }

        self.assertTrue(
            IntelligentEngineeringAnalyzer._is_cacheable_analysis_result(result)
        )

    def test_stage_confirmation_default_adapter_continues(self):
        confirmation = resolve_stage_confirmation({})

        self.assertTrue(confirmation.should_continue(StageReview("view_analysis", {})))

    def test_cached_analysis_replays_stage_confirmation_adapter(self):
        calls = []
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.config = {}
        analyzer.stage_confirmation = CallbackStageConfirmation(
            lambda stage, payload: calls.append(stage) or True
        )

        analyzer._confirm_cached_stages({
            "view_analysis": {},
            "dimension_extraction": {},
            "semantic_policy": {},
            "part_semantics": {"confidence": 0.9},
            "modeling_instructions": {
                "freecad_script": "final_shape = Part.makeBox(1, 1, 1)",
            },
        })

        self.assertEqual(
            ["view_analysis", "semantic_reconstruction", "modeling_generation"],
            calls,
        )

    def test_cached_semantic_retry_with_partial_executes_rerun(self):
        calls = []
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.config = {}
        analyzer.reconstruction_pipeline = unittest.mock.Mock()
        analyzer.reconstruction_pipeline.rerun_semantic_reconstruction_from_cached_analysis.return_value = {
            "part_semantics": {"part_type": "retried"},
            "modeling_instructions": {"freecad_script": "retried_script"},
        }

        def confirm(stage, payload):
            calls.append(stage)
            if stage == "semantic_reconstruction":
                return StageConfirmationResult.retry_with_partial(
                    {"part_type": True},
                    stage=stage,
                )
            return True

        analyzer.stage_confirmation = CallbackStageConfirmation(confirm)

        result = analyzer._confirm_cached_stages(
            {
                "view_analysis": {},
                "dimension_extraction": {},
                "semantic_policy": {},
                "part_semantics": {"confidence": 0.9},
                "modeling_instructions": {"freecad_script": "cached_script"},
            },
            geometry_data={"entities": []},
            extrude_height=10.0,
            file_path="drawing.dxf",
        )

        self.assertEqual(["view_analysis", "semantic_reconstruction"], calls)
        self.assertEqual("retried_script", result["modeling_instructions"]["freecad_script"])
        analyzer.reconstruction_pipeline.rerun_semantic_reconstruction_from_cached_analysis.assert_called_once()
        call_kwargs = analyzer.reconstruction_pipeline.rerun_semantic_reconstruction_from_cached_analysis.call_args.kwargs
        self.assertEqual({"part_type": True}, call_kwargs["retained_items"])
        self.assertEqual("drawing.dxf", call_kwargs["file_path"])



if __name__ == "__main__":
    unittest.main()
