# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from src.reconstruction.semantics import PartSemanticGenerator
from src.utils.stage_self_correction import SelfCorrectionRequest, ValidationIssue


class TestPartSemanticGenerator(unittest.TestCase):
    def test_user_content_lifts_user_modeling_hint_policy(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "context_version": "adjudicated_context_v1",
            "semantic_policy": {
                "user_modeling_hint": "优先生成主体，内部槽可以跳过。",
                "user_modeling_hint_policy": "drawing_facts_override_user_hint",
                "dimension_plan": {"allowed_dimensions": []},
            },
        })

        self.assertIn("=== 用户补充建模提示使用规则 ===", content)
        self.assertIn("semantic_understanding_payload", content)
        self.assertIn("优先生成主体，内部槽可以跳过。", content)
        self.assertIn("drawing_facts_override_user_hint", content)
        self.assertIn("必须以图纸事实和已裁决语义为准", content)
        self.assertNotIn('"context_version": "adjudicated_context_v1"', content)

    def test_user_content_omits_hint_section_when_no_hint_exists(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "context_version": "adjudicated_context_v1",
            "semantic_policy": {"dimension_plan": {"allowed_dimensions": []}},
        })

        self.assertNotIn("=== 用户补充建模提示使用规则 ===", content)

    def test_user_content_includes_stage_retry_focus_directives(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "context_version": "adjudicated_context_v1",
            "semantic_policy": {"dimension_plan": {"allowed_dimensions": []}},
            "retained_items": {
                "base_features": [{"description": "方形法兰板"}],
            },
            "stage_retry_directives": {
                "stage": "semantic_reconstruction",
                "objective": "优先解决未决风险",
                "focus_issues": ["D1标注8的含义不明确"],
            },
        })

        self.assertIn("=== 阶段重跑要求 ===", content)
        self.assertIn("focus_issues", content)
        self.assertIn("D1标注8的含义不明确", content)
        self.assertIn("不要仅复述上一轮结果", content)
        self.assertIn("方形法兰板", content)

    def test_user_content_uses_semantic_payload_not_raw_entities(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "drawing": {"entity_count": 1, "entity_type_count": {"LINE": 1}},
            "source_entities": [
                {"type": "LINE", "start": [0, 0], "end": [10, 0], "layer": "0"}
            ],
            "view_analysis": {"views": [{"name": "main", "entities": [{"type": "LINE"}]}]},
            "semantic_policy": {"dimension_plan": {"allowed_dimensions": []}},
        })

        self.assertIn("=== semantic_understanding_payload", content)
        self.assertIn('"line_summary"', content)
        self.assertNotIn('"source_entities"', content)
        self.assertNotIn('"entities"', content)
        self.assertNotIn('"start": [', content)
        self.assertNotIn('"end": [', content)

    def test_semantic_generation_request_uses_deepseek_json_output(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)
        generator.config = {"user_id": "cad-test"}
        generator.model = "deepseek-v4-pro"
        generator.validator = SimpleNamespace(validate=lambda result, context: (True, []))
        generator.telemetry_store = SimpleNamespace(
            start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
        )
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"part_type":"block"}')
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice])

        generator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        )
        generator._extract_json = lambda content: {
            "part_type": "block",
            "confidence": 0.9,
            "summary": "",
            "evidence": [],
            "candidate_interpretations": [],
            "coordinate_system": {},
            "dimension_source": "annotation",
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "planar_modeling_semantics": {
                "profile": None,
                "extrusion_direction": "unknown",
                "extrusion_depth": None,
                "cut_features": [],
                "dimension_bindings": [],
                "uncertainties": [],
            },
            "revolve_modeling_semantics": None,
            "preferred_modeling_path": None,
            "key_dimensions": [],
            "uncertainties": [],
            "warnings": [],
        }

        generator._generate_once(
            {"semantic_policy": {"dimension_plan": {"allowed_dimensions": []}}},
            thinking=False,
        )

        self.assertEqual({"type": "json_object"}, calls[0]["response_format"])
        self.assertEqual(
            {"thinking": {"type": "disabled"}},
            calls[0]["extra_body"],
        )
        self.assertNotIn("user_id", calls[0])

    def test_semantic_generation_postprocesses_before_validation(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)
        generator.config = {}
        generator.model = "deepseek-v4-pro"
        generator.telemetry_store = SimpleNamespace(
            start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
        )
        seen_results = []

        def validate(result, context):
            seen_results.append(result)
            return True, []

        generator.validator = SimpleNamespace(validate=validate)
        generator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")]
            )))
        )
        generator._extract_json = lambda content: {
            "part_type": "plate",
            "confidence": 0.9,
            "summary": "",
            "evidence": [],
            "candidate_interpretations": [],
            "coordinate_system": {},
            "dimension_source": "annotation",
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "planar_modeling_semantics": {
                "profile": None,
                "extrusion_direction": "unknown",
                "extrusion_depth": None,
                "cut_features": [],
                "dimension_bindings": [],
                "uncertainties": [],
            },
            "revolve_modeling_semantics": None,
            "preferred_modeling_path": None,
            "key_dimensions": [
                {"name": "extrusion_depth", "value": 16.0},
                {"name": "guessed_height", "value": 99.0},
            ],
            "uncertainties": ["Missing boss height dimension."],
            "warnings": ["Extrusion depth missing; a default may be assumed."],
        }

        result = generator._generate_once(
            {
                "dimensions": [
                    {"text": "16", "value": 16.0},
                    {"text": "99", "value": 99.0},
                ],
                "semantic_policy": {
                    "dimension_source": "annotation",
                    "drawing_evidence_package": {
                        "dimension_candidates": [
                            {"id": "D1", "text": "16", "value": 16.0}
                        ],
                        "derived_dimension_candidates": [],
                    },
                    "semantic_adjudication": {
                        "status": "completed",
                        "dimension_roles": [
                            {"dimension_id": "D1", "role": "extrusion_depth"}
                        ],
                        "derived_dimensions": [],
                    },
                },
            },
            thinking=False,
        )

        self.assertEqual(
            [{"name": "extrusion_depth", "value": 16.0}],
            seen_results[0]["key_dimensions"],
        )
        self.assertIn("非中文风险说明", seen_results[0]["warnings"][0])
        self.assertEqual(result, seen_results[0])

    def test_semantic_self_correction_request_uses_deepseek_json_output(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)
        generator.config = {}
        generator.model = "deepseek-v4-pro"
        generator.validator = SimpleNamespace(validate=lambda result, context: (True, []))
        generator.telemetry_store = SimpleNamespace(
            start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
        )
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"part_type":"flange"}')
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice])

        generator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        )
        generator._extract_json = lambda content: {
            "part_type": "flange",
            "confidence": 0.9,
            "summary": "",
            "evidence": [],
            "candidate_interpretations": [],
            "coordinate_system": {},
            "dimension_source": "annotation",
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "planar_modeling_semantics": {
                "profile": None,
                "extrusion_direction": "unknown",
                "extrusion_depth": None,
                "cut_features": [],
                "dimension_bindings": [],
                "uncertainties": [],
            },
            "revolve_modeling_semantics": None,
            "preferred_modeling_path": None,
            "key_dimensions": [],
            "uncertainties": [],
            "warnings": [],
        }

        request = SelfCorrectionRequest(
            stage="semantic_reconstruction",
            round_index=1,
            max_rounds=2,
            stage_payload={"semantic_policy": {"dimension_plan": {"allowed_dimensions": []}}},
            previous_output={"part_type": "plate"},
            validation_issues=[
                ValidationIssue(
                    code="user_requested_semantic_reconstruction_self_correction",
                    message="用户要求复核",
                )
            ],
            output_contract={"required_fields": ["part_type"]},
        )

        result = generator.generate_from_self_correction(request)

        self.assertEqual("flange", result["part_type"])
        self.assertEqual({"type": "json_object"}, calls[0]["response_format"])
        self.assertIn("self_correction_request", calls[0]["messages"][1]["content"])
        self.assertIn("用户要求复核", calls[0]["messages"][1]["content"])

    def test_semantic_prompts_require_chinese_user_facing_fields(self):
        self.assertIn("所有面向用户阅读的自然语言字段必须使用中文", PartSemanticGenerator.SYSTEM_PROMPT)
        self.assertIn("不要输出英文句子", PartSemanticGenerator.SYSTEM_PROMPT)
        self.assertIn("不要输出英文风险句", PartSemanticGenerator.RETRY_SYSTEM_PROMPT)
        self.assertIn("不得直接升级为圆柱凸台 boss", PartSemanticGenerator.SYSTEM_PROMPT)
        self.assertIn("应优先解释为孔/通孔", PartSemanticGenerator.RETRY_SYSTEM_PROMPT)
        self.assertIn("不得覆盖 semantic_adjudication", PartSemanticGenerator.SYSTEM_PROMPT)
        self.assertIn("旧 dimension_bindings 只能作为兼容提示", PartSemanticGenerator.RETRY_SYSTEM_PROMPT)

    def test_normalizes_incomplete_revolve_semantics_to_semantic_reconstruction(self):
        result = PartSemanticGenerator._normalize_part_semantics({
            "preferred_modeling_path": "revolve_base_then_add_hex_head",
            "revolve_modeling_semantics": {
                "profile": "由直线和圆弧组成的半轮廓",
                "axis": "中心线",
                "angle": 360.0,
            },
            "uncertainties": [],
        })

        self.assertIsNone(result["revolve_modeling_semantics"])
        self.assertEqual("semantic_reconstruction", result["preferred_modeling_path"])
        self.assertIn("回转语义缺少精确轴线", result["uncertainties"][0])


if __name__ == "__main__":
    unittest.main()
