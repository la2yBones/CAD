# -*- coding: utf-8 -*-

import unittest

from src.intelligent_analyzer.dimension_extractor import DimensionExtractor


class TestDimensionExtractor(unittest.TestCase):
    def test_dimension_extractor_preserves_dimension_entity_definition_points(self):
        result = DimensionExtractor().extract_dimensions(
            {
                "entities": [
                    {
                        "type": "DIMENSION",
                        "rendered_text": "30",
                        "text_position": [5, 5, 0],
                        "definition_points": [[0, 0, 0], [30, 0, 0]],
                        "measurement": 30.0,
                        "dimension_type": 0,
                    }
                ]
            }
        )

        dimension = result["dimensions"][0]
        self.assertEqual([[0, 0, 0], [30, 0, 0]], dimension["definition_points"])
        self.assertEqual(30.0, dimension["measurement"])

    def test_dimension_extractor_parses_repeated_radius_callout(self):
        result = DimensionExtractor().extract_dimensions(
            {
                "entities": [
                    {
                        "type": "TEXT",
                        "text": "R=4x1.5",
                        "position": [10, 10, 0],
                    }
                ]
            }
        )

        dimension = result["dimensions"][0]
        self.assertEqual("半径", dimension["type"])
        self.assertEqual(1.5, dimension["value"])
        self.assertEqual("repeated_radius", dimension["callout"])
        self.assertEqual(4, dimension["repeat_count"])
        self.assertEqual(1.5, dimension["radius_value"])

    def test_dimension_extractor_parses_repeated_diameter_callout(self):
        result = DimensionExtractor().extract_dimensions(
            {
                "entities": [
                    {
                        "type": "TEXT",
                        "text": "3xφ5",
                        "position": [10, 10, 0],
                    }
                ]
            }
        )

        dimension = result["dimensions"][0]
        self.assertEqual("直径", dimension["type"])
        self.assertEqual(5.0, dimension["value"])
        self.assertEqual("repeated_diameter", dimension["callout"])
        self.assertEqual(3, dimension["repeat_count"])
        self.assertEqual(5.0, dimension["diameter_value"])

    def test_dimension_extractor_parses_repeated_thread_callout(self):
        result = DimensionExtractor().extract_dimensions(
            {
                "entities": [
                    {
                        "type": "TEXT",
                        "text": "3-M5",
                        "position": [10, 10, 0],
                    }
                ]
            }
        )

        dimension = result["dimensions"][0]
        self.assertEqual("螺纹", dimension["type"])
        self.assertEqual(5.0, dimension["value"])
        self.assertEqual("repeated_thread", dimension["callout"])
        self.assertEqual(3, dimension["repeat_count"])
        self.assertEqual(5.0, dimension["thread_value"])



if __name__ == "__main__":
    unittest.main()
