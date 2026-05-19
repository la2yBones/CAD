# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.revolve_executor import build_revolve_script


class TestRevolveExecutor(unittest.TestCase):
    def test_builds_deterministic_script(self):
        script = build_revolve_script({
            "axis_point": [0, 0, 0],
            "axis_direction": [0, 0, 1],
            "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
            "angle_degrees": 360.0,
        })

        self.assertIn("face.revolve(axis_point, axis_direction, 360.0)", script)
        self.assertIn("Part.LineSegment", script)
