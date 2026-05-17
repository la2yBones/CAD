# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.intelligent_analyzer.modeling_generator import FreeCADInstructionGenerator
from src.intelligent_analyzer.reconstruction_context import ReconstructionContextBuilder
from src.intelligent_analyzer.dimension_extractor import DimensionExtractor
from src.intelligent_analyzer.semantic_schema import PartSemanticsValidator
from src.intelligent_analyzer.pipeline import IntelligentEngineeringAnalyzer
from src.utils.stage_confirmation import (
    CallbackStageConfirmation,
    StageConfirmationStopped,
    StageReview,
    resolve_stage_confirmation,
)
from src.reconstruction.modeling_constraints import ModelingConstraints
from src.reconstruction.semantic_policy import SemanticPolicy
from src.reconstruction.pipeline import SemanticReconstructionPipeline
from src.reconstruction.modeling_path import choose_modeling_path
from src.model_generator.freecad_bridge import FreeCADBridge
from src.model_generator.ai_script_runner import AIScriptRunner
from src.batch_processor.pipeline import CADPipeline
from src.batch_processor.processor import CADProcessor, CADProcessResult, PipelineStatus


class TestAIModeling(unittest.TestCase):
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
        self.assertIn("六角头螺栓主视图左侧头部的 R15 标注", prompt)
        self.assertIn("不得把它建成向实体内部凹陷的槽", prompt)
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

    def test_dimension_extractor_preserves_dimension_entity_definition_points(self):
        result = DimensionExtractor().extract_dimensions(
            {
                "entities": [
                    {
                        "type": "DIMENSION",
                        "rendered_text": "30",
                        "text_position": [5, 5, 0],
                        "definition_points": [[0, 0, 0], [30, 0, 0]],
                        "measurement": 30.0,
                        "dimension_type": 0,
                    }
                ]
            }
        )

        dimension = result["dimensions"][0]
        self.assertEqual([[0, 0, 0], [30, 0, 0]], dimension["definition_points"])
        self.assertEqual(30.0, dimension["measurement"])

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

    def test_modeling_path_routes_simple_single_profile_to_planar_extrude(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
            },
        )

        self.assertEqual("planar_extrude", decision["modeling_path"])

    def test_modeling_path_keeps_complex_single_view_in_semantic_reconstruction(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [{"kind": "boss"}],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
            },
        )

        self.assertEqual("semantic_reconstruction", decision["modeling_path"])

    def test_reconstruction_summary_preserves_semantic_policy(self):
        summary = ReconstructionContextBuilder().build_summary(
            {
                "drawing": {},
                "view_analysis": {"views": []},
                "dimensions": [],
                "semantic_policy": {
                    "dimension_source": "annotation",
                    "dimension_bindings": [],
                },
            }
        )

        self.assertEqual("annotation", summary["semantic_policy"]["dimension_source"])

    def test_semantic_policy_hides_geometry_coordinates_when_annotations_exist(self):
        policy_result = SemanticPolicy().evaluate(
            {
                "context_version": "reconstruction_context_v1",
                "dimensions": [{"text": "30", "value": 30.0, "type": "线性"}],
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
        self.assertEqual(["30", "39"], [option["value"] for option in question["options"]])

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

    def test_modeling_constraints_validate_allowed_script(self):
        script = """
import FreeCAD
import Part
import math
doc = FreeCAD.newDocument("GeneratedModel")
p1 = FreeCAD.Vector(0, 0, 0)
p2 = FreeCAD.Vector(1, 0, 0)
edge = Part.LineSegment(p1, p2).toShape()
wire = Part.Wire([edge])
face = Part.Face(wire)
solid = face.revolve(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0), 360)
Part.show(solid, "Solid")
doc.recompute()
"""
        result = ModelingConstraints().validate_script(script)

        self.assertTrue(result.success, result.error)

    def test_modeling_constraints_reject_forbidden_script_features(self):
        constraints = ModelingConstraints()
        cases = [
            ("import os\n", "禁止导入模块"),
            ("while True:\n    pass\n", "禁止使用 while"),
            ("exec('print(1)')\n", "禁止动态执行"),
            ("shape = body.makeFillet(1, [])\n", "禁止使用 FreeCAD 拓扑自动化"),
            ("Part.ShapeSplit()\n", "禁止使用 FreeCAD 拓扑自动化"),
        ]

        for script, expected in cases:
            with self.subTest(script=script):
                result = constraints.validate_script(script)
                self.assertFalse(result.success)
                self.assertIn(expected, result.error)

    def test_modeling_constraints_reject_malformed_arc_of_circle(self):
        script = """
import FreeCAD
import Part
arc = Part.ArcOfCircle(
    Part.Circle(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 5),
    0,
)
"""

        result = ModelingConstraints().validate_script(script)

        self.assertFalse(result.success)
        self.assertIn("Part.ArcOfCircle must use exactly 3 positional arguments", result.error)

    def test_part_semantics_validator_requires_core_fields(self):
        valid, errors = PartSemanticsValidator().validate(
            {
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
                "dimension_source": "annotation",
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertFalse(valid)
        self.assertIn("confidence 必须介于 0 到 1 之间", errors)

    def test_part_semantics_validator_rejects_mixed_annotation_dimensions(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "bolt",
                "confidence": 0.9,
                "summary": "",
                "evidence": [],
                "candidate_interpretations": [],
                "coordinate_system": {},
                "dimension_source": "annotation",
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [
                    {"name": "annotated_length", "value": 30.0, "unit": "mm"},
                    {"name": "measured_diameter", "value": 48.5, "unit": "mm"},
                ],
                "uncertainties": [],
                "warnings": [],
            },
            {"dimensions": [{"text": "30", "value": 30.0}]},
        )

        self.assertFalse(valid)
        self.assertTrue(any("key_dimensions 只能使用标注值" in error for error in errors))

    def test_part_semantics_validator_rejects_policy_dimension_source_drift(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "bolt",
                "confidence": 0.9,
                "summary": "",
                "evidence": [],
                "candidate_interpretations": [],
                "coordinate_system": {},
                "dimension_source": "geometry",
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            },
            {
                "dimensions": [{"text": "30", "value": 30.0}],
                "semantic_policy": {"dimension_source": "annotation"},
            },
        )

        self.assertFalse(valid)
        self.assertTrue(any("必须服从 semantic_policy.dimension_source" in error for error in errors))

    def test_part_semantics_validator_rejects_dimensions_outside_dimension_plan(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "bolt",
                "confidence": 0.9,
                "summary": "",
                "evidence": [],
                "candidate_interpretations": [],
                "coordinate_system": {},
                "dimension_source": "annotation",
                "base_features": [],
                "additive_features": [],
                "subtractive_features": [],
                "key_dimensions": [
                    {"name": "total_length", "value": 48.0, "unit": "mm"},
                    {"name": "thread_length", "value": 30.0, "unit": "mm"},
                ],
                "uncertainties": [],
                "warnings": [],
            },
            {
                "dimensions": [
                    {"text": "9", "value": 9.0},
                    {"text": "39", "value": 39.0},
                    {"text": "30", "value": 30.0},
                ],
                "semantic_policy": {
                    "dimension_source": "annotation",
                    "dimension_plan": {
                        "allowed_dimensions": [
                            {"text": "9+39", "value": 48.0, "role": "profile_length"}
                        ],
                        "unresolved_dimensions": [
                            {"text": "30", "value": 30.0, "role": "unresolved_linear"}
                        ],
                    },
                },
            },
        )

        self.assertFalse(valid)
        self.assertTrue(any("dimension_plan.allowed_dimensions" in error for error in errors))

    def test_part_semantics_validator_allows_adjudicated_composite_dimensions(self):
        valid, errors = PartSemanticsValidator().validate(
            {
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
                "key_dimensions": [
                    {"name": "total_length", "value": 48.0, "unit": "mm"},
                ],
                "uncertainties": [],
                "warnings": [],
            },
            {
                "dimensions": [
                    {"text": "9", "value": 9.0},
                    {"text": "39", "value": 39.0},
                ],
                "semantic_policy": {
                    "dimension_source": "annotation",
                    "dimension_plan": {
                        "allowed_dimensions": [
                            {"text": "9+39", "value": 48.0, "role": "profile_length"}
                        ],
                        "segment_dimensions": [
                            {"text": "9", "value": 9.0, "role": "profile_length_segment"},
                            {"text": "39", "value": 39.0, "role": "profile_length_segment"},
                        ],
                    },
                },
            },
        )

        self.assertTrue(valid)
        self.assertEqual([], errors)

    def test_low_semantic_confidence_blocks_modeling(self):
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.config = {"semantic_min_confidence": 0.7}
        self.assertFalse(analyzer._is_semantic_confidence_sufficient({"confidence": 0.4}))
        self.assertTrue(analyzer._is_semantic_confidence_sufficient({"confidence": 0.8}))

    def test_reconstruction_pipeline_stops_before_llm_when_clarification_needed(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.semantic_generator = unittest.mock.Mock()
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.config = {}
        pipeline.stage_confirmation = resolve_stage_confirmation(pipeline.config)

        result = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={
                "drawing_type": "two_view",
                "views": [
                    {"name": "main", "bbox": [0, 0, 40, 40], "entities": []},
                    {"name": "right", "bbox": [60, 0, 100, 40], "entities": []},
                ],
            },
            dimension_data={
                "dimensions": [
                    {"text": "30", "value": 30.0, "type": "线性"},
                    {"text": "12", "value": 12.0, "type": "线性"},
                ]
            },
            local_relationships=None,
            extrude_height=10.0,
        )

        pipeline.semantic_generator.generate.assert_not_called()
        self.assertTrue(result["modeling_instructions"]["blocked_by_clarification"])
        self.assertTrue(result["semantic_policy"]["clarification_questions"])
        self.assertIn("clarification_context", result)

    def test_reconstruction_pipeline_continues_from_clarification_context(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
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
                    "key_dimensions": [],
                    "uncertainties": [],
                    "warnings": [],
                }
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(return_value={"freecad_script": "pass"})
        )
        pipeline.config = {}

        pending = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={
                "drawing_type": "two_view",
                "views": [
                    {"name": "main", "bbox": [0, 0, 40, 40], "entities": []},
                    {"name": "right", "bbox": [60, 0, 100, 40], "entities": []},
                ],
            },
            dimension_data={
                "dimensions": [
                    {"text": "30", "value": 30.0, "type": "线性"},
                    {"text": "12", "value": 12.0, "type": "线性"},
                ]
            },
            local_relationships=None,
            extrude_height=10.0,
        )
        resumed = pipeline.continue_with_clarification(
            pending["clarification_context"],
            {"bind_profile_length": "30"},
        )

        pipeline.semantic_generator.generate.assert_called_once()
        pipeline.instruction_generator.generate.assert_called_once()
        self.assertEqual([], resumed["semantic_policy"]["clarification_questions"])
        self.assertEqual("pass", resumed["modeling_instructions"]["freecad_script"])

    def test_reconstruction_pipeline_routes_simple_single_profile_to_planar_extrude(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "profile",
                    "confidence": 0.9,
                    "summary": "simple profile",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                    "dimension_source": "geometry",
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [],
                    "subtractive_features": [],
                    "key_dimensions": [],
                    "uncertainties": [],
                    "warnings": [],
                }
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.config = {}

        result = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": []},
            local_relationships=None,
            extrude_height=10.0,
        )

        self.assertEqual("planar_extrude", result["modeling_path_decision"]["modeling_path"])
        self.assertTrue(result["modeling_instructions"]["routed_to_planar_extrude"])
        pipeline.instruction_generator.generate.assert_not_called()

    def test_stage_confirmation_default_adapter_continues(self):
        confirmation = resolve_stage_confirmation({})

        self.assertTrue(confirmation.should_continue(StageReview("view_analysis", {})))

    def test_reconstruction_pipeline_uses_stage_confirmation_adapter(self):
        calls = []
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.semantic_generator = unittest.mock.Mock()
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.config = {}
        pipeline.stage_confirmation = CallbackStageConfirmation(
            lambda stage, payload: calls.append(stage) or False
        )

        with self.assertRaises(StageConfirmationStopped):
            pipeline.run(
                geometry_data={"entities": []},
                view_analysis={"drawing_type": "single_view", "views": []},
                dimension_data={"dimensions": []},
                local_relationships=None,
                extrude_height=10.0,
            )

        self.assertEqual(["view_analysis"], calls)
        pipeline.semantic_generator.generate.assert_not_called()

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
        })

        self.assertEqual(["view_analysis", "semantic_reconstruction"], calls)

    def test_cad_process_result_supports_needs_clarification_status(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")
        result.mark_needs_clarification(
            [{"id": "bind_profile_length", "text": "请选择主视图总尺寸", "kind": "single_choice"}],
            {"marker": "keep"},
        )

        self.assertFalse(result.success)
        self.assertEqual(PipelineStatus.NEEDS_CLARIFICATION, result.status)
        self.assertEqual("needs_clarification", result.to_dict()["status"])
        self.assertEqual({"marker": "keep"}, result.clarification_context)

    def test_cad_process_result_serializes_mode_and_modeling_path(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )

        self.assertEqual("intelligent", result.to_dict()["mode"])
        self.assertEqual("semantic_reconstruction", result.to_dict()["modeling_path"])

    def test_cad_process_result_supports_stopped_by_user_status(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")

        result.mark_stopped_by_user("用户在 view_analysis 阶段确认后停止处理")

        self.assertFalse(result.success)
        self.assertEqual(PipelineStatus.STOPPED_BY_USER, result.status)
        self.assertEqual("stopped_by_user", result.to_dict()["status"])
        self.assertIn("用户在 view_analysis", result.error_message)

    def test_processor_maps_stage_confirmation_stop_to_status(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {
            "api": {
                "deepseek": {
                    "api_key": "test-key",
                    "_stage_confirmation": CallbackStageConfirmation(
                        lambda stage, payload: False
                    ),
                }
            }
        }
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(return_value={})

        result = processor.process_with_intelligent_analysis(
            "drawing.dxf",
            {},
            10.0,
        )

        self.assertEqual(PipelineStatus.STOPPED_BY_USER, result.status)
        self.assertIn("用户在 view_analysis", result.error_message)

    def test_pipeline_summary_separates_user_stop_from_failure(self):
        completed = CADProcessResult(success=True, input_file="ok.dxf")
        completed.mark_completed()
        stopped = CADProcessResult(success=False, input_file="stop.dxf")
        stopped.mark_stopped_by_user()
        failed = CADProcessResult(success=False, input_file="bad.dxf")
        failed.mark_failed("bad")

        pipeline = CADPipeline.__new__(CADPipeline)
        summary = pipeline.get_summary({
            "ok": completed,
            "stop": stopped,
            "bad": failed,
        })

        self.assertEqual(1, summary["success"])
        self.assertEqual(1, summary["stopped_by_user"])
        self.assertEqual(1, summary["failed"])

    def test_basic_processing_skips_multiview_analysis(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {}
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._get_modeler = unittest.mock.Mock()
        modeler = unittest.mock.Mock()
        modeler.export.return_value = False
        processor._get_modeler.return_value = unittest.mock.Mock(return_value=modeler)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(
            side_effect=AssertionError("basic mode must not inspect views")
        )

        result = processor.process_single_file(
            "drawing.dxf",
            {},
            10.0,
            enable_analysis=False,
        )

        self.assertTrue(result.success)
        processor._prepare_intelligent_view_context.assert_not_called()
        self.assertEqual("basic", result.mode)
        self.assertEqual("planar_extrude", result.modeling_path)

    def test_geometry_data_processing_skips_multiview_analysis(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {}
        processor._get_modeler = unittest.mock.Mock()
        modeler = unittest.mock.Mock()
        processor._get_modeler.return_value = unittest.mock.Mock(return_value=modeler)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(
            side_effect=AssertionError("geometry execution must not inspect views")
        )

        result = processor.process_from_geometry_data(
            {"entities": []},
            {},
            10.0,
        )

        self.assertTrue(result.success)
        processor._prepare_intelligent_view_context.assert_not_called()
        self.assertEqual("basic", result.mode)
        self.assertEqual("planar_extrude", result.modeling_path)

    def test_intelligent_processing_routes_planar_decision_to_basic_executor(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {
            "api": {
                "deepseek": {"api_key": "test-key"},
            }
        }
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(return_value={})
        processor._run_planar_extrude_for_intelligent_result = unittest.mock.Mock()

        routed_result = CADProcessResult(
            success=True,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="planar_extrude",
        )
        processor._run_planar_extrude_for_intelligent_result.return_value = routed_result

        fake_analyzer = unittest.mock.Mock()
        fake_analyzer.analyze_full.return_value = {
            "modeling_path_decision": {"modeling_path": "planar_extrude", "reason": "simple"},
            "modeling_instructions": {
                "analysis_summary": "",
                "modeling_strategy": "",
                "freecad_script": "",
                "instructions": [],
                "key_dimensions": [],
                "warnings": [],
                "routed_to_planar_extrude": True,
            },
        }
        fake_analyzer.save_results.return_value = None

        with patch(
            "src.intelligent_analyzer.IntelligentEngineeringAnalyzer",
            return_value=fake_analyzer,
        ):
            result = processor.process_with_intelligent_analysis("drawing.dxf", {}, 10.0)

        self.assertIs(result, routed_result)
        processor._run_planar_extrude_for_intelligent_result.assert_called_once()

    def test_execute_intelligent_modeling_path_runs_ai_script_for_semantic_reconstruction(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {}
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.return_value = {
            "success": True,
            "step_path": "drawing.step",
            "fcstd_path": "drawing.FCStd",
        }

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            completed = processor._execute_intelligent_modeling_path(
                result=result,
                analysis_result={
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": {"freecad_script": "pass"},
                },
                geometry_data={"entities": []},
                output_structure={},
                extrude_height=10.0,
                missing_script_message="missing",
                script_failure_prefix="failed",
                completion_message="done",
            )

        self.assertTrue(completed.success)
        self.assertEqual("drawing.step", completed.output_paths["model_step"])
        self.assertEqual("drawing.FCStd", completed.output_paths["model_fcstd"])

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
