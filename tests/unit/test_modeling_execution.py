# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from src.batch_processor.modeling_execution import (
    IntelligentModelingExecutor,
    ModelingExecutionRequest,
)
from src.batch_processor.result import CADProcessResult
from src.batch_processor.result import PipelineStatus


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

    def test_missing_script_message_removes_generic_modeler_fallback_text(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )

        failed = IntelligentModelingExecutor({}, lambda: None).execute(
            result=result,
            intelligent_analysis_result={
                "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                "modeling_instructions": {"freecad_script": ""},
            },
            geometry_data={"entities": []},
            output_structure={},
            extrude_height=10.0,
            missing_script_message="未获得可执行的 AI FreeCAD 建模脚本；统一智能处理不会调用通用建模器兜底",
            script_failure_prefix="AI脚本执行失败，统一智能处理不会调用通用建模器兜底",
            completion_message="done",
        )

        self.assertFalse(failed.success)
        self.assertEqual("未获得可执行的 AI FreeCAD 建模脚本", failed.error_message)
        self.assertNotIn("通用建模器兜底", failed.error_message)

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

    def test_treats_speculative_skipped_fillet_as_completed_warning(self):
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
                {
                    "name": "thickness_edge_fillets",
                    "kind": "fillet",
                    "reason": "R=4x1.5 possibly only refers to front-view corner fillets; thickness edge fillets are not clearly annotated",
                    "risk": "If drawing requires all edge fillets, model may be incomplete.",
                }
            ],
            "completed_features": [
                {"name": "square_plate_with_corners", "kind": "base"},
                {"name": "cylindrical_boss", "kind": "additive"},
                {"name": "through_hole", "kind": "subtractive"},
            ],
            "partial_completion_reason": "main required features completed; speculative fillet skipped",
        }
        modeling_instructions = {"freecad_script": "pass", "warnings": []}

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            executor = IntelligentModelingExecutor({}, lambda: None)
            completed = executor.execute(
                result=result,
                intelligent_analysis_result={
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": modeling_instructions,
                },
                geometry_data={"entities": []},
                output_structure={},
                extrude_height=10.0,
                missing_script_message="missing",
                script_failure_prefix="failed",
                completion_message="done",
            )

        self.assertTrue(completed.success)
        self.assertEqual(PipelineStatus.COMPLETED, completed.status)
        self.assertEqual([], completed.skipped_features)
        self.assertIsNone(completed.partial_completion_reason)
        typed_warnings = executor._analysis.modeling_instructions.warnings
        self.assertIn("推测性跳过细节已作为风险提示处理", typed_warnings[0])
        self.assertNotIn("possibly", typed_warnings[0])

    def test_script_readiness_failure_becomes_pending_clarification(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.return_value = {
            "success": False,
            "error": "AI脚本未通过可执行性校验: 缺少 final_shape 赋值",
            "validation_errors": ["缺少 final_shape 赋值，无法确认最终实体"],
            "failure_stage": "script_readiness",
            "failure_kind": "script_quality",
            "recoverable": True,
        }

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner):
            completed = IntelligentModelingExecutor({}, lambda: None).execute(
                result=result,
                intelligent_analysis_result={
                    "view_analysis": {"drawing_type": "two_view"},
                    "dimension_extraction": {"dimensions": []},
                    "reconstruction_context": {"semantic_policy": {}},
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": {
                        "analysis_summary": "测试脚本",
                        "freecad_script": "solid = Part.makeBox(1, 1, 1)",
                        "_modeling_task_payload": {
                            "task_version": "modeling_task_v1",
                            "object": {"part_type": "plate"},
                        },
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
        self.assertEqual(PipelineStatus.NEEDS_CLARIFICATION, completed.status)
        self.assertEqual("script_quality_recovery_hint", completed.clarification_questions[0]["id"])
        self.assertTrue(completed.clarification_context["script_quality_recovery"])
        self.assertEqual(
            ["缺少 final_shape 赋值，无法确认最终实体"],
            completed.clarification_context["script_validation_errors"],
        )
        correction_request = completed.clarification_context["self_correction_request"]
        self.assertEqual("modeling_generation", correction_request["stage"])
        self.assertEqual(1, correction_request["round_index"])
        self.assertEqual(2, correction_request["max_rounds"])
        self.assertEqual(
            "modeling_task_v1",
            correction_request["stage_payload"]["task_version"],
        )
        self.assertEqual(
            "script_quality_1",
            correction_request["validation_issues"][0]["code"],
        )
        correction_result = completed.clarification_context["self_correction_result"]
        self.assertEqual("pending_recovery", correction_result["status"])
        self.assertEqual("self_correct", correction_result["next_action"])

    def test_script_readiness_failure_self_corrects_before_pending(self):
        result = CADProcessResult(
            success=False,
            input_file="drawing.dxf",
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )
        fake_runner = unittest.mock.Mock()
        fake_runner.run_script.side_effect = [
            {
                "success": False,
                "error": "AI脚本未通过可执行性校验: 缺少 final_shape 赋值",
                "validation_errors": ["缺少 final_shape 赋值，无法确认最终实体"],
                "failure_stage": "script_readiness",
                "failure_kind": "script_quality",
                "recoverable": True,
            },
            {
                "success": True,
                "step_path": "corrected.step",
                "fcstd_path": "corrected.FCStd",
            },
        ]
        fake_generator = unittest.mock.Mock()
        fake_generator.generate_from_self_correction.return_value = {
            "analysis_summary": "已修复脚本出口",
            "freecad_script": "final_shape = Part.makeBox(1, 1, 1)",
            "instructions": [],
            "warnings": [],
            "completed_features": [],
            "skipped_features": [],
        }
        progress_callback = unittest.mock.Mock()

        with patch("src.model_generator.ai_script_runner.AIScriptRunner", return_value=fake_runner), patch(
            "src.reconstruction.instruction_generator.FreeCADInstructionGenerator",
            return_value=fake_generator,
        ):
            completed = IntelligentModelingExecutor(
                {
                    "_progress_callback": progress_callback,
                    "api": {
                        "deepseek": {
                            "api_key": "test-key",
                            "model": "deepseek-v4-pro",
                        }
                    }
                },
                lambda: None,
            ).execute(
                result=result,
                intelligent_analysis_result={
                    "view_analysis": {"drawing_type": "two_view"},
                    "dimension_extraction": {"dimensions": []},
                    "reconstruction_context": {"semantic_policy": {}},
                    "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
                    "modeling_instructions": {
                        "analysis_summary": "测试脚本",
                        "freecad_script": "solid = Part.makeBox(1, 1, 1)",
                        "_modeling_task_payload": {
                            "task_version": "modeling_task_v1",
                            "object": {"part_type": "plate"},
                        },
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
        self.assertEqual(PipelineStatus.COMPLETED, completed.status)
        self.assertEqual("corrected.step", completed.output_paths["model_step"])
        self.assertEqual(2, fake_runner.run_script.call_count)
        correction_request = fake_generator.generate_from_self_correction.call_args.args[0]
        self.assertEqual("modeling_generation", correction_request.stage)
        self.assertEqual("script_quality_1", correction_request.validation_issues[0].code)
        progress_callback.assert_any_call("self_correction", "模型自纠中 1/2")

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
