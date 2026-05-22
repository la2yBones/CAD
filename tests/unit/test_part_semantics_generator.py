# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from src.reconstruction.semantics import PartSemanticGenerator


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
        generator.config = {}
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


if __name__ == "__main__":
    unittest.main()
