# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.path_contracts import (
    evaluate_planar_extrude_contract,
    evaluate_revolve_contract,
)


class TestPathContracts(unittest.TestCase):
    def test_planar_contract_reports_missing_depth_before_routing(self):
        contract = evaluate_planar_extrude_contract(
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

        self.assertFalse(contract["eligible"])
        self.assertIn("extrusion_depth", contract["missing_fields"])

    def test_revolve_contract_can_be_recognized_when_semantics_are_closed(self):
        contract = evaluate_revolve_contract(
            {"drawing_type": "single_view"},
            {
                "revolve_modeling_semantics": {
                    "axis_point": [0, 0, 0],
                    "axis_direction": [0, 0, 1],
                    "profile_points": [[1, 0, 0], [1, 0, 2], [0, 0, 2], [1, 0, 0]],
                    "angle_degrees": 360.0,
                    "uncertainties": [],
                }
            },
        )

        self.assertTrue(contract["eligible"])
        self.assertTrue(contract["implemented"])
