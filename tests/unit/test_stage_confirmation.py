# -*- coding: utf-8 -*-
import unittest

from src.utils.stage_confirmation import (
    CallbackStageConfirmation,
    StageConfirmationResult,
    StageConfirmationStopped,
    StageReview,
    default_stage_stop_message,
    ensure_stage_stop_message,
    request_stage_confirmation,
    stage_display_name,
)


class LegacyBoolConfirmation:
    def __init__(self, value):
        self.value = value

    def should_continue(self, review):
        return self.value


class TestStageConfirmation(unittest.TestCase):
    def test_callback_confirmation_returns_stop_result_with_default_message(self):
        confirmation = CallbackStageConfirmation(lambda stage, payload: False)

        result = confirmation.review(StageReview("view_analysis", {}))

        self.assertFalse(result.continue_processing)
        self.assertEqual("stop", result.action)
        self.assertEqual("view_analysis", result.stage)
        self.assertEqual("用户在 视图语义校正 阶段确认后停止处理", result.message)

    def test_callback_confirmation_preserves_result_object(self):
        expected = StageConfirmationResult(
            continue_processing=False,
            action="cancel",
            message="cancelled",
            stage="view_analysis",
        )
        confirmation = CallbackStageConfirmation(lambda stage, payload: expected)

        result = confirmation.review(StageReview("view_analysis", {}))

        self.assertEqual(expected, result)

    def test_callback_confirmation_preserves_continue_result_object(self):
        expected = StageConfirmationResult.continue_()
        confirmation = CallbackStageConfirmation(lambda stage, payload: expected)

        result = confirmation.review(StageReview("semantic_reconstruction", {}))

        self.assertTrue(result.continue_processing)
        self.assertEqual("continue", result.action)
        self.assertEqual("", result.message)
        self.assertIsNone(result.stage)

    def test_request_stage_confirmation_preserves_legacy_bool_adapter(self):
        result = request_stage_confirmation(
            LegacyBoolConfirmation(False),
            StageReview("semantic_reconstruction", {}),
        )

        self.assertEqual(
            StageConfirmationResult.stop(
                default_stage_stop_message("semantic_reconstruction"),
                stage="semantic_reconstruction",
            ),
            result,
        )

    def test_stage_display_name_maps_user_visible_stage_names(self):
        self.assertEqual("视图语义校正", stage_display_name("view_analysis"))
        self.assertEqual("零件语义重建", stage_display_name("semantic_reconstruction"))
        self.assertEqual("custom_stage", stage_display_name("custom_stage"))
        self.assertEqual(
            "用户在 零件语义重建 阶段确认后停止处理",
            default_stage_stop_message("semantic_reconstruction"),
        )

    def test_stage_stop_exception_preserves_result_action(self):
        result = ensure_stage_stop_message(
            StageConfirmationResult(
                continue_processing=False,
                action="cancel",
                message="",
            ),
            "view_analysis",
        )

        error = StageConfirmationStopped(result)

        self.assertEqual("cancel", error.result.action)
        self.assertEqual("view_analysis", error.result.stage)
        self.assertIn("视图语义校正", str(error))


if __name__ == "__main__":
    unittest.main()
