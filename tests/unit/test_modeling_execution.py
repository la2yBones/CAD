# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from src.batch_processor.modeling_execution import (
    IntelligentModelingExecutor,
    ModelingExecutionRequest,
)
from src.batch_processor.processor import CADProcessResult
from src.batch_processor.processor import PipelineStatus


class TestIntelligentModelingExecutor(unittest.TestCase):
    def test_runs_ai_script_for_semantic_reconstruction(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.return_value = {
            "success": True,
            "step_path": "drawing.step",
            "fcstd_path": "drawing.FCStd",
        }

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            completed = IntelligentModelingExecutor({}, lambda: None).execute(
                result=result,
                intelligent_analysis_result={
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": {"freecad_script": "pass"},
                },
                geometry_data={"entities": []},
                output_structure={},
                extrude_height=10.0,
                missing_script_message="missing",
                script_failure_prefix="failed",
                completion_message="done",
            )

        self.assertTrue(completed.success)
        self.assertEqual("drawing.step", completed.output_paths["model_step"])
        self.assertEqual("drawing.FCStd", completed.output_paths["model_fcstd"])

    def test_marks_ai_script_with_skipped_features_as_partial_completed(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.return_value = {
            "success": True,
            "step_path": "drawing.step",
            "skipped_features": [
                {"name": "R2 fillet", "kind": "fillet", "reason": "FreeCAD fillet failed"}
            ],
            "completed_features": [
                {"name": "base body", "kind": "base"}
            ],
            "partial_completion_reason": "主体模型已导出，圆角失败后跳过",
        }

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            completed = IntelligentModelingExecutor({}, lambda: None).execute(
                result=result,
                intelligent_analysis_result={
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": {"freecad_script": "pass"},
                },
                geometry_data={"entities": []},
                output_structure={},
                extrude_height=10.0,
                missing_script_message="missing",
                script_failure_prefix="failed",
                completion_message="done",
            )

        self.assertTrue(completed.success)
        self.assertEqual(PipelineStatus.PARTIAL_COMPLETED, completed.status)
        self.assertEqual("drawing.step", completed.output_paths["model_step"])
        self.assertEqual("R2 fillet", completed.skipped_features[0]["name"])
        self.assertEqual("主体模型已导出，圆角失败后跳过", completed.partial_completion_reason)

    def test_runs_revolve_executor(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf", mode="intelligent")
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.return_value = {
            "success": True,
            "step_path": "drawing.step",
            "fcstd_path": "drawing.FCStd",
        }

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            completed = IntelligentModelingExecutor({}, lambda: None).execute(
                result=result,
                intelligent_analysis_result={
                    "modeling_path_decision": {
                        "modeling_path": "revolve",
                        "reason": "axisymmetric",
                        "candidate_paths": [
                            {
                                "path": "revolve",
                                "semantics": {
                                    "axis_point": [0, 0, 0],
                                    "axis_direction": [0, 0, 1],
                                    "profile_points": [
                                        [1, 0, 0],
                                        [1, 0, 2],
                                        [0, 0, 2],
                                        [1, 0, 0],
                                    ],
                                    "angle_degrees": 360.0,
                                },
                            }
                        ],
                    },
                },
                geometry_data={"entities": []},
                output_structure={},
                extrude_height=10.0,
                missing_script_message="missing",
                script_failure_prefix="failed",
                completion_message="done",
            )

        self.assertTrue(completed.success)
        self.assertEqual("revolve", completed.modeling_path)
        self.assertEqual("drawing.step", completed.output_paths["model_step"])

    def test_reports_missing_revolve_semantics(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf", mode="intelligent")

        completed = IntelligentModelingExecutor({}, lambda: None).execute(
            result=result,
            intelligent_analysis_result={
                "modeling_path_decision": {
                    "modeling_path": "revolve",
                    "candidate_paths": [],
                },
            },
            geometry_data={"entities": []},
            output_structure={},
            extrude_height=10.0,
            missing_script_message="missing",
            script_failure_prefix="failed",
            completion_message="done",
        )

        self.assertFalse(completed.success)
        self.assertIn("missing revolve semantics", completed.error_message)

    def test_uses_registered_path_handler(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf", mode="intelligent")
        calls = []

        def execute_custom_path(request: ModelingExecutionRequest):
            calls.append(request)
            request.result.mark_completed()
            request.result.output_paths["model_step"] = "custom.step"
            return request.result

        completed = IntelligentModelingExecutor(
            {},
            lambda: None,
            path_handlers={"custom_path": execute_custom_path},
        ).execute(
            result=result,
            intelligent_analysis_result={
                "modeling_path_decision": {"modeling_path": "custom_path"},
            },
            geometry_data={"entities": []},
            output_structure={},
            extrude_height=10.0,
            missing_script_message="missing",
            script_failure_prefix="failed",
            completion_message="done",
        )

        self.assertTrue(completed.success)
        self.assertEqual("custom_path", completed.modeling_path)
        self.assertEqual("custom.step", completed.output_paths["model_step"])
        self.assertEqual(1, len(calls))

    def test_respects_empty_handler_table(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf", mode="intelligent")

        completed = IntelligentModelingExecutor(
            {},
            lambda: None,
            path_handlers={},
        ).execute(
            result=result,
            intelligent_analysis_result={
                "modeling_path_decision": {"modeling_path": "revolve"},
                "modeling_instructions": {},
            },
            geometry_data={"entities": []},
            output_structure={},
            extrude_height=10.0,
            missing_script_message="missing script",
            script_failure_prefix="failed",
            completion_message="done",
        )

        self.assertFalse(completed.success)
        self.assertEqual("missing script", completed.error_message)
        self.assertIsNone(completed.modeling_path)
