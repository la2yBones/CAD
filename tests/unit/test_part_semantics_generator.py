# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.semantics import PartSemanticGenerator


class TestPartSemanticGenerator(unittest.TestCase):
    def test_user_content_lifts_user_modeling_hint_policy(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "context_version": "adjudicated_context_v1",
            "semantic_policy": {
                "user_modeling_hint": "优先生成主体，内部槽可以跳过。",
                "user_modeling_hint_policy": "drawing_facts_override_user_hint",
                "dimension_plan": {"allowed_dimensions": []},
            },
        })

        self.assertIn("=== 用户补充建模提示使用规则 ===", content)
        self.assertIn("优先生成主体，内部槽可以跳过。", content)
        self.assertIn("drawing_facts_override_user_hint", content)
        self.assertIn("必须以图纸事实和已裁决语义为准", content)

    def test_user_content_omits_hint_section_when_no_hint_exists(self):
        generator = PartSemanticGenerator.__new__(PartSemanticGenerator)

        content = generator._build_user_content({
            "context_version": "adjudicated_context_v1",
            "semantic_policy": {"dimension_plan": {"allowed_dimensions": []}},
        })

        self.assertNotIn("=== 用户补充建模提示使用规则 ===", content)


if __name__ == "__main__":
    unittest.main()
