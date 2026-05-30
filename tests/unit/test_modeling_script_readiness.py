# -*- coding: utf-8 -*-

import unittest

from src.reconstruction.modeling_script_readiness import ModelingScriptReadinessChecker


VALID_SCRIPT = """
import FreeCAD
import Part

doc = FreeCAD.newDocument("GeneratedModel")
p1 = FreeCAD.Vector(0, 0, 0)
p2 = FreeCAD.Vector(10, 0, 0)
p3 = FreeCAD.Vector(10, 10, 0)
p4 = FreeCAD.Vector(0, 10, 0)
edges = [
    Part.LineSegment(p1, p2).toShape(),
    Part.LineSegment(p2, p3).toShape(),
    Part.LineSegment(p3, p4).toShape(),
    Part.LineSegment(p4, p1).toShape(),
]
wire = Part.Wire(edges)
if not wire.isClosed():
    raise ValueError("profile not closed")
face = Part.Face(wire)
final_shape = face.extrude(FreeCAD.Vector(0, 0, 5))
Part.show(final_shape, "GeneratedModel")
doc.recompute()
"""


class TestModelingScriptReadinessChecker(unittest.TestCase):
    def test_accepts_executable_script_shape(self):
        result = ModelingScriptReadinessChecker().check(VALID_SCRIPT)

        self.assertTrue(result.success, result.error)

    def test_rejects_missing_final_shape(self):
        script = VALID_SCRIPT.replace("final_shape = face.extrude", "solid = face.extrude")

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("缺少 final_shape 赋值", result.error)

    def test_rejects_missing_part_show_final_shape(self):
        script = VALID_SCRIPT.replace('Part.show(final_shape, "GeneratedModel")', "")

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("缺少 Part.show", result.error)

    def test_rejects_missing_recompute(self):
        script = VALID_SCRIPT.replace("doc.recompute()", "")

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("缺少 doc.recompute", result.error)

    def test_rejects_face_without_wire_closed_check(self):
        script = VALID_SCRIPT.replace(
            'if not wire.isClosed():\n    raise ValueError("profile not closed")\n',
            "",
        )

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("闭合检查", result.error)

    def test_rejects_raw_edge_constructor_inside_wire(self):
        script = VALID_SCRIPT.replace(
            "Part.LineSegment(p1, p2).toShape()",
            "Part.LineSegment(p1, p2)",
            1,
        )

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("必须先转换为 Edge/Shape", result.error)

    def test_rejects_wrong_arc_of_circle_arity(self):
        script = VALID_SCRIPT.replace(
            "Part.LineSegment(p1, p2).toShape()",
            "Part.ArcOfCircle(p1, 5, 0, 1.57).toShape()",
            1,
        )

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("Part.ArcOfCircle must use exactly 3 positional arguments", result.error)

    def test_rejects_json_usage_without_import(self):
        script = VALID_SCRIPT + "\nprint(json.dumps({}))\n"

        result = ModelingScriptReadinessChecker().check(script)

        self.assertFalse(result.success)
        self.assertIn("缺少 import json", result.error)


if __name__ == "__main__":
    unittest.main()
