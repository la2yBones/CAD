# -*- coding: utf-8 -*-
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from src.batch_processor import CADProcessResult
from src.batch_processor.pending_view_model import (
    build_pending_item_detail,
    pending_recovery_summary,
    pending_recovery_type,
)
from src.reconstruction.clarification import (
    build_candidate_clarification_summary,
    clarification_option_label,
    clarification_option_value,
    is_candidate_clarification_question,
)
from src.reconstruction.analysis_result import (
    IntelligentAnalysisResult,
    ModelingInstructionsResult,
)
from src.gui.helpers import (
    format_stage_supervision_message,
    read_project_env,
    stage_self_correction_log_lines,
    write_project_env,
)


class TestGuiSettingsEnv(unittest.TestCase):
    def test_format_stage_supervision_message_names_hidden_actions(self):
        result = CADProcessResult(success=False, input_file="drawing.dxf")
        result.mark_stage_action_requested(
            action="self_correct",
            stage="view_analysis",
        )

        label, message = format_stage_supervision_message(result)

        self.assertEqual("已请求模型自纠", label)
        self.assertIn("视图语义校正", message)
        self.assertIn("模型自纠", message)

    def test_modeling_self_correction_log_lines_describe_rounds(self):
        result = CADProcessResult(success=True, input_file="drawing.dxf")
        result.intelligent_analysis = {
            "modeling_instructions": {
                "self_correction_log": [
                    {
                        "round_index": 1,
                        "max_rounds": 2,
                        "trigger": "script_quality_validation_failed",
                        "result": "修正后脚本执行成功",
                    }
                ]
            }
        }

        lines = stage_self_correction_log_lines(result)

        self.assertEqual(1, len(lines))
        self.assertIn("模型自纠第 1/2 轮", lines[0])
        self.assertIn("建模指令生成", lines[0])

    def test_stage_self_correction_log_lines_accepts_typed_analysis_result(self):
        result = CADProcessResult(success=True, input_file="drawing.dxf")
        result.intelligent_analysis = IntelligentAnalysisResult(
            modeling_instructions=ModelingInstructionsResult(
                self_correction_log=[
                    {
                        "stage": "modeling_generation",
                        "round_index": 1,
                        "max_rounds": 2,
                        "trigger": "script_quality_validation_failed",
                        "result": "修正后脚本执行成功",
                    }
                ]
            )
        )

        lines = stage_self_correction_log_lines(result)

        self.assertEqual(1, len(lines))
        self.assertIn("模型自纠第 1/2 轮", lines[0])
        self.assertIn("建模指令生成", lines[0])

    def test_stage_self_correction_log_lines_include_all_llm_stages(self):
        result = CADProcessResult(success=True, input_file="drawing.dxf")
        result.intelligent_analysis = {
            "view_analysis": {
                "self_correction_log": [
                    {
                        "stage": "view_analysis",
                        "round_index": 1,
                        "max_rounds": 2,
                        "trigger": "user_requested_view_self_correction",
                        "result": "已重新生成视图语义",
                    }
                ]
            },
            "semantic_policy": {
                "semantic_adjudication": {
                    "self_correction_log": [
                        {
                            "stage": "semantic_adjudication",
                            "round_index": 1,
                            "max_rounds": 2,
                            "trigger": "user_requested_semantic_adjudication_self_correction",
                            "result": "已重新生成图纸语义裁决",
                        }
                    ]
                }
            },
            "part_semantics": {
                "self_correction_log": [
                    {
                        "stage": "semantic_reconstruction",
                        "round_index": 1,
                        "max_rounds": 2,
                        "trigger": "user_requested_semantic_reconstruction_self_correction",
                        "result": "已重新生成零件语义",
                    }
                ]
            },
            "modeling_instructions": {
                "self_correction_log": [
                    {
                        "stage": "modeling_generation",
                        "round_index": 1,
                        "max_rounds": 2,
                        "trigger": "script_quality_validation_failed",
                        "result": "修正后脚本执行成功",
                    }
                ]
            },
        }

        lines = stage_self_correction_log_lines(result)

        self.assertEqual(4, len(lines))
        self.assertTrue(any("视图语义校正" in line for line in lines))
        self.assertTrue(any("图纸语义裁决" in line for line in lines))
        self.assertTrue(any("零件语义重建" in line for line in lines))
        self.assertTrue(any("建模指令生成" in line for line in lines))

    def test_handle_processing_stage_displays_self_correction_progress(self):
        from src.gui.processing_panel import ProcessingPanel

        panel = ProcessingPanel.__new__(ProcessingPanel)
        panel._active_batch_item_id = None
        panel._set_batch_item_stage = unittest.mock.Mock()
        panel._update_progress = unittest.mock.Mock()

        ProcessingPanel._handle_processing_stage(panel, "self_correction", "模型自纠中 1/2")

        panel._set_batch_item_stage.assert_called_once_with(
            None,
            "self_correction",
            "处理中",
            "模型自纠中 1/2",
        )
        panel._update_progress.assert_called_once_with(65, "模型自纠中 1/2...")

    def test_write_project_env_preserves_comments_and_updates_known_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\nDEEPSEEK_API_KEY=old\nOTHER=value\n",
                encoding="utf-8",
            )

            write_project_env(
                {
                    "DEEPSEEK_API_KEY": "new-key",
                    "MOONSHOT_API_KEY": "kimi-key",
                    "FREECAD_BIN_PATH": r"D:\FreeCAD 1.0\bin",
                },
                env_path,
            )

            text = env_path.read_text(encoding="utf-8")
            values = read_project_env(env_path)

        self.assertIn("# comment", text)
        self.assertIn("OTHER=value", text)
        self.assertEqual("new-key", values["DEEPSEEK_API_KEY"])
        self.assertEqual("kimi-key", values["MOONSHOT_API_KEY"])
        self.assertEqual(r"D:\FreeCAD 1.0\bin", values["FREECAD_BIN_PATH"])

    def test_read_project_env_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n# API\nDEEPSEEK_API_KEY='quoted-key'\nFREECAD_BIN_PATH=\"D:/FreeCAD/bin\"\n",
                encoding="utf-8",
            )

            values = read_project_env(env_path)

        self.assertEqual("quoted-key", values["DEEPSEEK_API_KEY"])
        self.assertEqual("D:/FreeCAD/bin", values["FREECAD_BIN_PATH"])

    def test_pending_item_resume_restores_previous_result_metadata(self):
        result = CADProcessResult.from_pending_item({
            "input_file": "drawing.dxf",
            "mode": "intelligent",
            "modeling_path": "semantic_reconstruction",
            "clarification_questions": [{"id": "user_modeling_hint"}],
            "clarification_context": {"partial_modeling_recovery": True},
            "output_paths": {
                "analysis_full": "out/drawing_full.json",
                "model_step": "out/drawing.step",
            },
            "completed_features": [{"name": "base_body"}],
            "skipped_features": [{"name": "R15"}],
            "partial_completion_reason": "主体已生成，R15 跳过",
        })

        self.assertEqual("semantic_reconstruction", result.modeling_path)
        self.assertEqual("out/drawing_full.json", result.output_paths["analysis_full"])
        self.assertEqual("base_body", result.completed_features[0]["name"])
        self.assertEqual("R15", result.skipped_features[0]["name"])
        self.assertEqual("主体已生成，R15 跳过", result.partial_completion_reason)

    def test_candidate_clarification_question_is_rendered_as_explicit_choice(self):
        question = {
            "id": "resolve_profile_length",
            "kind": "single_choice",
            "options": [
                {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
                {"label": "不确定 / 暂不使用这些候选", "value": "__unknown__"},
            ],
        }

        self.assertTrue(is_candidate_clarification_question(question))
        self.assertEqual("48（由相邻尺寸链组合得到的候选）", clarification_option_label(question["options"][0]))
        self.assertEqual("48", clarification_option_value(question["options"][0]))
        self.assertEqual("__unknown__", clarification_option_value(question["options"][1]))

    def test_candidate_clarification_summary_confirms_selected_value(self):
        questions = [{
            "id": "resolve_profile_length",
            "text": "系统只找到了轮廓总长的候选值，请确认是否采用。",
            "kind": "single_choice",
            "options": [
                {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
                {"label": "不确定 / 暂不使用这些候选", "value": "__unknown__"},
            ],
        }]

        summary = build_candidate_clarification_summary(
            questions,
            {"resolve_profile_length": "48"},
        )

        self.assertIn("即将提交以下候选尺寸处理结果", summary)
        self.assertIn("确认采用 48（由相邻尺寸链组合得到的候选）", summary)

    def test_candidate_clarification_summary_marks_unknown_as_excluded(self):
        questions = [{
            "id": "resolve_profile_length",
            "text": "系统只找到了轮廓总长的候选值，请确认是否采用。",
            "kind": "single_choice",
            "options": [
                {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
                {"label": "不确定 / 暂不使用这些候选", "value": "__unknown__"},
            ],
        }]

        summary = build_candidate_clarification_summary(
            questions,
            {"resolve_profile_length": "__unknown__"},
        )

        self.assertIn("不采用候选值", summary)
        self.assertIn("不会把它作为建模尺寸", summary)

    def test_non_candidate_single_choice_keeps_generic_rendering_path(self):
        question = {
            "id": "select_modeling_path",
            "kind": "single_choice",
            "options": ["语义重建路径", "平面拉伸路径"],
        }

        self.assertFalse(is_candidate_clarification_question(question))
        self.assertEqual("语义重建路径", clarification_option_label(question["options"][0]))
        self.assertEqual("语义重建路径", clarification_option_value(question["options"][0]))

    def test_pending_item_detail_summarizes_questions_and_recovery_state(self):
        detail = build_pending_item_detail({
            "input_file": "examples/cad_files/base.dxf",
            "source_status": "partial_completed",
            "modeling_path": "semantic_reconstruction",
            "updated_at": "2026-05-25T10:00:00",
            "partial_completion_reason": "主体已生成，圆角跳过",
            "clarification_questions": [{
                "id": "resolve_profile_length",
                "text": "系统只找到了轮廓总长的候选值，请确认是否采用。",
                "reason": "轮廓总长目前只是本地候选。",
                "options": [
                    {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
                    {"label": "不确定 / 暂不使用这些候选", "value": "__unknown__"},
                ],
            }],
            "clarification_context": {
                "script_validation_errors": ["缺少 final_shape 赋值，无法确认最终实体"],
            },
            "skipped_features": [{"name": "fillet_R4", "reason": "API 受限"}],
            "output_paths": {"model_step": "out/base.step"},
        })

        self.assertIn("base.dxf", detail)
        self.assertIn("恢复类型：部分建模恢复", detail)
        self.assertIn("partial_completed", detail)
        self.assertIn("主体已生成，圆角跳过", detail)
        self.assertIn("48（由相邻尺寸链组合得到的候选）", detail)
        self.assertIn("fillet_R4: API 受限", detail)
        self.assertIn("上次脚本校验问题", detail)
        self.assertIn("缺少 final_shape", detail)
        self.assertIn("model_step: out/base.step", detail)

    def test_pending_recovery_type_distinguishes_recovery_reason(self):
        item = {
            "clarification_questions": [{"id": "script_quality_recovery_hint"}],
            "clarification_context": {"script_quality_recovery": True},
        }

        self.assertEqual("脚本质量恢复", pending_recovery_type(item))
        self.assertEqual("脚本质量恢复，需要补充 1 项信息", pending_recovery_summary(item))

    def test_pending_item_detail_has_empty_state_text(self):
        detail = build_pending_item_detail(None)

        self.assertIn("选中一条待恢复任务", detail)

if __name__ == "__main__":
    unittest.main()
