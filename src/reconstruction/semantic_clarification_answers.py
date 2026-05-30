#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply user clarification answers to semantic dimension bindings."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping

from .clarification import UNKNOWN_ANSWER
from .clarification_response import ClarificationResponse
from .dimension_permission_plan import DimensionPermissionPlan


FEATURE_DETAIL_DIMENSION_KEY = "bind_feature_detail_dimension"


class SemanticClarificationAnswerApplier:
    """Mutate dimension binding copies according to structured clarification answers."""

    def apply(
        self,
        bindings: List[Dict[str, Any]],
        clarification_answers: Mapping[str, Any] | ClarificationResponse,
    ) -> List[Dict[str, Any]]:
        response = ClarificationResponse.from_input(clarification_answers)
        resolved = deepcopy(bindings)
        answer_to_role = {
            "bind_profile_length": "profile_length",
            "bind_profile_height": "profile_height",
        }
        for question_id, role in answer_to_role.items():
            if question_id not in response:
                continue
            answer = response.get(question_id)
            if self._is_unknown_answer(answer):
                DimensionPermissionPlan.exclude_for_question(resolved, question_id)
                continue
            DimensionPermissionPlan.bind_selected_value(
                resolved,
                role=role,
                selected_value=answer,
            )

        if FEATURE_DETAIL_DIMENSION_KEY in response:
            DimensionPermissionPlan.apply_feature_detail_dimension_answer(
                resolved,
                response.get(FEATURE_DETAIL_DIMENSION_KEY),
            )

        for question_id, answer in response.answers.items():
            if not question_id.startswith("resolve_"):
                continue
            if self._is_unknown_answer(answer):
                DimensionPermissionPlan.exclude_for_question(resolved, question_id)
                continue
            role = question_id.removeprefix("resolve_")
            DimensionPermissionPlan.resolve_conflicting_role(
                resolved,
                role=role,
                selected_value=answer,
            )
        return resolved

    @staticmethod
    def _is_unknown_answer(value: Any) -> bool:
        if isinstance(value, dict):
            value = value.get("value")
        return str(value).strip() == UNKNOWN_ANSWER
