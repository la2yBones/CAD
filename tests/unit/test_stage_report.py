# -*- coding: utf-8 -*-
import unittest

from src.utils.stage_report import build_stage_report


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
        self.assertIn("继续后需要补充信息：1 项", report)
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
        self.assertIn("主体：基础特征 1 个，增材 0 个，减材 1 个", report)
        self.assertIn("置信度较低", report)
        self.assertIn("孔深不确定", report)
        self.assertNotIn("第三条不应出现", report)
        self.assertNotIn('"kind"', report)


if __name__ == "__main__":
    unittest.main()
