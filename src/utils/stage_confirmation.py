#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage confirmation seam for interactive and non-interactive analysis callers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol


@dataclass(frozen=True)
class StageReview:
    """A completed LLM stage that may require human release before continuing."""

    stage: str
    payload: Dict[str, Any]


class StageConfirmation(Protocol):
    """Interface used by analysis pipelines to request release of completed stages."""

    def should_continue(self, review: StageReview) -> bool:
        ...


class ContinueStageConfirmation:
    """Non-interactive adapter: every completed stage is automatically released."""

    def should_continue(self, review: StageReview) -> bool:
        return True


class CallbackStageConfirmation:
    """Adapter for UI or test callbacks that already expose stage/payload arguments."""

    def __init__(self, callback: Callable[[str, Dict[str, Any]], bool]):
        self.callback = callback

    def should_continue(self, review: StageReview) -> bool:
        return bool(self.callback(review.stage, review.payload))


class StageConfirmationStopped(RuntimeError):
    """Raised when a caller declines to continue after reviewing a stage."""


def resolve_stage_confirmation(config: Optional[Dict[str, Any]]) -> StageConfirmation:
    config = config or {}
    configured = config.get("_stage_confirmation")
    if configured and hasattr(configured, "should_continue"):
        return configured

    legacy_callback = config.get("_stage_confirmation_callback")
    if callable(legacy_callback):
        return CallbackStageConfirmation(legacy_callback)

    return ContinueStageConfirmation()
