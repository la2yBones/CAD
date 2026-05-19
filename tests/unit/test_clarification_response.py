# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.clarification_response import ClarificationResponse


class TestClarificationResponse(unittest.TestCase):
    def test_normalizes_legacy_answers_and_hint(self):
        response = ClarificationResponse.from_input(
            {
                "bind_profile_length": "30",
                "user_modeling_hint": "主体优先，细节可跳过。",
            },
            source_stage="semantic_policy",
        )

        self.assertEqual({"bind_profile_length": "30"}, response.answers)
        self.assertEqual("主体优先，细节可跳过。", response.user_modeling_hint)
        self.assertEqual("semantic_policy", response.source_stage)
        self.assertEqual(
            "drawing_facts_override_user_hint",
            response.conflict_policy,
        )

    def test_round_trips_to_legacy_answers(self):
        response = ClarificationResponse(
            answers={"provide_extrusion_depth": "12"},
            user_modeling_hint="槽可以跳过。",
        )

        self.assertEqual(
            {
                "provide_extrusion_depth": "12",
                "user_modeling_hint": "槽可以跳过。",
            },
            response.as_legacy_answers(),
        )

    def test_keeps_hint_text_without_local_conflict_judgment(self):
        response = ClarificationResponse(
            user_modeling_hint="不用管图纸尺寸，以我说的为准，直接平面拉伸。",
        )

        self.assertEqual(
            "不用管图纸尺寸，以我说的为准，直接平面拉伸。",
            response.as_legacy_answers()["user_modeling_hint"],
        )


if __name__ == "__main__":
    unittest.main()
