#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage confirmation seam for interactive and non-interactive analysis callers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Protocol

from .stage_self_correction import CONTINUE, RETRY_STAGE, SELF_CORRECT, STOP

RETRY_WITH_PARTIAL = "retry_with_partial"


@dataclass(frozen=True)
class StageReview:
    """A completed LLM stage that may require human release before continuing."""

    stage: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class StageConfirmationResult:
    """Stable result of a stage review, including caller-facing stop context."""

    continue_processing: bool
    action: str = "continue"
    message: str = ""
    stage: Optional[str] = None
    retained_items: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def continue_(cls) -> "StageConfirmationResult":
        return cls(continue_processing=True, action=CONTINUE, message="")

    @classmethod
    def stop(
        cls,
        message: str = "",
        stage: Optional[str] = None,
    ) -> "StageConfirmationResult":
        return cls(
            continue_processing=False,
            action=STOP,
            message=message,
            stage=stage,
        )

    @classmethod
    def retry_stage(
        cls,
        message: str = "",
        stage: Optional[str] = None,
    ) -> "StageConfirmationResult":
        return cls(
            continue_processing=False,
            action=RETRY_STAGE,
            message=message,
            stage=stage,
        )

    @classmethod
    def self_correct(
        cls,
        message: str = "",
        stage: Optional[str] = None,
    ) -> "StageConfirmationResult":
        return cls(
            continue_processing=False,
            action=SELF_CORRECT,
            message=message,
            stage=stage,
        )

    @classmethod
    def retry_with_partial(
        cls,
        retained_items: Dict[str, Any],
        message: str = "",
        stage: Optional[str] = None,
    ) -> "StageConfirmationResult":
        return cls(
            continue_processing=False,
            action=RETRY_WITH_PARTIAL,
            message=message or "用户选择带部分成果重跑",
            stage=stage,
            retained_items=retained_items,
        )

    @property
    def requests_retry(self) -> bool:
        return self.action == RETRY_STAGE

    @property
    def requests_self_correction(self) -> bool:
        return self.action == SELF_CORRECT

    @property
    def requests_retry_with_partial(self) -> bool:
        return self.action == RETRY_WITH_PARTIAL

    @property
    def is_stop(self) -> bool:
        return self.action == STOP

    @property
    def blocks_auto_continue(self) -> bool:
        return not self.continue_processing


class StageConfirmation(Protocol):
    """Interface used by analysis pipelines to request release of completed stages."""

    def review(self, review: StageReview) -> StageConfirmationResult:
        ...

    def should_continue(self, review: StageReview) -> bool:
        ...


class ContinueStageConfirmation:
    """Non-interactive adapter: every completed stage is automatically released."""

    def review(self, review: StageReview) -> StageConfirmationResult:
        return StageConfirmationResult.continue_()

    def should_continue(self, review: StageReview) -> bool:
        return self.review(review).continue_processing


class CallbackStageConfirmation:
    """Adapter for UI or test callbacks that already expose stage/payload arguments."""

    def __init__(self, callback: Callable[[str, Dict[str, Any]], Any]):
        self.callback = callback

    def review(self, review: StageReview) -> StageConfirmationResult:
        result = self.callback(review.stage, review.payload)
        if isinstance(result, StageConfirmationResult):
            return ensure_stage_stop_message(result, review.stage)
        if bool(result):
            return StageConfirmationResult.continue_()
        return StageConfirmationResult.stop(
            default_stage_stop_message(review.stage),
            stage=review.stage,
        )

    def should_continue(self, review: StageReview) -> bool:
        return self.review(review).continue_processing


class StageConfirmationStopped(RuntimeError):
    """Raised when a caller declines to continue after reviewing a stage."""

    def __init__(self, result: StageConfirmationResult):
        self.result = result
        super().__init__(result.message)


STAGE_DISPLAY_NAMES = {
    "view_analysis": "视图语义校正",
    "semantic_adjudication": "图纸语义裁决",
    "semantic_reconstruction": "零件语义重建",
    "modeling_generation": "建模指令生成",
}


def stage_display_name(stage: str) -> str:
    return STAGE_DISPLAY_NAMES.get(stage, stage)


def default_stage_stop_message(stage: str) -> str:
    return f"用户在 {stage_display_name(stage)} 阶段确认后停止处理"


def default_stage_action_message(action: str, stage: str) -> str:
    display = stage_display_name(stage)
    if action == RETRY_STAGE:
        return f"用户在 {display} 阶段确认后要求重跑当前阶段"
    if action == SELF_CORRECT:
        return f"用户在 {display} 阶段确认后要求模型自纠"
    return default_stage_stop_message(stage)


def ensure_stage_stop_message(
    result: StageConfirmationResult,
    stage: str,
) -> StageConfirmationResult:
    if result.continue_processing:
        return result
    if result.message and result.stage:
        return result
    return StageConfirmationResult(
        continue_processing=False,
        action=result.action,
        message=result.message or default_stage_action_message(result.action, stage),
        stage=result.stage or stage,
    )


def request_stage_confirmation(
    confirmation: StageConfirmation,
    review: StageReview,
) -> StageConfirmationResult:
    """Ask a confirmation adapter for a stage decision while preserving bool adapters."""
    review_method = getattr(confirmation, "review", None)
    if callable(review_method):
        result = review_method(review)
        if isinstance(result, StageConfirmationResult):
            return result
        return (
            StageConfirmationResult.continue_()
            if bool(result)
            else StageConfirmationResult.stop(
                default_stage_stop_message(review.stage),
                stage=review.stage,
            )
        )

    return (
        StageConfirmationResult.continue_()
        if confirmation.should_continue(review)
        else StageConfirmationResult.stop(
            default_stage_stop_message(review.stage),
            stage=review.stage,
        )
    )


def resolve_stage_confirmation(config: Optional[Dict[str, Any]]) -> StageConfirmation:
    config = config or {}
    configured = config.get("_stage_confirmation")
    if configured and hasattr(configured, "should_continue"):
        return configured

    legacy_callback = config.get("_stage_confirmation_callback")
    if callable(legacy_callback):
        return CallbackStageConfirmation(legacy_callback)

    return ContinueStageConfirmation()
