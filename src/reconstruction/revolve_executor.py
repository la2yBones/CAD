#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build deterministic FreeCAD scripts for constrained revolve semantics."""
from __future__ import annotations

from typing import Any, Dict, List


def build_revolve_script(semantics: Dict[str, Any]) -> str:
    """Return a deterministic revolve script for a closed polyline profile."""
    axis_point = semantics["axis_point"]
    axis_direction = semantics["axis_direction"]
    profile_points = semantics["profile_points"]
    angle_degrees = semantics["angle_degrees"]

    point_lines = [
        f"    FreeCAD.Vector({point[0]}, {point[1]}, {point[2]}),"
        for point in profile_points
    ]
    profile_block = "\n".join(point_lines)
    return f"""import FreeCAD
import Part

doc = FreeCAD.newDocument("RevolveModel")
points = [
{profile_block}
]
edges = []
for index in range(len(points) - 1):
    edges.append(Part.LineSegment(points[index], points[index + 1]).toShape())
wire = Part.Wire(edges)
face = Part.Face(wire)
axis_point = FreeCAD.Vector({axis_point[0]}, {axis_point[1]}, {axis_point[2]})
axis_direction = FreeCAD.Vector({axis_direction[0]}, {axis_direction[1]}, {axis_direction[2]})
shape = face.revolve(axis_point, axis_direction, {angle_degrees})
Part.show(shape, "FinalModel")
doc.recompute()
"""
