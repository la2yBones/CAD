# -*- coding: utf-8 -*-
import unittest

from src.utils.stage_report import (
    StageDecisionSummary,
    build_semantic_adjudication_stage_summary,
    build_semantic_stage_summary,
    build_stage_report,
    build_view_stage_summary,
    build_modeling_generation_stage_summary,
)


class TestStageReport(unittest.TestCase):
    def test_view_stage_report_is_short_decision_summary(self):
        report = build_stage_report(
            "view_analysis",
            {
                "view_analysis": {
                    "drawing_type": "two_view",
                    "confidence": 0.82,
                    "views": [{"name": "main"}, {"name": "right"}],
                    "warnings": ["视图间深度关系不确定", "存在遮挡线", "第三条不应出现"],
                },
                "dimension_data": {"dimensions": [{"text": "30"}]},
                "semantic_policy": {
                    "clarification_questions": [{"id": "bind_profile_length"}],
                },
            },
        )

        self.assertIn("结论：two_view，2 个视图，1 个尺寸，置信度 0.82", report)
        self.assertIn("风险：继续后需要补充信息：1 项", report)
        self.assertIn("需补充：bind_profile_length", report)
        self.assertIn("下一步：继续后进入补充信息面板", report)
        self.assertNotIn("第三条不应出现", report)
        self.assertNotIn("{", report)

    def test_semantic_stage_report_limits_detail_arrays(self):
        report = build_stage_report(
            "semantic_reconstruction",
            {
                "part_semantics": {
                    "part_type": "flange",
                    "confidence": 0.66,
                    "summary": "这是一个很长的法兰盘摘要" * 10,
                    "dimension_source": "annotation",
                    "key_dimensions": [{"name": "outer_diameter"}],
                    "base_features": [{"kind": "cylinder"}],
                    "subtractive_features": [{"kind": "hole"}],
                    "uncertainties": ["孔深不确定", "倒角位置不确定", "第三条不应出现"],
                },
            },
        )

        self.assertIn("结论：flange，置信度 0.66，尺寸来源 annotation", report)
        self.assertIn("依据：主体特征 1 个，增材 0 个，减材 1 个", report)
        self.assertIn("置信度较低", report)
        self.assertIn("孔深不确定", report)
        self.assertNotIn("第三条不应出现", report)
        self.assertNotIn('"kind"', report)

    def test_semantic_adjudication_stage_report_is_short_decision_summary(self):
        report = build_stage_report(
            "semantic_adjudication",
            {
                "semantic_adjudication": {
                    "confidence": 0.82,
                    "view_roles": [{"view_id": "V1", "role": "main"}],
                    "dimension_roles": [
                        {"dimension_id": "D1", "role": "extrusion_depth"},
                        {"dimension_id": "D2", "role": "unresolved"},
                    ],
                    "feature_roles": [{"feature_id": "G1", "role": "through_hole"}],
                    "derived_dimensions": [
                        {"source_derived_dimension_id": "DD1", "role": "feature_height"}
                    ],
                    "clarification_questions": [{"id": "confirm_D2"}],
                    "uncertainties": ["D2 是否为凸台高度不确定"],
                    "warnings": ["第三条不应出现"],
                },
            },
        )

        self.assertIn("结论：图纸语义裁决，置信度 0.82，追问 1 项", report)
        self.assertIn("依据：视图角色 1 个，尺寸角色 1 个", report)
        self.assertIn("依据：特征角色 1 个，派生尺寸 1 个", report)
        self.assertIn("风险：继续后需要补充信息：1 项", report)
        self.assertIn("需补充：confirm_D2", report)
        self.assertIn("下一步：继续后进入补充信息面板", report)
        self.assertNotIn("{", report)

    def test_view_stage_report_shows_clarification_question_text(self):
        report = build_stage_report(
            "view_analysis",
            {
                "view_analysis": {
                    "drawing_type": "two_view",
                    "confidence": 0.9,
                    "views": [{"name": "main"}, {"name": "right"}],
                },
                "dimension_data": {"dimensions": []},
                "semantic_policy": {
                    "clarification_questions": [
                        {
                            "id": "confirm_depth",
                            "text": "请确认尺寸40是否表示主体深度。",
                            "reason": "该尺寸可能影响主体体量。",
                        }
                    ],
                },
            },
        )

        self.assertIn("继续后需要补充信息：1 项", report)
        self.assertIn("需补充：请确认尺寸40是否表示主体深度。", report)
        self.assertIn("该尺寸可能影响主体体量", report)

    def test_semantic_adjudication_summary_marks_failed_fallback(self):
        summary = build_semantic_adjudication_stage_summary(
            {
                "semantic_adjudication": {
                    "status": "failed",
                    "warnings": ["接口返回空内容"],
                },
            },
        )

        self.assertIn("图纸语义裁决失败", summary.risks[0])
        self.assertEqual("继续进入零件语义生成", summary.next_step)

    def test_view_stage_summary_exposes_stable_decision_fields(self):
        summary = build_view_stage_summary(
            {
                "view_analysis": {"drawing_type": "single_view", "confidence": 0.9, "views": [{}]},
                "dimension_data": {"dimensions": []},
                "semantic_policy": {"clarification_questions": []},
            }
        )

        self.assertIsInstance(summary, StageDecisionSummary)
        self.assertEqual("single_view，1 个视图，0 个尺寸，置信度 0.9", summary.conclusion)
        self.assertEqual("继续进入零件语义重建", summary.next_step)
        self.assertEqual((), summary.risks)

    def test_view_stage_report_shows_supervision_records(self):
        report = build_stage_report(
            "view_analysis",
            {
                "view_analysis": {
                    "drawing_type": "two_view",
                    "confidence": 0.8,
                    "views": [{"name": "main"}, {"name": "top"}],
                    "self_correction_log": [
                        {
                            "round_index": 1,
                            "max_rounds": 2,
                            "trigger": "view_relationship_uncertain",
                            "result": "修正视图关系",
                        }
                    ],
                },
                "dimension_data": {"dimensions": []},
                "semantic_policy": {},
            },
        )

        self.assertIn("模型自纠第 1/2 轮", report)
        self.assertIn("模型自纠记录：1 轮", report)

    def test_semantic_stage_summary_keeps_long_summary_out_of_dialog(self):
        summary = build_semantic_stage_summary(
            {
                "part_semantics": {
                    "part_type": "bracket",
                    "confidence": 0.95,
                    "summary": "这一段完整分析不应进入确认弹窗" * 20,
                    "dimension_source": "geometry",
                    "key_dimensions": [{"name": "width"}],
                    "base_features": [],
                    "additive_features": [],
                    "subtractive_features": [],
                    "uncertainties": [],
                    "warnings": [],
                }
            }
        )

        report = summary.render()

        self.assertNotIn("这一段完整分析", report)
        self.assertIn("依据：关键尺寸 1 个", report)

    def test_semantic_adjudication_stage_report_shows_retry_record(self):
        report = build_stage_report(
            "semantic_adjudication",
            {
                "semantic_adjudication": {
                    "confidence": 0.9,
                    "stage_retry_log": [
                        {
                            "trigger": "user_requested_retry_stage",
                            "result": "已重跑图纸语义裁决",
                        }
                    ],
                },
            },
        )

        self.assertIn("阶段重跑，原因 user_requested_retry_stage", report)
        self.assertIn("阶段重跑记录：1 次", report)

    def test_semantic_reconstruction_stage_report_shows_operation_hint(self):
        report = build_stage_report(
            "semantic_reconstruction",
            {
                "part_semantics": {
                    "part_type": "flange",
                    "confidence": 0.9,
                    "dimension_source": "annotation",
                },
            },
        )

        self.assertIn("flange", report)

    def test_semantic_stage_summary_routes_missing_depth_to_clarification(self):
        summary = build_semantic_stage_summary(
            {
                "part_semantics": {
                    "part_type": "bracket",
                    "confidence": 0.7,
                    "dimension_source": "annotation",
                    "key_dimensions": [],
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [],
                    "subtractive_features": [],
                    "uncertainties": ["Extrusion depth missing"],
                    "warnings": [],
                }
            }
        )

        self.assertEqual(
            "继续后进入建模前澄清，补充主体厚度或拉伸深度",
            summary.next_step,
        )

    def test_semantic_stage_report_localizes_common_english_risks(self):
        report = build_stage_report(
            "semantic_reconstruction",
            {
                "part_semantics": {
                    "part_type": "bracket",
                    "confidence": 0.7,
                    "dimension_source": "annotation",
                    "key_dimensions": [],
                    "base_features": [{"kind": "profile_extrusion"}],
                    "additive_features": [{"kind": "boss"}],
                    "subtractive_features": [],
                    "uncertainties": [
                        "Extrusion depth missing; a reasonable default may be assumed."
                    ],
                    "warnings": [
                        "Modeling will require assumptions for missing depth and boss."
                    ],
                }
            },
        )

        self.assertIn("主体拉伸深度缺失，需补充主体厚度或拉伸深度", report)
        self.assertIn("建模需要对缺失深度、凸台作额外假设，需补充确认", report)
        self.assertNotIn("Extrusion depth missing", report)
        self.assertNotIn("Modeling will require assumptions", report)

    def test_modeling_generation_stage_report_shows_self_correction(self):
        report = build_stage_report(
            "modeling_generation",
            {
                "modeling_instructions": {
                    "freecad_script": "final_shape = Part.makeBox(1, 1, 1)",
                    "completed_features": [{"name": "base"}],
                    "skipped_features": [],
                    "warnings": [],
                    "self_correction_log": [
                        {
                            "round_index": 1,
                            "max_rounds": 2,
                            "trigger": "script_quality_validation_failed",
                            "result": "修正后脚本执行成功",
                        }
                    ],
                }
            },
        )

        self.assertIn("结论：建模指令已生成", report)
        self.assertIn("模型自纠第 1/2 轮", report)
        self.assertIn("模型自纠记录：1 轮", report)
        self.assertIn("下一步：继续进入 FreeCAD 脚本执行", report)

    def test_modeling_generation_stage_summary_handles_missing_script(self):
        summary = build_modeling_generation_stage_summary(
            {"modeling_instructions": {"freecad_script": ""}}
        )

        self.assertEqual("建模指令未生成可执行脚本", summary.conclusion)
        self.assertEqual("无法继续执行，缺少建模脚本", summary.next_step)

    def test_modeling_generation_stage_report_shows_retry_record(self):
        report = build_stage_report(
            "modeling_generation",
            {
                "modeling_instructions": {
                    "freecad_script": "final_shape = Part.makeBox(1, 1, 1)",
                    "completed_features": [],
                    "skipped_features": [],
                    "warnings": [],
                    "stage_retry_log": [
                        {
                            "trigger": "user_requested_retry_stage",
                            "result": "用户触发后已重跑建模指令生成阶段",
                        }
                    ],
                }
            },
        )

        self.assertIn("阶段重跑，原因 user_requested_retry_stage", report)
        self.assertIn("阶段重跑记录：1 次", report)


if __name__ == "__main__":
    unittest.main()
