# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from src.batch_processor.pipeline import CADPipeline
from src.batch_processor.processor import CADProcessor, CADProcessResult, PipelineStatus
from src.utils.stage_confirmation import CallbackStageConfirmation


class TestBatchProcessor(unittest.TestCase):
    def test_cad_process_result_supports_needs_clarification_status(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")
        result.mark_needs_clarification(
            [{"id": "bind_profile_length", "text": "请选择主视图总尺寸", "kind": "single_choice"}],
            {"marker": "keep"},
        )

        self.assertFalse(result.success)
        self.assertEqual(PipelineStatus.NEEDS_CLARIFICATION, result.status)
        self.assertEqual("needs_clarification", result.to_dict()["status"])
        self.assertEqual({"marker": "keep"}, result.clarification_context)

    def test_cad_process_result_serializes_mode_and_modeling_path(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )

        self.assertEqual("intelligent", result.to_dict()["mode"])
        self.assertEqual("semantic_reconstruction", result.to_dict()["modeling_path"])

    def test_cad_process_result_supports_partial_completed_status(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")

        result.mark_partial_completed(
            skipped_features=[
                {"name": "R2 fillet", "kind": "fillet", "reason": "not enough evidence"}
            ],
            completed_features=[{"name": "base body", "kind": "base"}],
            reason="主体可导出，圆角跳过",
        )

        data = result.to_dict()
        self.assertTrue(result.success)
        self.assertEqual(PipelineStatus.PARTIAL_COMPLETED, result.status)
        self.assertEqual("partial_completed", data["status"])
        self.assertEqual("R2 fillet", data["skipped_features"][0]["name"])
        self.assertEqual("主体可导出，圆角跳过", data["partial_completion_reason"])

        result.mark_completed()

        self.assertEqual(PipelineStatus.COMPLETED, result.status)
        self.assertEqual([], result.skipped_features)
        self.assertIsNone(result.partial_completion_reason)

    def test_cad_process_result_supports_stopped_by_user_status(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")

        result.mark_stopped_by_user("用户在 view_analysis 阶段确认后停止处理")

        self.assertFalse(result.success)
        self.assertEqual(PipelineStatus.STOPPED_BY_USER, result.status)
        self.assertEqual("stopped_by_user", result.to_dict()["status"])
        self.assertIn("用户在 view_analysis", result.error_message)
        self.assertEqual("stop", result.to_dict()["stage_stop_action"])
        self.assertIsNone(result.to_dict()["stage_stop_stage"])

    def test_processor_collects_semantic_and_path_contract_questions(self):
        questions = CADProcessor._collect_clarification_questions({
            "semantic_policy": {
                "clarification_questions": [{"id": "bind_profile_length"}],
            },
            "modeling_instructions": {
                "clarification_questions": [{"id": "provide_extrusion_depth"}],
            },
        })

        self.assertEqual(
            ["bind_profile_length", "provide_extrusion_depth"],
            [question["id"] for question in questions],
        )

    def test_processor_maps_stage_confirmation_stop_to_status(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {
            "api": {
                "deepseek": {
                    "api_key": "test-key",
                    "_stage_confirmation": CallbackStageConfirmation(
                        lambda stage, payload: False
                    ),
                }
            }
        }
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(return_value={})

        result = processor.process_with_intelligent_analysis(
            "drawing.dxf",
            {},
            10.0,
        )

        self.assertEqual(PipelineStatus.STOPPED_BY_USER, result.status)
        self.assertIn("用户在 view_analysis", result.error_message)
        self.assertEqual("stop", result.stage_stop_action)
        self.assertEqual("view_analysis", result.stage_stop_stage)

    def test_pipeline_summary_separates_user_stop_from_failure(self):
        completed = CADProcessResult(success=True, input_file="ok.dxf")
        completed.mark_completed()
        partial = CADProcessResult(success=False, input_file="partial.dxf")
        partial.mark_partial_completed(
            skipped_features=[{"name": "slot", "reason": "missing width"}],
        )
        stopped = CADProcessResult(success=False, input_file="stop.dxf")
        stopped.mark_stopped_by_user()
        failed = CADProcessResult(success=False, input_file="bad.dxf")
        failed.mark_failed("bad")

        pipeline = CADPipeline.__new__(CADPipeline)
        summary = pipeline.get_summary({
            "ok": completed,
            "partial": partial,
            "stop": stopped,
            "bad": failed,
        })

        self.assertEqual(2, summary["success"])
        self.assertEqual(1, summary["partial_completed"])
        self.assertEqual(1, summary["stopped_by_user"])
        self.assertEqual(1, summary["failed"])

    def test_pipeline_basic_directory_entry_uses_basic_file_entry(self):
        pipeline = CADPipeline.__new__(CADPipeline)
        pipeline.list_available_files = unittest.mock.Mock(return_value=[{"name": "a.dxf"}])
        pipeline.set_input_dir = unittest.mock.Mock()
        pipeline.process_multiple_files_basic = unittest.mock.Mock(return_value={"a.dxf": "ok"})

        result = pipeline.process_directory_basic("drawings", 12.0)

        self.assertEqual({"a.dxf": "ok"}, result)
        pipeline.process_multiple_files_basic.assert_called_once_with(
            ["a.dxf"],
            12.0,
            None,
        )

    def test_basic_processing_skips_multiview_analysis(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {}
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._get_modeler = unittest.mock.Mock()
        modeler = unittest.mock.Mock()
        modeler.export.return_value = False
        processor._get_modeler.return_value = unittest.mock.Mock(return_value=modeler)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(
            side_effect=AssertionError("basic mode must not inspect views")
        )

        result = processor.process_single_file(
            "drawing.dxf",
            {},
            10.0,
            enable_analysis=False,
        )

        self.assertTrue(result.success)
        processor._prepare_intelligent_view_context.assert_not_called()
        self.assertEqual("basic", result.mode)
        self.assertEqual("planar_extrude", result.modeling_path)

    def test_geometry_data_processing_skips_multiview_analysis(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {}
        processor._get_modeler = unittest.mock.Mock()
        modeler = unittest.mock.Mock()
        processor._get_modeler.return_value = unittest.mock.Mock(return_value=modeler)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(
            side_effect=AssertionError("geometry execution must not inspect views")
        )

        result = processor.process_from_geometry_data(
            {"entities": []},
            {},
            10.0,
        )

        self.assertTrue(result.success)
        processor._prepare_intelligent_view_context.assert_not_called()
        self.assertEqual("basic", result.mode)
        self.assertEqual("planar_extrude", result.modeling_path)

    def test_intelligent_processing_routes_planar_decision_to_basic_executor(self):
        processor = CADProcessor.__new__(CADProcessor)
        processor.config = {
            "api": {
                "deepseek": {"api_key": "test-key"},
            }
        }
        processor._get_parser = unittest.mock.Mock()
        parser = unittest.mock.Mock()
        parser.parse.return_value = {"entities": []}
        parser.export_json.return_value = None
        processor._get_parser.return_value = unittest.mock.Mock(return_value=parser)
        processor._prepare_intelligent_view_context = unittest.mock.Mock(return_value={})

        routed_result = CADProcessResult(
            success=True,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="planar_extrude",
        )
        executor = unittest.mock.Mock()
        executor.execute.return_value = routed_result
        processor._get_modeling_executor = unittest.mock.Mock(return_value=executor)

        fake_analyzer = unittest.mock.Mock()
        fake_analyzer.analyze_full.return_value = {
            "modeling_path_decision": {"modeling_path": "planar_extrude", "reason": "simple"},
            "modeling_instructions": {
                "analysis_summary": "",
                "modeling_strategy": "",
                "freecad_script": "",
                "instructions": [],
                "key_dimensions": [],
                "warnings": [],
                "routed_to_planar_extrude": True,
            },
        }
        fake_analyzer.save_results.return_value = None

        with patch(
            "src.intelligent_analyzer.IntelligentEngineeringAnalyzer",
            return_value=fake_analyzer,
        ):
            result = processor.process_with_intelligent_analysis("drawing.dxf", {}, 10.0)

        self.assertIs(result, routed_result)
        executor.execute.assert_called_once()



if __name__ == "__main__":
    unittest.main()
