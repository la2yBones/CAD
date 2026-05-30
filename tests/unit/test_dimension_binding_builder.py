# -*- coding: utf-8 -*-

import unittest

from src.reconstruction.dimension_binding_builder import DimensionBindingBuilder


class TestDimensionBindingBuilder(unittest.TestCase):
    def test_binds_textually_explicit_dimensions(self):
        bindings = DimensionBindingBuilder().build(
            [
                {"text": "R15", "value": 15.0, "type": "半径"},
                {"text": "⌀10", "value": 10.0, "type": "直径"},
                {"text": "M8", "value": 8.0, "type": "螺纹"},
                {"text": "1x45%%d", "value": 1.0, "type": "线性"},
                {"text": "30", "value": 30.0, "type": "线性"},
            ],
            {"view_analysis": {"views": []}},
        )

        by_text = {item["text"]: item for item in bindings}
        self.assertEqual("radius", by_text["R15"]["semantic_role"])
        self.assertEqual("diameter", by_text["⌀10"]["semantic_role"])
        self.assertEqual("thread_size", by_text["M8"]["semantic_role"])
        self.assertEqual("chamfer", by_text["1x45%%d"]["semantic_role"])
        self.assertEqual("unresolved_linear", by_text["30"]["semantic_role"])

    def test_marks_linear_geometry_inference_as_candidate(self):
        bindings = DimensionBindingBuilder().build(
            [
                {
                    "text": "30",
                    "value": 30.0,
                    "type": "线性",
                    "position": [20, 10, 0],
                    "associated_lines": [
                        {"line": {"start": [0, 10, 0], "end": [40, 10, 0]}}
                    ],
                }
            ],
            {
                "view_analysis": {
                    "views": [{"name": "main", "bbox": [0, 0, 40, 40]}]
                }
            },
        )

        self.assertEqual("profile_length", bindings[0]["semantic_role"])
        self.assertEqual("candidate", bindings[0]["binding_status"])
        self.assertEqual("legacy_linear_geometry_candidate", bindings[0]["source"])

    def test_preserves_repeated_dimension_metadata(self):
        bindings = DimensionBindingBuilder().build(
            [
                {
                    "text": "3xφ5",
                    "value": 5.0,
                    "type": "直径",
                    "callout": "repeated_diameter",
                    "repeat_count": 3,
                    "diameter_value": 5.0,
                }
            ],
            {"view_analysis": {"views": []}},
        )

        binding = bindings[0]
        self.assertEqual("diameter", binding["semantic_role"])
        self.assertEqual("repeated_diameter", binding["callout"])
        self.assertEqual(3, binding["repeat_count"])
        self.assertEqual(5.0, binding["diameter_value"])

    def test_applies_dimension_chain_candidates(self):
        bindings = DimensionBindingBuilder().build(
            [
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
            ],
            {
                "view_analysis": {
                    "drawing_type": "two_view",
                    "views": [{"name": "main", "bbox": [0, 0, 50, 30]}],
                }
            },
        )

        by_text = {item["text"]: item for item in bindings}
        self.assertEqual("profile_length", by_text["9+39"]["semantic_role"])
        self.assertEqual("profile_length_segment", by_text["9"]["semantic_role"])
        self.assertEqual("profile_length_segment", by_text["39"]["semantic_role"])
        self.assertEqual("candidate", by_text["9+39"]["binding_status"])


if __name__ == "__main__":
    unittest.main()
