# -*- coding: utf-8 -*-

import unittest
import unittest.mock

from src.intelligent_analyzer.reconstruction_context import ReconstructionContextBuilder
from src.reconstruction.semantic_policy import SemanticPolicy
from src.reconstruction.pipeline import SemanticReconstructionPipeline
from src.utils.stage_confirmation import (
    CallbackStageConfirmation,
    StageConfirmationStopped,
    resolve_stage_confirmation,
)


class TestSemanticReconstructionPipeline(unittest.TestCase):
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
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "definition_points": [[0, 10, 0], [30, 10, 0]],
                    },
                    {
                        "text": "12",
                        "value": 12.0,
                        "type": "线性",
                        "definition_points": [[5, 12, 0], [17, 12, 0]],
                    },
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
                    {
                        "text": "30",
                        "value": 30.0,
                        "type": "线性",
                        "definition_points": [[0, 10, 0], [30, 10, 0]],
                    },
                    {
                        "text": "12",
                        "value": 12.0,
                        "type": "线性",
                        "definition_points": [[5, 12, 0], [17, 12, 0]],
                    },
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

    def test_reconstruction_pipeline_passes_conflicting_user_hint_to_llm_context(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.config = {}
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "profile",
                    "confidence": 0.9,
                    "summary": "profile",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
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
            generate=unittest.mock.Mock(
                return_value={"freecad_script": "pass", "warnings": []}
            )
        )
        pipeline.modeling_path_registry = unittest.mock.Mock()
        pipeline.modeling_path_registry.choose.return_value = {
            "modeling_path": "semantic_reconstruction"
        }
        pipeline.modeling_path_registry.build_routed_modeling_result.return_value = None

        pending_context = {
            "reconstruction_context": {
                "context_version": "reconstruction_context_v1",
                "dimensions": [{"text": "30", "value": 30.0}],
                "view_analysis": {"views": []},
            },
            "geometry_data": {"entities": []},
            "view_analysis": {"views": []},
            "dimension_data": {"dimensions": [{"text": "30", "value": 30.0}]},
            "extrude_height": 10.0,
        }

        resumed = pipeline.continue_with_clarification(
            pending_context,
            {"user_modeling_hint": "不用管图纸尺寸，以我说的为准。"},
        )

        self.assertEqual([], resumed["semantic_policy"]["clarification_questions"])
        call_kwargs = pipeline.instruction_generator.generate.call_args.kwargs
        self.assertEqual(
            "不用管图纸尺寸，以我说的为准。",
            call_kwargs["modeling_task_payload"]["recovery_hints"]["user_modeling_hint"],
        )
        self.assertNotIn("source_entities", repr(call_kwargs["modeling_task_payload"]))

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
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
                        "extrusion_depth": 10.0,
                        "cut_features": [],
                        "dimension_bindings": [],
                        "uncertainties": [],
                    },
                    "revolve_modeling_semantics": None,
                    "preferred_modeling_path": "planar_extrude",
                    "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
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

    def test_reconstruction_pipeline_does_not_block_on_unbound_additive_feature_dimension(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.config = {}
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "base",
                    "confidence": 0.9,
                    "summary": "base with possible boss",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                    "dimension_source": "annotation",
                    "base_features": [{"kind": "plate"}],
                    "additive_features": [
                        {"kind": "boss", "description": "右视图中的凸台"}
                    ],
                    "subtractive_features": [],
                    "planar_modeling_semantics": {
                        "profile": {"kind": "plate", "description": "base"},
                        "extrusion_direction": "Z",
                        "extrusion_depth": 8.0,
                        "cut_features": [],
                        "dimension_bindings": [],
                        "uncertainties": [],
                    },
                    "revolve_modeling_semantics": None,
                    "preferred_modeling_path": None,
                    "key_dimensions": [],
                    "uncertainties": ["凸台高度可能对应未绑定尺寸40"],
                    "warnings": [],
                }
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.modeling_path_registry = unittest.mock.Mock()
        pipeline.modeling_path_registry.choose.return_value = {
            "modeling_path": "semantic_reconstruction"
        }
        pipeline.modeling_path_registry.build_routed_modeling_result.return_value = None
        pipeline.instruction_generator.generate.return_value = {
            "freecad_script": "pass",
            "warnings": [],
        }

        result = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": [{"name": "main", "bbox": [0, 0, 100, 100]}]},
            dimension_data={"dimensions": [{"text": "40", "value": 40.0, "type": "线性"}]},
            local_relationships=None,
            extrude_height=10.0,
        )

        questions = result["semantic_policy"]["clarification_questions"]
        self.assertEqual([], questions)
        self.assertFalse(result["modeling_instructions"].get("blocked_by_clarification", False))
        pipeline.instruction_generator.generate.assert_called_once()

    def test_reconstruction_pipeline_blocks_critical_missing_additive_geometry_before_modeling(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.config = {}
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "bracket",
                    "confidence": 0.9,
                    "summary": "误判为带凸台零件",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                    "dimension_source": "annotation",
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [
                        {"kind": "boss", "description": "中心圆被解释为凸台"}
                    ],
                    "subtractive_features": [],
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "base"},
                        "extrusion_direction": "Z",
                        "extrusion_depth": None,
                        "cut_features": [],
                        "dimension_bindings": [],
                        "uncertainties": [
                            "Extrusion depth not specified by any annotation",
                            "Boss center location relative to profile not dimensioned",
                        ],
                    },
                    "revolve_modeling_semantics": None,
                    "preferred_modeling_path": "planar_extrude",
                    "key_dimensions": [{"name": "boss_diameter", "value": 70.0}],
                    "uncertainties": [
                        "Extrusion depth missing",
                        "Boss height missing",
                    ],
                    "warnings": [
                        "Modeling will require assumptions for missing depth and boss height"
                    ],
                }
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.modeling_path_registry = unittest.mock.Mock()

        result = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={
                "drawing_type": "three_view",
                "views": [
                    {"name": "main", "bbox": [0, 100, 100, 150]},
                    {"name": "bottom", "bbox": [0, 0, 100, 100]},
                    {"name": "right", "bbox": [150, 100, 250, 150]},
                ],
            },
            dimension_data={"dimensions": [{"text": "⌀70", "value": 70.0, "type": "直径"}]},
            local_relationships=None,
            extrude_height=10.0,
        )

        questions = result["semantic_policy"]["clarification_questions"]
        self.assertEqual("user_modeling_hint", questions[0]["id"])
        self.assertIn("孔/通孔", questions[0]["text"])
        self.assertTrue(result["modeling_instructions"]["blocked_by_clarification"])
        pipeline.modeling_path_registry.choose.assert_not_called()
        pipeline.instruction_generator.generate.assert_not_called()

    def test_feature_detail_clarification_skips_when_user_modeling_hint_exists(self):
        questions = SemanticReconstructionPipeline._build_feature_detail_clarification_questions(
            part_semantics={
                "additive_features": [
                    {"kind": "boss", "description": "right-view boss"}
                ]
            },
            policy_result={
                "adjudicated_context": {
                    "semantic_policy": {
                        "user_modeling_hint": "40 is the boss height"
                    }
                },
                "dimension_plan": {
                    "unresolved_dimensions": [
                        {"text": "40", "value": 40.0}
                    ]
                },
            },
        )

        self.assertEqual([], questions)

    def test_reconstruction_pipeline_waits_for_path_contract_clarification(self):
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
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
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

        self.assertTrue(result["modeling_instructions"]["blocked_by_path_contract"])
        self.assertEqual(
            "provide_extrusion_depth",
            result["modeling_instructions"]["clarification_questions"][0]["id"],
        )
        pipeline.instruction_generator.generate.assert_not_called()

    def test_reconstruction_pipeline_continues_after_path_depth_clarification(self):
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
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
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
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.config = {}

        pending = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": []},
            local_relationships=None,
            extrude_height=10.0,
        )
        resumed = pipeline.continue_with_clarification(
            pending["clarification_context"],
            {"provide_extrusion_depth": "12"},
        )

        self.assertEqual("planar_extrude", resumed["modeling_path_decision"]["modeling_path"])
        self.assertTrue(resumed["modeling_instructions"]["routed_to_planar_extrude"])
        pipeline.semantic_generator.generate.assert_called_once()
        pipeline.instruction_generator.generate.assert_not_called()

    def test_path_clarification_hint_falls_back_to_semantic_reconstruction(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.config = {}
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
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
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
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={"freecad_script": "pass", "warnings": []}
            )
        )

        pending = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": []},
            local_relationships=None,
            extrude_height=10.0,
        )
        resumed = pipeline.continue_with_clarification(
            pending["clarification_context"],
            {"user_modeling_hint": "主体先按外轮廓建出来，厚度不确定可以保守处理。"},
        )

        self.assertEqual(
            "semantic_reconstruction",
            resumed["modeling_path_decision"]["modeling_path"],
        )
        self.assertTrue(resumed["modeling_path_decision"]["fallback_from_path_clarification"])
        self.assertFalse(resumed["modeling_instructions"].get("blocked_by_clarification", False))
        pipeline.instruction_generator.generate.assert_called_once()
        call_kwargs = pipeline.instruction_generator.generate.call_args.kwargs
        fallback_context = call_kwargs["modeling_task_payload"]["recovery_hints"]["path_clarification_fallback"]
        self.assertEqual(["extrusion_depth"], fallback_context["missing_fields"])
        self.assertEqual("planar_extrude", fallback_context["original_modeling_path"])
        self.assertIn("用户已提供补充建模提示", fallback_context["reason"])

    def test_reconstruction_pipeline_waits_for_path_preference(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "profile",
                    "confidence": 0.9,
                    "summary": "ambiguous profile",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                    "dimension_source": "geometry",
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [],
                    "subtractive_features": [],
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
                        "extrusion_depth": 10.0,
                        "cut_features": [],
                        "dimension_bindings": [],
                        "uncertainties": [],
                    },
                    "revolve_modeling_semantics": {
                        "axis_point": [0, 0, 0],
                        "axis_direction": [0, 0, 1],
                        "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                        "angle_degrees": 360.0,
                        "uncertainties": [],
                    },
                    "preferred_modeling_path": None,
                    "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
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

        self.assertTrue(result["modeling_instructions"]["blocked_by_path_contract"])
        self.assertTrue(result["modeling_path_decision"]["requires_path_preference"])
        self.assertEqual(
            "select_modeling_path",
            result["modeling_instructions"]["clarification_questions"][0]["id"],
        )
        pipeline.instruction_generator.generate.assert_not_called()

    def test_reconstruction_pipeline_continues_after_path_preference(self):
        pipeline = SemanticReconstructionPipeline.__new__(SemanticReconstructionPipeline)
        pipeline.context_builder = ReconstructionContextBuilder()
        pipeline.semantic_policy = SemanticPolicy()
        pipeline.stage_confirmation = resolve_stage_confirmation({})
        pipeline.semantic_generator = unittest.mock.Mock(
            generate=unittest.mock.Mock(
                return_value={
                    "part_type": "profile",
                    "confidence": 0.9,
                    "summary": "ambiguous profile",
                    "evidence": [],
                    "candidate_interpretations": [],
                    "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                    "dimension_source": "geometry",
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [],
                    "subtractive_features": [],
                    "planar_modeling_semantics": {
                        "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                        "extrusion_direction": "Z",
                        "extrusion_depth": 10.0,
                        "cut_features": [],
                        "dimension_bindings": [],
                        "uncertainties": [],
                    },
                    "revolve_modeling_semantics": {
                        "axis_point": [0, 0, 0],
                        "axis_direction": [0, 0, 1],
                        "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                        "angle_degrees": 360.0,
                        "uncertainties": [],
                    },
                    "preferred_modeling_path": None,
                    "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
                    "uncertainties": [],
                    "warnings": [],
                }
            )
        )
        pipeline.instruction_generator = unittest.mock.Mock()
        pipeline.config = {}

        pending = pipeline.run(
            geometry_data={"entities": []},
            view_analysis={"drawing_type": "single_view", "views": []},
            dimension_data={"dimensions": []},
            local_relationships=None,
            extrude_height=10.0,
        )
        resumed = pipeline.continue_with_clarification(
            pending["clarification_context"],
            {"select_modeling_path": "revolve"},
        )

        self.assertEqual("revolve", resumed["modeling_path_decision"]["modeling_path"])
        self.assertTrue(resumed["modeling_instructions"]["routed_to_revolve"])
        pipeline.semantic_generator.generate.assert_called_once()
        pipeline.instruction_generator.generate.assert_not_called()

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



if __name__ == "__main__":
    unittest.main()
