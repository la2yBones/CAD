# -*- coding: utf-8 -*-

import json
import unittest
import unittest.mock
from types import SimpleNamespace

from src.reconstruction.semantic_adjudicator import (
    LLMSemanticAdjudicator,
    SemanticAdjudicationValidator,
)
from src.reconstruction.semantic_adjudication_view import SemanticAdjudicationView
from src.reconstruction.pipeline import SemanticReconstructionPipeline
from src.reconstruction.semantic_policy import SemanticPolicy
from src.intelligent_analyzer.reconstruction_context import ReconstructionContextBuilder
from src.utils.stage_confirmation import resolve_stage_confirmation


def _evidence_package():
    return {
        "package_version": "drawing_evidence_package_v1",
        "view_candidates": [{"id": "V1", "local_name_hint": "main"}],
        "dimension_candidates": [{"id": "D1", "text": "16", "value": 16.0}],
        "derived_dimension_candidates": [{"id": "DD1", "value": 4.0}],
        "geometry_candidates": [{"id": "G1", "candidate_kind": "circle"}],
        "spatial_relations": [{"id": "R1", "relation_type": "dimension_near_view"}],
    }


def _valid_adjudication():
    return {
        "confidence": 0.9,
        "view_roles": [
            {
                "view_id": "V1",
                "role": "main",
                "confidence": 0.9,
                "evidence_ids": ["V1", "R1"],
                "reason": "候选视图与标注关系一致",
                "overrode_local_hint": False,
            }
        ],
        "dimension_roles": [
            {
                "dimension_id": "D1",
                "role": "extrusion_depth",
                "confidence": 0.8,
                "evidence_ids": ["D1", "V1"],
                "reason": "该尺寸位于主视图厚度方向",
            }
        ],
        "feature_roles": [
            {
                "feature_id": "G1",
                "role": "through_hole",
                "confidence": 0.8,
                "evidence_ids": ["G1", "D1"],
                "reason": "圆形几何与直径标注相关",
            }
        ],
        "derived_dimensions": [
            {
                "source_derived_dimension_id": "DD1",
                "role": "feature_height",
                "value": 4.0,
                "confidence": 0.8,
                "evidence_ids": ["DD1"],
                "reason": "来自候选派生尺寸",
            }
        ],
        "clarification_questions": [],
        "uncertainties": [],
        "warnings": [],
    }


