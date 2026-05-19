# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.modeling_path import (
    choose_modeling_path,
    default_modeling_path_registry,
)


class TestModelingPath(unittest.TestCase):
    def test_routes_simple_single_profile_to_planar_extrude(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
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
            },
        )

        self.assertEqual("planar_extrude", decision["modeling_path"])

    def test_does_not_derive_missing_planar_semantics(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
            },
        )

        self.assertEqual("semantic_reconstruction", decision["modeling_path"])
        self.assertNotIn("blocked_by_path_contract", decision)
        planar = next(item for item in decision["candidate_paths"] if item["path"] == "planar_extrude")
        self.assertIn("profile", planar["missing_fields"])
        self.assertIn("has_uncertainties", planar["rejection_reasons"])

    def test_keeps_complex_single_view_in_semantic_reconstruction(self):
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

    def test_blocks_for_clarification_when_planar_contract_is_incomplete(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
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
            },
        )

        self.assertTrue(decision["blocked_by_path_contract"])
        self.assertEqual("provide_extrusion_depth", decision["clarification_questions"][0]["id"])
        self.assertIn("厚度或拉伸深度", decision["clarification_questions"][0]["text"])
        self.assertIn("10mm", decision["clarification_questions"][0]["example"])

    def test_routes_to_revolve_when_contract_is_closed(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "cylinder"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XZ", "depth_axis": "unknown"},
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                    "uncertainties": [],
                },
            },
        )

        self.assertEqual("revolve", decision["modeling_path"])
        revolve = next(item for item in decision["candidate_paths"] if item["path"] == "revolve")
        self.assertTrue(revolve["eligible"])
        self.assertTrue(revolve["implemented"])

    def test_uses_preferred_path_when_multiple_candidates_are_closed(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                "planar_modeling_semantics": {
                    "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                    "extrusion_direction": "Z",
                    "extrusion_depth": 10.0,
                    "cut_features": [],
                    "dimension_bindings": [],
                    "uncertainties": [],
                },
                "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                    "uncertainties": [],
                },
                "preferred_modeling_path": "revolve",
            },
        )

        self.assertEqual("revolve", decision["modeling_path"])

    def test_requests_preference_when_multiple_candidates_are_closed(self):
        decision = choose_modeling_path(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                "planar_modeling_semantics": {
                    "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                    "extrusion_direction": "Z",
                    "extrusion_depth": 10.0,
                    "cut_features": [],
                    "dimension_bindings": [],
                    "uncertainties": [],
                },
                "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                    "uncertainties": [],
                },
                "preferred_modeling_path": None,
            },
        )

        self.assertEqual("semantic_reconstruction", decision["modeling_path"])
        self.assertTrue(decision["requires_path_preference"])
        self.assertEqual("select_modeling_path", decision["clarification_questions"][0]["id"])
        self.assertIn("更符合图纸意图", decision["clarification_questions"][0]["text"])
        self.assertIn("平面拉伸", decision["clarification_questions"][0]["example"])

    def test_registry_supplies_preference_labels(self):
        registry = default_modeling_path_registry()
        decision = registry.choose(
            {"drawing_type": "single_view"},
            {
                "base_features": [{"kind": "profile_extrusion"}],
                "additive_features": [],
                "uncertainties": [],
                "coordinate_system": {"profile_plane": "XY", "depth_axis": "Z"},
                "planar_modeling_semantics": {
                    "profile": {"kind": "profile_extrusion", "description": "simple profile"},
                    "extrusion_direction": "Z",
                    "extrusion_depth": 10.0,
                    "cut_features": [],
                    "dimension_bindings": [],
                    "uncertainties": [],
                },
                "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                    "uncertainties": [],
                },
                "preferred_modeling_path": None,
            },
        )

        question = decision["clarification_questions"][0]
        labels = {option["value"]: option["label"] for option in question["options"]}
        self.assertEqual(registry.label_for_path("planar_extrude"), labels["planar_extrude"])
        self.assertEqual(registry.label_for_path("revolve"), labels["revolve"])
        self.assertEqual("future_path", registry.label_for_path("future_path"))

    def test_registry_builds_routed_planar_result(self):
        registry = default_modeling_path_registry()
        result = registry.build_routed_modeling_result(
            {"modeling_path": "planar_extrude"},
            {
                "summary": "simple profile",
                "key_dimensions": [{"name": "thickness", "value": 10.0, "unit": "mm"}],
            },
        )

        self.assertTrue(result["routed_to_planar_extrude"])
        self.assertEqual(
            [{"name": "thickness", "value": 10.0, "unit": "mm"}],
            result["key_dimensions"],
        )

    def test_registry_builds_routed_revolve_result(self):
        registry = default_modeling_path_registry()
        result = registry.build_routed_modeling_result(
            {"modeling_path": "revolve"},
            {"summary": "axisymmetric part", "key_dimensions": []},
        )

        self.assertTrue(result["routed_to_revolve"])

    def test_registry_returns_none_for_semantic_reconstruction(self):
        registry = default_modeling_path_registry()

        self.assertIsNone(
            registry.build_routed_modeling_result(
                {"modeling_path": "semantic_reconstruction"},
                {"summary": "complex part"},
            )
        )
