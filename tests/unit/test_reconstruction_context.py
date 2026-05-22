# -*- coding: utf-8 -*-

import unittest

from src.intelligent_analyzer.reconstruction_context import ReconstructionContextBuilder


class TestReconstructionContext(unittest.TestCase):
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

    def test_reconstruction_context_keeps_geometry_summary_for_compressed_payloads(self):
        context = ReconstructionContextBuilder().build(
            {
                "entities": [
                    {"type": "ARC", "layer": "轮廓线", "center": [0, 0, 0], "radius": 1.5},
                    {"type": "ARC", "layer": "轮廓线", "center": [1, 0, 0], "radius": 1.5},
                ],
            },
            {"views": []},
            {"dimensions": []},
        )

        self.assertEqual(2, context["geometry_summary"]["arc_summary"]["count"])
        self.assertEqual([1.5], context["geometry_summary"]["arc_summary"]["radius_values"])


if __name__ == "__main__":
    unittest.main()
