# -*- coding: utf-8 -*-
import unittest
import unittest.mock

from src.intelligent_analyzer.pipeline import IntelligentEngineeringAnalyzer
from src.intelligent_analyzer.llm_view_analyzer import LLMViewAnalyzer
from src.intelligent_analyzer.view_schema import ViewAnalysisValidator
from src.utils.stage_confirmation import (
    StageConfirmationResult,
    StageConfirmationStopped,
)


class TestIntelligentAnalyzerStageRetry(unittest.TestCase):
    def test_view_schema_list_fields_accept_llm_string_values(self):
        analyzer = LLMViewAnalyzer.__new__(LLMViewAnalyzer)

        normalized = analyzer._normalize_view_schema_lists({
            "evidence": "两个视图区域水平对齐",
            "warnings": "需要人工复核",
        })

        self.assertEqual(["两个视图区域水平对齐"], normalized["evidence"])
        self.assertEqual(["需要人工复核"], normalized["warnings"])

    def test_view_auto_self_correction_builds_payload_with_rule_standard(self):
        analyzer = LLMViewAnalyzer.__new__(LLMViewAnalyzer)
        analyzer.validator = ViewAnalysisValidator(confidence_threshold=0.6)
        analyzer.confidence_threshold = 0.6
        analyzer.generate_from_self_correction = unittest.mock.Mock(return_value={
            "analysis_id": "view_test",
            "timestamp": "2026-05-30T10:49:14+00:00",
            "drawing_type": "single_view",
            "views": [
                {
                    "object_id": "view_1",
                    "name": "single",
                    "label": "single",
                    "bbox": [0.0, 0.0, 10.0, 10.0],
                    "confidence": 0.9,
                }
            ],
            "relationships": [],
            "confidence": 0.9,
            "evidence": ["已修正为数组"],
            "reason_summary": "自纠成功",
            "warnings": [],
        })

        result = analyzer._auto_self_correct(
            llm_result={"evidence": "字符串证据"},
            geometry_data={
                "entities": [
                    {"type": "LINE", "start": [0, 0], "end": [10, 0]},
                    {"type": "LINE", "start": [10, 0], "end": [10, 10]},
                    {"type": "LINE", "start": [10, 10], "end": [0, 10]},
                    {"type": "LINE", "start": [0, 10], "end": [0, 0]},
                ]
            },
            rule_result={
                "detection_method": "projection_split",
                "views": [
                    {
                        "name": "single",
                        "type": "single",
                        "bbox": [0, 0, 10, 10],
                        "confidence": 0.72,
                    }
                ],
                "relationships": [],
            },
            rule_standard={
                "drawing_type": "single_view",
                "confidence": 0.72,
                "views": [],
                "relationships": [],
                "warnings": [],
            },
            dimension_data={"dimensions": []},
            file_path="底座二视图.dxf",
            validation_errors=["JSON Schema校验失败: evidence: 'x' is not of type 'array'"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(1, analyzer.generate_from_self_correction.call_count)
        request = analyzer.generate_from_self_correction.call_args.args[0]
        self.assertIn("local_rule_summary", request.stage_payload)

    def test_view_retry_action_regenerates_view_analysis_before_reconstruction(self):
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.cache = None
        analyzer.view_analyzer = unittest.mock.Mock()
        analyzer.view_analyzer.analyze_views.return_value = {
            "drawing_type": "single_view",
            "views": [],
        }
        analyzer.dimension_extractor = unittest.mock.Mock()
        analyzer.dimension_extractor.extract_dimensions.return_value = {"dimensions": []}
        analyzer.llm_view_analyzer = unittest.mock.Mock()
        analyzer.llm_view_analyzer.refine_view_analysis.side_effect = [
            {"drawing_type": "single_view", "views": [], "confidence": 0.7},
            {"drawing_type": "two_view", "views": [{"name": "main"}], "confidence": 0.9},
        ]
        analyzer.reconstruction_pipeline = unittest.mock.Mock()
        analyzer.reconstruction_pipeline.run.side_effect = [
            StageConfirmationStopped(
                StageConfirmationResult.retry_stage(stage="view_analysis")
            ),
            {
                "part_semantics": {"part_type": "plate"},
                "modeling_instructions": {"freecad_script": "script"},
            },
        ]
        analyzer._analyze_local_fallback = unittest.mock.Mock(return_value=None)

        result = analyzer.analyze_full(
            geometry_data={"entities": []},
            extrude_height=10.0,
            file_path="plate.dxf",
        )

        self.assertEqual(2, analyzer.llm_view_analyzer.refine_view_analysis.call_count)
        self.assertEqual(2, analyzer.reconstruction_pipeline.run.call_count)
        self.assertEqual("two_view", result["view_analysis"]["drawing_type"])
        self.assertTrue(result["view_analysis"]["stage_retry_applied"])
        self.assertEqual(
            "user_requested_retry_stage",
            result["view_analysis"]["stage_retry_log"][0]["trigger"],
        )

    def test_view_self_correction_action_regenerates_view_analysis_before_reconstruction(self):
        analyzer = IntelligentEngineeringAnalyzer.__new__(IntelligentEngineeringAnalyzer)
        analyzer.cache = None
        analyzer.view_analyzer = unittest.mock.Mock()
        analyzer.view_analyzer.analyze_views.return_value = {
            "detection_method": "projection_split",
            "drawing_type": "single_view",
            "views": [{"name": "single", "type": "单视图", "bbox": [0, 0, 10, 10]}],
            "relationships": [],
        }
        analyzer.dimension_extractor = unittest.mock.Mock()
        analyzer.dimension_extractor.extract_dimensions.return_value = {"dimensions": []}
        analyzer.llm_view_analyzer = unittest.mock.Mock()
        analyzer.llm_view_analyzer.confidence_threshold = 0.6
        analyzer.llm_view_analyzer.refine_view_analysis.return_value = {
            "drawing_type": "single_view",
            "views": [{"name": "single"}],
            "confidence": 0.7,
        }
        analyzer.llm_view_analyzer.generate_from_self_correction.return_value = {
            "drawing_type": "two_view",
            "views": [{"name": "main"}, {"name": "top"}],
            "confidence": 0.88,
        }
        analyzer.reconstruction_pipeline = unittest.mock.Mock()
        analyzer.reconstruction_pipeline.run.side_effect = [
            StageConfirmationStopped(
                StageConfirmationResult.self_correct(stage="view_analysis")
            ),
            {
                "part_semantics": {"part_type": "plate"},
                "modeling_instructions": {"freecad_script": "script"},
            },
        ]
        analyzer._analyze_local_fallback = unittest.mock.Mock(return_value=None)

        result = analyzer.analyze_full(
            geometry_data={
                "entities": [
                    {"type": "LINE", "start": [0, 0], "end": [10, 0]},
                ]
            },
            extrude_height=10.0,
            file_path="plate.dxf",
        )

        self.assertEqual(1, analyzer.llm_view_analyzer.generate_from_self_correction.call_count)
        request = analyzer.llm_view_analyzer.generate_from_self_correction.call_args.args[0]
        self.assertEqual("view_analysis", request.stage)
        self.assertIn("candidate_views", request.stage_payload)
        self.assertNotIn("entities", request.stage_payload["candidate_views"][0])
        self.assertEqual("two_view", result["view_analysis"]["drawing_type"])
        self.assertTrue(result["view_analysis"]["self_correction_applied"])
        self.assertEqual(
            "user_requested_view_self_correction",
            result["view_analysis"]["self_correction_log"][0]["trigger"],
        )


if __name__ == "__main__":
    unittest.main()
