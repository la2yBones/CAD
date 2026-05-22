# -*- coding: utf-8 -*-

import unittest

from src.reconstruction.semantic_policy import SemanticPolicy
from src.reconstruction.clarification_response import ClarificationResponse


class TestSemanticPolicy(unittest.TestCase):
    def test_semantic_policy_hides_geometry_coordinates_when_annotations_exist(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [{"text": "30", "value": 30.0, "type": "线性"}],
                "geometry_summary": {
                    "arc_summary": {"count": 4, "radius_values": [1.5]},
                },
                "source_entities": [{"type": "LINE", "start": [0, 0], "end": [48.5, 0]}],
                "view_analysis": {
                    "views": [
                        {
                            "name": "main",
                            "entities": [{"type": "LINE", "start": [0, 0], "end": [48.5, 0]}],
                        }
                    ]
                },
            }
        )

        self.assertEqual("annotation", policy_result["dimension_source"])
        adjudicated = policy_result["adjudicated_context"]
        self.assertNotIn("source_entities", adjudicated)
        self.assertNotIn("entities", adjudicated["view_analysis"]["views"][0])
        self.assertEqual(
            {"count": 4, "radius_values": [1.5]},
            adjudicated["geometry_summary"]["arc_summary"],
        )
        self.assertEqual("unresolved_linear", policy_result["dimension_bindings"][0]["semantic_role"])

    def test_semantic_policy_keeps_geometry_when_annotations_missing(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [],
                "source_entities": [{"type": "LINE", "start": [0, 0], "end": [48.5, 0]}],
                "view_analysis": {"views": []},
            }
        )

        self.assertEqual("geometry", policy_result["dimension_source"])
        self.assertIn("source_entities", policy_result["adjudicated_context"])

    def test_semantic_policy_binds_textually_explicit_dimensions(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {"text": "R15", "value": 15.0, "type": "半径"},
                    {"text": "⌀10", "value": 10.0, "type": "直径"},
                    {"text": "M8", "value": 8.0, "type": "螺纹"},
                    {"text": "1x45%%d", "value": 1.0, "type": "线性"},
                    {"text": "30", "value": 30.0, "type": "线性"},
                ],
                "view_analysis": {"views": []},
            }
        )

        bindings = {item["text"]: item for item in policy_result["dimension_bindings"]}
        self.assertEqual("radius", bindings["R15"]["semantic_role"])
        self.assertEqual("diameter", bindings["⌀10"]["semantic_role"])
        self.assertEqual("thread_size", bindings["M8"]["semantic_role"])
        self.assertEqual("chamfer", bindings["1x45%%d"]["semantic_role"])
        self.assertTrue(any("外部尖角削除" in item for item in bindings["1x45%%d"]["evidence"]))
        self.assertEqual("unresolved_linear", bindings["30"]["semantic_role"])

        constraints = policy_result["feature_constraints"]
        self.assertTrue(constraints["chamfer_is_external_corner_removal"])
        self.assertTrue(constraints["chamfer_must_not_create_recess_or_slot"])

    def test_semantic_policy_preserves_repeated_radius_metadata(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "R=4x1.5",
                        "value": 1.5,
                        "type": "半径",
                        "callout": "repeated_radius",
                        "repeat_count": 4,
                        "radius_value": 1.5,
                    }
                ],
                "view_analysis": {"views": []},
            }
        )

        allowed = policy_result["dimension_plan"]["allowed_dimensions"][0]
        self.assertEqual("radius", allowed["role"])
        self.assertEqual(1.5, allowed["value"])
        self.assertEqual("repeated_radius", allowed["callout"])
        self.assertEqual(4, allowed["repeat_count"])

    def test_semantic_policy_preserves_repeated_diameter_metadata(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "3xφ5",
                        "value": 5.0,
                        "type": "直径",
                        "callout": "repeated_diameter",
                        "repeat_count": 3,
                        "diameter_value": 5.0,
                    }
                ],
                "view_analysis": {"views": []},
            }
        )

        allowed = policy_result["dimension_plan"]["allowed_dimensions"][0]
        self.assertEqual("diameter", allowed["role"])
        self.assertEqual(5.0, allowed["value"])
        self.assertEqual("repeated_diameter", allowed["callout"])
        self.assertEqual(3, allowed["repeat_count"])
        self.assertEqual(5.0, allowed["diameter_value"])

    def test_semantic_policy_preserves_repeated_thread_metadata(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "3-M5",
                        "value": 5.0,
                        "type": "螺纹",
                        "callout": "repeated_thread",
                        "repeat_count": 3,
                        "thread_value": 5.0,
                    }
                ],
                "view_analysis": {"views": []},
            }
        )

        allowed = policy_result["dimension_plan"]["allowed_dimensions"][0]
        self.assertEqual("thread_size", allowed["role"])
        self.assertEqual(5.0, allowed["value"])
        self.assertEqual("repeated_thread", allowed["callout"])
        self.assertEqual(3, allowed["repeat_count"])
        self.assertEqual(5.0, allowed["thread_value"])

    def test_semantic_policy_promotes_user_confirmed_feature_dimension(self):
        answer = (
            '{"action":"bind_feature_dimension","dimension_text":"40",'
            '"role":"feature_depth","feature_kind":"boss",'
            '"feature_description":"中心圆柱凸台"}'
        )
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "40",
                        "value": 40.0,
                        "type": "线性",
                        "position": [0, 0, 0],
                    }
                ],
                "view_analysis": {"views": []},
            },
            clarification_answers={
                "bind_feature_detail_dimension": answer,
            },
        )

        self.assertEqual([], policy_result["dimension_plan"]["unresolved_dimensions"])
        allowed = policy_result["dimension_plan"]["allowed_dimensions"][0]
        self.assertEqual("feature_depth", allowed["role"])
        self.assertEqual(40.0, allowed["value"])
        self.assertEqual("boss", allowed["feature_kind"])
        self.assertEqual("中心圆柱凸台", allowed["feature_description"])
        self.assertEqual("user_confirmed", allowed["source"])

    def test_semantic_policy_binds_linear_dimension_when_view_and_line_agree(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "position": [20, 10, 0],
                        "associated_lines": [
                            {"line": {"start": [0, 10, 0], "end": [40, 10, 0]}}
                        ],
                    },
                    {
                        "text": "12",
                        "value": 12.0,
                        "type": "线性",
                        "position": [80, 10, 0],
                        "associated_lines": [
                            {"line": {"start": [60, 10, 0], "end": [100, 10, 0]}}
                        ],
                    },
                    {
                        "text": "18",
                        "value": 18.0,
                        "type": "线性",
                        "position": [10, 20, 0],
                        "associated_lines": [
                            {"line": {"start": [10, 0, 0], "end": [10, 40, 0]}}
                        ],
                    },
                ],
                "view_analysis": {
                    "views": [
                        {"name": "main", "bbox": [0, 0, 40, 40]},
                        {"name": "right", "bbox": [60, 0, 100, 40]},
                    ]
                },
            }
        )

        bindings = {item["text"]: item for item in policy_result["dimension_bindings"]}
        self.assertEqual("profile_length", bindings["30"]["semantic_role"])
        self.assertEqual("projected_profile_horizontal_extent", bindings["12"]["semantic_role"])
        self.assertEqual("profile_height", bindings["18"]["semantic_role"])

    def test_semantic_policy_leaves_external_linear_dimension_unresolved(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "24",
                        "value": 24.0,
                        "type": "线性",
                        "position": [120, 10, 0],
                        "associated_lines": [
                            {"line": {"start": [60, 10, 0], "end": [100, 10, 0]}}
                        ],
                    }
                    ,
                    {
                        "text": "21",
                        "value": 21.0,
                        "type": "线性",
                        "position": [120, 20, 0],
                        "associated_lines": [
                            {"line": {"start": [80, 0, 0], "end": [80, 40, 0]}}
                        ],
                    },
                ],
                "view_analysis": {
                    "views": [
                        {"name": "right", "bbox": [60, 0, 100, 40]},
                    ]
                },
            }
        )

        self.assertEqual(
            "unresolved_linear",
            policy_result["dimension_bindings"][0]["semantic_role"],
        )
        self.assertEqual(
            "unresolved_linear",
            policy_result["dimension_bindings"][1]["semantic_role"],
        )

    def test_semantic_policy_asks_when_key_role_values_conflict(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "position": [20, 10, 0],
                        "associated_lines": [
                            {"line": {"start": [0, 10, 0], "end": [40, 10, 0]}}
                        ],
                    },
                    {
                        "text": "39",
                        "value": 39.0,
                        "type": "线性",
                        "position": [22, 12, 0],
                        "associated_lines": [
                            {"line": {"start": [0, 12, 0], "end": [40, 12, 0]}}
                        ],
                    },
                ],
                "view_analysis": {
                    "views": [{"name": "main", "bbox": [0, 0, 40, 40]}]
                },
            }
        )

        question = policy_result["clarification_questions"][0]
        self.assertEqual("resolve_profile_length", question["id"])
        self.assertIn("主视图水平总尺寸", question["text"])
        self.assertNotIn("profile_length", question["text"])
        self.assertIn("标注值", question["example"])
        self.assertEqual(["30", "39"], [option["value"] for option in question["options"]])

    def test_user_modeling_hint_enters_adjudicated_context_and_unblocks_recovery(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "position": [20, 10, 0],
                        "associated_lines": [
                            {"line": {"start": [0, 10, 0], "end": [40, 10, 0]}}
                        ],
                    },
                    {
                        "text": "39",
                        "value": 39.0,
                        "type": "线性",
                        "position": [22, 12, 0],
                        "associated_lines": [
                            {"line": {"start": [0, 12, 0], "end": [40, 12, 0]}}
                        ],
                    },
                ],
                "view_analysis": {
                    "views": [{"name": "main", "bbox": [0, 0, 40, 40]}]
                },
            },
            clarification_answers={
                "user_modeling_hint": "主体按外轮廓建模，内部细节可以先跳过。"
            },
        )

        self.assertEqual([], policy_result["clarification_questions"])
        adjudicated = policy_result["adjudicated_context"]
        self.assertEqual(
            "主体按外轮廓建模，内部细节可以先跳过。",
            adjudicated["user_modeling_hint"],
        )
        self.assertIn(
            "用户提供了补充建模提示",
            "\n".join(policy_result["assumptions"]),
        )

    def test_clarification_response_carries_hint_policy_into_context(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [],
                "view_analysis": {"views": []},
            },
            clarification_answers=ClarificationResponse(
                user_modeling_hint="优先生成主体。",
                conflict_policy="drawing_facts_override_user_hint",
            ),
        )

        adjudicated = policy_result["adjudicated_context"]
        self.assertEqual("优先生成主体。", adjudicated["user_modeling_hint"])
        self.assertEqual(
            "drawing_facts_override_user_hint",
            adjudicated["semantic_policy"]["user_modeling_hint_policy"],
        )

    def test_semantic_policy_asks_for_missing_multiview_axes(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {"text": "30", "value": 30.0, "type": "线性"},
                    {"text": "12", "value": 12.0, "type": "线性"},
                ],
                "view_analysis": {
                    "drawing_type": "two_view",
                    "views": [
                        {"name": "main", "bbox": [0, 0, 40, 40]},
                        {"name": "right", "bbox": [60, 0, 100, 40]},
                    ],
                },
            }
        )

        questions = {item["id"]: item for item in policy_result["clarification_questions"]}
        self.assertIn("bind_profile_length", questions)
        self.assertIn("请确认哪个标注值", questions["bind_profile_length"]["text"])
        self.assertIn("不确定", questions["bind_profile_length"]["example"])
        self.assertEqual(
            ["30", "12", "__unknown__"],
            [option["value"] for option in questions["bind_profile_length"]["options"]],
        )
        self.assertIn("不确定", questions["bind_profile_length"]["text"])

    def test_semantic_policy_derives_composite_main_length_from_dimension_chain(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "9",
                        "value": 9.0,
                        "type": "线性",
                        "definition_points": [[0, 10, 0], [9, 10, 0]],
                    },
                    {
                        "text": "39",
                        "value": 39.0,
                        "type": "线性",
                        "definition_points": [[9, 10, 0], [48, 10, 0]],
                    },
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "definition_points": [[18, 12, 0], [48, 12, 0]],
                    },
                ],
                "view_analysis": {
                    "drawing_type": "two_view",
                    "views": [{"name": "main", "bbox": [0, 0, 50, 30]}],
                },
            }
        )

        bindings = {item["text"]: item for item in policy_result["dimension_bindings"]}
        self.assertEqual("profile_length", bindings["9+39"]["semantic_role"])
        self.assertEqual(48.0, bindings["9+39"]["value"])
        self.assertEqual("profile_length_segment", bindings["9"]["semantic_role"])
        self.assertEqual("profile_length_segment", bindings["39"]["semantic_role"])
        self.assertEqual("unresolved_linear", bindings["30"]["semantic_role"])
        self.assertEqual([], policy_result["clarification_questions"])

        plan = policy_result["dimension_plan"]
        allowed = {item["text"]: item for item in plan["allowed_dimensions"]}
        segments = {item["text"]: item for item in plan["segment_dimensions"]}
        unresolved = {item["text"]: item for item in plan["unresolved_dimensions"]}
        self.assertEqual("profile_length", allowed["9+39"]["role"])
        self.assertEqual("profile_length_segment", segments["9"]["role"])
        self.assertEqual("profile_length_segment", segments["39"]["role"])
        self.assertEqual("unresolved_linear", unresolved["30"]["role"])

    def test_semantic_policy_binds_equal_orthogonal_main_dimensions_as_square(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [
                    {
                        "text": "96",
                        "value": 96.0,
                        "type": "线性",
                        "definition_points": [[0, 0, 0], [96, 0, 0]],
                    },
                    {
                        "text": "96",
                        "value": 96.0,
                        "type": "线性",
                        "definition_points": [[0, 0, 0], [0, 96, 0]],
                    },
                    {"text": "φ32", "value": 32.0, "type": "直径"},
                    {"text": "φ64", "value": 64.0, "type": "直径"},
                ],
                "view_analysis": {
                    "drawing_type": "two_view",
                    "views": [
                        {"name": "main", "bbox": [0, 0, 96, 96]},
                        {"name": "right", "bbox": [140, 0, 200, 96]},
                    ],
                },
            }
        )

        roles = [item["semantic_role"] for item in policy_result["dimension_bindings"]]
        self.assertIn("profile_length", roles)
        self.assertIn("profile_height", roles)
        self.assertEqual([], policy_result["clarification_questions"])
        allowed = policy_result["dimension_plan"]["allowed_dimensions"]
        self.assertEqual(
            ["profile_length", "profile_height", "diameter", "diameter"],
            [item["role"] for item in allowed],
        )

    def test_semantic_policy_applies_clarification_answers(self):
        context = {
            "context_version": "reconstruction_context_v1",
            "dimensions": [
                {"text": "30", "value": 30.0, "type": "线性"},
                {"text": "12", "value": 12.0, "type": "线性"},
            ],
            "view_analysis": {
                "drawing_type": "two_view",
                "views": [
                    {"name": "main", "bbox": [0, 0, 40, 40]},
                    {"name": "right", "bbox": [60, 0, 100, 40]},
                ],
            },
        }

        policy_result = SemanticPolicy().evaluate(
            context,
            clarification_answers={
                "bind_profile_length": "30",
            },
        )

        bindings = {item["text"]: item for item in policy_result["dimension_bindings"]}
        self.assertEqual("profile_length", bindings["30"]["semantic_role"])
        self.assertEqual([], policy_result["clarification_questions"])

    def test_semantic_policy_accepts_unknown_clarification_answer(self):
        context = {
            "context_version": "reconstruction_context_v1",
            "dimensions": [
                {"text": "30", "value": 30.0, "type": "线性"},
                {"text": "12", "value": 12.0, "type": "线性"},
            ],
            "view_analysis": {
                "drawing_type": "two_view",
                "views": [
                    {"name": "main", "bbox": [0, 0, 40, 40]},
                    {"name": "right", "bbox": [60, 0, 100, 40]},
                ],
            },
        }

        policy_result = SemanticPolicy().evaluate(
            context,
            clarification_answers={
                "bind_profile_length": SemanticPolicy.UNKNOWN_ANSWER,
            },
        )

        roles = {item["text"]: item["semantic_role"] for item in policy_result["dimension_bindings"]}
        self.assertEqual("excluded_by_user", roles["30"])
        self.assertEqual("excluded_by_user", roles["12"])
        self.assertEqual([], policy_result["clarification_questions"])
        self.assertEqual(2, len(policy_result["dimension_plan"]["excluded_dimensions"]))



if __name__ == "__main__":
    unittest.main()