class TestLLMSemanticAdjudicator(unittest.TestCase):
    def test_semantic_adjudication_view_exports_modeling_dimensions(self):
        view = SemanticAdjudicationView(_valid_adjudication())

        self.assertTrue(view.is_successful)
        self.assertEqual(0.9, view.confidence)
        self.assertEqual("D1", view.confirmed_dimensions[0]["dimension_id"])
        self.assertEqual("G1", view.confirmed_features[0]["feature_id"])
        self.assertEqual("DD1", view.derived_dimensions[0]["source_derived_dimension_id"])
        self.assertEqual(2, len(view.modeling_dimensions))
        self.assertEqual(
            "semantic_adjudication.dimension_roles",
            view.modeling_dimensions[0]["source"],
        )
        self.assertTrue(view.has_role("through_hole"))

    def test_semantic_adjudication_view_blocks_failed_modeling_dimensions(self):
        view = SemanticAdjudicationView({
            **_valid_adjudication(),
            "status": "failed",
            "warnings": ["裁决失败"],
        })

        self.assertFalse(view.is_successful)
        self.assertEqual([], view.modeling_dimensions)
        self.assertEqual("failed", view.to_dict()["status"])

    def test_semantic_adjudication_view_excludes_unresolved_dimensions(self):
        adjudication = _valid_adjudication()
        adjudication["dimension_roles"] = [
            {
                "dimension_id": "D1",
                "role": "unresolved",
                "confidence": 0.2,
                "evidence_ids": ["D1"],
                "reason": "该尺寸尚未裁决",
            }
        ]
        adjudication["derived_dimensions"] = [
            {
                "source_derived_dimension_id": "DD1",
                "role": "unresolved",
                "value": 4.0,
                "confidence": 0.2,
                "evidence_ids": ["DD1"],
                "reason": "派生尺寸尚未裁决",
            }
        ]

        view = SemanticAdjudicationView(adjudication)

        self.assertTrue(view.is_successful)
        self.assertEqual([], view.modeling_dimensions)

    def test_adjudicator_uses_json_output_and_evidence_package_only(self):
        adjudicator = LLMSemanticAdjudicator.__new__(LLMSemanticAdjudicator)
        adjudicator.config = {}
        adjudicator.model = "deepseek-v4-pro"
        adjudicator.validator = SemanticAdjudicationValidator()
        adjudicator.telemetry_store = SimpleNamespace(
            start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
        )
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content=json.dumps(_valid_adjudication(), ensure_ascii=False))
            choice = SimpleNamespace(message=message)
            return SimpleNamespace(choices=[choice])

        adjudicator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        )

        result = adjudicator.adjudicate({
            "semantic_policy": {"drawing_evidence_package": _evidence_package()},
            "source_entities": [{"type": "LINE", "start": [0, 0]}],
        })

        self.assertEqual("completed", result["status"])
        self.assertEqual(0.9, result["confidence"])
        self.assertEqual({"type": "json_object"}, calls[0]["response_format"])
        self.assertEqual(
            {"thinking": {"type": "disabled"}},
            calls[0]["extra_body"],
        )
        user_content = calls[0]["messages"][1]["content"]
        self.assertIn("drawing_evidence_package", user_content)
        self.assertIn('"V1"', user_content)
        self.assertNotIn("source_entities", user_content)

    def test_validator_rejects_unknown_evidence_ids(self):
        valid, errors = SemanticAdjudicationValidator().validate(
            {
                **_valid_adjudication(),
                "dimension_roles": [
                    {
                        "dimension_id": "D404",
                        "role": "extrusion_depth",
                        "confidence": 0.8,
                        "evidence_ids": ["D404"],
                        "reason": "不存在的证据",
                    }
                ],
            },
            _evidence_package(),
        )

        self.assertFalse(valid)
        self.assertTrue(any("不存在的证据 ID" in error for error in errors))

    def test_validator_rejects_unknown_primary_role_ids(self):
        valid, errors = SemanticAdjudicationValidator().validate(
            {
                **_valid_adjudication(),
                "dimension_roles": [
                    {
                        "dimension_id": "D404",
                        "role": "extrusion_depth",
                        "confidence": 0.8,
                        "evidence_ids": ["D1"],
                        "reason": "主 ID 不存在，但 evidence_id 存在",
                    }
                ],
            },
            _evidence_package(),
        )

        self.assertFalse(valid)
        self.assertTrue(any("dimension_roles.dimension_id" in error for error in errors))

    def test_validator_rejects_unknown_derived_dimension_ids(self):
        valid, errors = SemanticAdjudicationValidator().validate(
            {
                **_valid_adjudication(),
                "derived_dimensions": [
                    {
                        "source_derived_dimension_id": "DD404",
                        "role": "feature_height",
                        "value": 4.0,
                        "confidence": 0.8,
                        "evidence_ids": ["D1"],
                        "reason": "派生 ID 不存在",
                    }
                ],
            },
            _evidence_package(),
        )

        self.assertFalse(valid)
        self.assertTrue(any("derived_dimensions 引用" in error for error in errors))

    def test_pipeline_blocks_when_adjudication_returns_clarification_questions(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.config = {}
        pipeline.semantic_adjudicator = SimpleNamespace(
            adjudicate=lambda context, file_path=None: {
                **_valid_adjudication(),
                "clarification_questions": [
                    {
                        "id": "confirm_D1_role",
                        "kind": "single_choice",
                        "text": "请确认 D1 是否表示主体厚度。",
                        "options": [],
                    }
                ],
            }
        )
        pipeline.semantic_generator = SimpleNamespace(generate=unittest.mock.Mock())
        pipeline.instruction_generator = SimpleNamespace(generate=unittest.mock.Mock())

        result = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": [{"text": "16", "value": 16.0, "type": "线性"}]},
            local_relationships=None,
            extrude_height=10.0,
        )

        self.assertTrue(result["modeling_instructions"]["blocked_by_clarification"])
        self.assertEqual(
            "confirm_D1_role",
            result["semantic_policy"]["clarification_questions"][0]["id"],
        )
        self.assertEqual(
            "semantic_adjudication",
            result["semantic_policy"]["clarification_questions"][0]["source_stage"],
        )
        self.assertEqual(
            "semantic_adjudication",
            result["clarification_context"]["clarification_stage"],
        )
        pipeline.semantic_generator.generate.assert_not_called()
        pipeline.instruction_generator.generate.assert_not_called()

    def test_successful_adjudication_replaces_legacy_policy_questions(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_adjudicator = SimpleNamespace(
            adjudicate=lambda context, file_path=None: _valid_adjudication()
        )
        policy_result = {
            "adjudicated_context": {
                "semantic_policy": {"drawing_evidence_package": _evidence_package()}
            },
            "clarification_questions": [
                {
                    "id": "bind_profile_length",
                    "kind": "single_choice",
                    "text": "旧本地策略提出的追问",
                }
            ],
        }

        updated_policy, _updated_context = pipeline._apply_semantic_adjudication(
            policy_result,
            file_path=None,
        )

        self.assertEqual([], updated_policy["clarification_questions"])

    def test_failed_adjudication_preserves_legacy_policy_questions(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_adjudicator = SimpleNamespace(
            adjudicate=lambda context, file_path=None: {
                **_valid_adjudication(),
                "status": "failed",
                "clarification_questions": [],
            }
        )
        legacy_questions = [
            {
                "id": "bind_profile_length",
                "kind": "single_choice",
                "text": "旧本地策略提出的追问",
            }
        ]
        policy_result = {
            "adjudicated_context": {
                "semantic_policy": {"drawing_evidence_package": _evidence_package()}
            },
            "clarification_questions": legacy_questions,
        }

        updated_policy, _updated_context = pipeline._apply_semantic_adjudication(
            policy_result,
            file_path=None,
        )

        self.assertEqual(legacy_questions, updated_policy["clarification_questions"])

    def test_pipeline_passes_semantic_adjudication_answers_back_to_adjudicator(self):
        seen_contexts = []

        class FakeAdjudicator:
            def adjudicate(self, context, file_path=None):
                seen_contexts.append(context)
                if len(seen_contexts) == 1:
                    return {
                        **_valid_adjudication(),
                        "clarification_questions": [
                            {
                                "id": "confirm_D1_role",
                                "kind": "single_choice",
                                "text": "请确认 D1 是否表示主体厚度。",
                                "options": [],
                            }
                        ],
                    }
                return _valid_adjudication()

        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.config = {}
        pipeline.semantic_adjudicator = FakeAdjudicator()
        pipeline.semantic_generator = SimpleNamespace(
            generate=unittest.mock.Mock(return_value={
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
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            })
        )
        pipeline.instruction_generator = SimpleNamespace(
            generate=unittest.mock.Mock(return_value={"freecad_script": "pass"})
        )
        pipeline.modeling_path_registry = SimpleNamespace(
            choose=unittest.mock.Mock(return_value={"modeling_path": "semantic_reconstruction"}),
            build_routed_modeling_result=unittest.mock.Mock(return_value=None),
        )

        pending = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": [{"text": "16", "value": 16.0, "type": "线性"}]},
            local_relationships=None,
            extrude_height=10.0,
        )
        pipeline.continue_with_clarification(
            pending["clarification_context"],
            {"confirm_D1_role": "extrusion_depth"},
        )

        clarification = seen_contexts[1]["semantic_adjudication_clarification"]
        self.assertEqual(
            {"confirm_D1_role": "extrusion_depth"},
            clarification["answers"],
        )


if __name__ == "__main__":
    unittest.main()
