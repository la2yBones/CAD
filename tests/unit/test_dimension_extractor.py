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



if __name__ == "__main__":
    unittest.main()
