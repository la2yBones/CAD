#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalized user response for clarification recovery."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


USER_MODELING_HINT_KEY = "user_modeling_hint"


@dataclass(frozen=True)
class ClarificationResponse:
    """Structured clarification answers plus optional natural-language modeling hint."""

    answers: dict[str, Any] = field(default_factory=dict)
    user_modeling_hint: str = ""
    source_stage: Optional[str] = None
    conflict_policy: str = "drawing_facts_override_user_hint"

    @classmethod
    def from_input(
        cls,
        value: "ClarificationResponse | Mapping[str, Any] | None",
        *,
        source_stage: Optional[str] = None,
    ) -> "ClarificationResponse":
        if isinstance(value, cls):
            if source_stage and not value.source_stage:
                return cls(
                    answers=dict(value.answers),
                    user_modeling_hint=value.user_modeling_hint,
                    source_stage=source_stage,
                    conflict_policy=value.conflict_policy,
                )
            return value
        raw = dict(value or {})
        hint = str(raw.pop(USER_MODELING_HINT_KEY, "") or "").strip()
        return cls(
            answers=raw,
            user_modeling_hint=hint,
            source_stage=source_stage,
        )

    def as_legacy_answers(self) -> dict[str, Any]:
        answers = dict(self.answers)
        if self.user_modeling_hint:
            answers[USER_MODELING_HINT_KEY] = self.user_modeling_hint
        return answers

    def has_any_input(self) -> bool:
        return bool(self.answers or self.user_modeling_hint)

    def get(self, key: str, default: Any = None) -> Any:
        if key == USER_MODELING_HINT_KEY:
            return self.user_modeling_hint or default
        return self.answers.get(key, default)

    def __contains__(self, key: str) -> bool:
        if key == USER_MODELING_HINT_KEY:
            return bool(self.user_modeling_hint)
        return key in self.answers
