# -*- coding: utf-8 -*-

import unittest

from src.reconstruction.modeling_constraints import (
    DEFAULT_MODELING_CONSTRAINTS,
    ModelingConstraints,
)


class TestModelingConstraints(unittest.TestCase):
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

    def test_constraints_prompt_requires_edge_compatibility_helper(self):
        prompt = DEFAULT_MODELING_CONSTRAINTS.prompt_section()

        self.assertIn("as_edge(obj)", prompt)
        self.assertIn('hasattr(obj, "toShape")', prompt)

    def test_constraints_prompt_prefers_semantic_adjudication(self):
        prompt = DEFAULT_MODELING_CONSTRAINTS.prompt_section()

        self.assertIn("dimensions.semantic_adjudication", prompt)

    def test_retry_reason_ignores_legacy_radius_when_adjudication_succeeds(self):
        retry_reason = ModelingConstraints().retry_reason(
            {
                "analysis_summary": "圆角未实现",
                "modeling_strategy": "",
                "freecad_script": "",
                "warnings": [],
            },
            {
                "semantic_policy": {
                    "semantic_adjudication": {
                        "status": "completed",
                        "dimension_roles": [],
                        "derived_dimensions": [],
                    },
                    "dimension_plan": {
                        "allowed_dimensions": [
                            {"role": "radius", "value": 4.0},
                        ],
                    },
                },
            },
            {"part_type": "plate"},
        )

        self.assertEqual("", retry_reason)

    def test_retry_reason_uses_adjudicated_feature_roles(self):
        retry_reason = ModelingConstraints().retry_reason(
            {
                "analysis_summary": "R15圆弧面跳过",
                "modeling_strategy": "",
                "freecad_script": "",
                "warnings": [],
            },
            {
                "semantic_policy": {
                    "semantic_adjudication": {
                        "status": "completed",
                        "dimension_roles": [],
                        "derived_dimensions": [],
                        "feature_roles": [
                            {
                                "feature_id": "G1",
                                "role": "radius",
                                "evidence_ids": ["G1"],
                            }
                        ],
                    },
                },
            },
            {"part_type": "bolt"},
        )

        self.assertEqual("radius_surface", retry_reason)


if __name__ == "__main__":
    unittest.main()
