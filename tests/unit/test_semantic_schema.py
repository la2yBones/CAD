# -*- coding: utf-8 -*-

import unittest

from src.intelligent_analyzer.semantic_schema import PartSemanticsValidator


class TestPartSemanticsValidator(unittest.TestCase):
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
                        "construction_dimensions": [
                            {"text": "9", "value": 9.0, "role": "profile_length_segment"},
                            {"text": "39", "value": 39.0, "role": "profile_length_segment"},
                        ],
                    },
                },
            },
        )

        self.assertTrue(valid)
        self.assertEqual([], errors)

    def test_part_semantics_validator_allows_adjudicated_construction_dimensions(self):
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
                    {"name": "head_length", "value": 9.0, "unit": "mm"},
                    {"name": "threaded_shank_length", "value": 39.0, "unit": "mm"},
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
                        "construction_dimensions": [
                            {"text": "9", "value": 9.0, "role": "profile_length_segment"},
                            {"text": "39", "value": 39.0, "role": "profile_length_segment"},
                        ],
                        "unresolved_dimensions": [
                            {"text": "30", "value": 30.0, "role": "unresolved_linear"}
                        ],
                    },
                },
            },
        )

        self.assertTrue(valid)
        self.assertEqual([], errors)

    def test_part_semantics_validator_rejects_misnamed_construction_dimensions(self):
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
                    {"name": "total_length", "value": 9.0, "unit": "mm"},
                ],
                "uncertainties": [],
                "warnings": [],
            },
            {
                "dimensions": [{"text": "9", "value": 9.0}],
                "semantic_policy": {
                    "dimension_source": "annotation",
                    "dimension_plan": {
                        "allowed_dimensions": [],
                        "construction_dimensions": [
                            {"text": "9", "value": 9.0, "role": "profile_length_segment"}
                        ],
                    },
                },
            },
        )

        self.assertFalse(valid)
        self.assertTrue(any("construction_dimensions" in error for error in errors))

    def test_part_semantics_validator_requires_planar_modeling_semantics(self):
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

        self.assertFalse(valid)
        self.assertIn("缺少字段: planar_modeling_semantics", errors)

    def test_part_semantics_validator_requires_revolve_modeling_semantics(self):
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
                "planar_modeling_semantics": {
                    "profile": None,
                    "extrusion_direction": "unknown",
                    "extrusion_depth": None,
                    "cut_features": [],
                    "dimension_bindings": [],
                    "uncertainties": [],
                },
                "preferred_modeling_path": None,
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertFalse(valid)
        self.assertIn("缺少字段: revolve_modeling_semantics", errors)

    def test_part_semantics_validator_rejects_incomplete_revolve_semantics(self):
        valid, errors = PartSemanticsValidator().validate(
            {
                "part_type": "shaft",
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
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                },
                "preferred_modeling_path": "revolve",
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertFalse(valid)
        self.assertIn("revolve_modeling_semantics 缺少字段: uncertainties", errors)

    def test_part_semantics_validator_rejects_invalid_preferred_modeling_path(self):
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
                "planar_modeling_semantics": {
                    "profile": None,
                    "extrusion_direction": "unknown",
                    "extrusion_depth": None,
                    "cut_features": [],
                    "dimension_bindings": [],
                    "uncertainties": [],
                },
                "revolve_modeling_semantics": None,
                "preferred_modeling_path": "magic",
                "key_dimensions": [],
                "uncertainties": [],
                "warnings": [],
            }
        )

        self.assertFalse(valid)
        self.assertTrue(any("preferred_modeling_path 必须是" in error for error in errors))



if __name__ == "__main__":
    unittest.main()
