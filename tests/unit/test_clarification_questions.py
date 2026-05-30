# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.clarification import (
    choice_option,
    clarification_question,
)


class TestClarificationQuestions(unittest.TestCase):
    def test_builds_question_with_optional_user_facing_fields(self):
        question = clarification_question(
            question_id="provide_depth",
            text="请补充厚度。",
            kind="free_text",
            reason="缺少厚度无法建模。",
            example="10mm",
        )

        self.assertEqual("provide_depth", question["id"])
        self.assertEqual("请补充厚度。", question["text"])
        self.assertEqual("free_text", question["kind"])
        self.assertEqual([], question["options"])
        self.assertEqual("缺少厚度无法建模。", question["reason"])
        self.assertEqual("10mm", question["example"])
        self.assertNotIn("required", question)

    def test_choice_option_normalizes_values_to_strings(self):
        self.assertEqual(
            {"label": "厚度 10", "value": "10"},
            choice_option("厚度 10", 10),
        )


if __name__ == "__main__":
    unittest.main()
