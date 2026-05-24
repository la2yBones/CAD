# -*- coding: utf-8 -*-

import json
import unittest

from src.reconstruction.drawing_evidence import DrawingEvidencePackageBuilder
from src.reconstruction.semantic_payload import SemanticUnderstandingPayloadBuilder
from src.reconstruction.semantic_policy import SemanticPolicy


def _sample_context():
    return {
        "context_version": "reconstruction_context_v1",
        "drawing": {"entity_count": 4, "entity_type_count": {"LINE": 2, "CIRCLE": 2}},
        "view_analysis": {
            "drawing_type": "two_view",
            "views": [
                {
                    "name": "top",
                    "label": "俯视图",
                    "bbox": [0, 40, 100, 120],
                    "centroid": [50, 80, 0],
                    "entity_count": 2,
                    "entity_type_count": {"CIRCLE": 2},
                    "entities": [{"type": "CIRCLE", "center": [50, 80, 0], "radius": 10}],
                },
                {
                    "name": "main",
                    "label": "主视图",
                    "bbox": [0, 0, 100, 20],
                    "centroid": [50, 10, 0],
                    "entity_count": 2,
                    "entity_type_count": {"LINE": 2},
                    "entities": [{"type": "LINE", "start": [0, 0, 0], "end": [100, 0, 0]}],
                },
            ],
            "relationships": [],
        },
        "dimensions": [
            {
                "text": "20",
                "value": 20.0,
                "type": "线性",
                "position": [20, 10, 0],
                "definition_points": [[20, 0, 0], [20, 20, 0]],
            },
            {
                "text": "16",
                "value": 16.0,
                "type": "线性",
                "position": [10, 8, 0],
                "definition_points": [[10, 2, 0], [10, 18, 0]],
            },
            {
                "text": "6xφ4",
                "value": 4.0,
                "type": "直径",
                "position": [50, 80, 0],
                "repeat_count": 6,
                "diameter_value": 4.0,
            },
        ],
        "source_entities": [
            {"type": "CIRCLE", "center": [50, 80, 0], "radius": 10, "layer": "0"},
            {"type": "CIRCLE", "center": [50, 80, 0], "radius": 20, "layer": "0"},
            {"type": "LINE", "start": [0, 0, 0], "end": [100, 0, 0], "layer": "0"},
        ],
    }


class TestDrawingEvidencePackageBuilder(unittest.TestCase):
    def test_evidence_package_ids_are_stable(self):
        builder = DrawingEvidencePackageBuilder()

        first = builder.build(_sample_context())
        second = builder.build(_sample_context())

        self.assertEqual(first, second)
        self.assertEqual(["V1", "V2"], [item["id"] for item in first["view_candidates"]])
        self.assertEqual(
            ["D1", "D2", "D3"],
            [item["id"] for item in first["dimension_candidates"]],
        )
        self.assertEqual(
            ["G1", "G2", "G3"],
            [item["id"] for item in first["geometry_candidates"]],
        )

    def test_evidence_package_does_not_contain_final_semantic_roles(self):
        package = DrawingEvidencePackageBuilder().build(_sample_context())
        encoded = json.dumps(package, ensure_ascii=False)

        self.assertNotIn("semantic_role", encoded)
        self.assertNotIn('"role"', encoded)
        self.assertNotIn("profile_length", encoded)
        self.assertNotIn("extrusion_depth", encoded)
        self.assertNotIn("thread_length", encoded)
        self.assertNotIn("feature_height", encoded)

        views = {item["id"]: item for item in package["view_candidates"]}
        self.assertEqual("main", views["V1"]["local_name_hint"])
        self.assertEqual("top", views["V2"]["local_name_hint"])

    def test_derived_dimensions_keep_formula_and_source_ids_only(self):
        package = DrawingEvidencePackageBuilder().build(_sample_context())

        derived = [
            item for item in package["derived_dimension_candidates"]
            if item["candidate_kind"] == "difference"
            and item["source_dimension_ids"] == ["D2", "D1"]
        ]

        self.assertEqual(1, len(derived))
        self.assertEqual(4.0, derived[0]["value"])
        self.assertEqual("D2 - D1", derived[0]["formula"])
        self.assertNotIn("role", derived[0])

    def test_evidence_package_omits_raw_entity_lists(self):
        package = DrawingEvidencePackageBuilder().build(_sample_context())
        encoded = json.dumps(package, ensure_ascii=False)

        self.assertNotIn("source_entities", encoded)
        self.assertNotIn('"entities"', encoded)
        self.assertIn("geometry_candidates", package)

    def test_semantic_policy_and_payload_carry_evidence_package(self):
        policy_result = SemanticPolicy().evaluate(_sample_context())

        package = policy_result["drawing_evidence_package"]
        self.assertEqual("drawing_evidence_package_v1", package["package_version"])
        self.assertEqual(
            package,
            policy_result["adjudicated_context"]["semantic_policy"][
                "drawing_evidence_package"
            ],
        )

        payload = SemanticUnderstandingPayloadBuilder().build(
            policy_result["adjudicated_context"]
        )
        self.assertEqual(package, payload["drawing_evidence_package"])


if __name__ == "__main__":
    unittest.main()
