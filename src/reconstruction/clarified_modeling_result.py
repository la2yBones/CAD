#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户澄清后的建模结果装配。"""
from __future__ import annotations

from typing import Any, Callable, Dict

from .clarification import ClarificationOutlet
from .clarification_response import ClarificationResponse
from .modeling_path import ModelingPathDecision


ModelingResultFactory = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


class ClarifiedModelingResultBuilder:
    """根据澄清后的语义和路径裁决装配建模结果。"""

    def __init__(
        self,
        *,
        clarification_outlet: ClarificationOutlet | None = None,
        semantic_min_confidence: float = 0.70,
    ) -> None:
        self.clarification_outlet = clarification_outlet or ClarificationOutlet()
        self.semantic_min_confidence = float(semantic_min_confidence)

    def build(
        self,
        *,
        clarification_response: ClarificationResponse,
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        build_modeling_result: ModelingResultFactory,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        if not self._is_semantic_confidence_sufficient(part_semantics):
            return (
                part_semantics,
                modeling_path_decision,
                self.build_blocked_modeling_result(part_semantics),
            )

        if self._needs_path_clarification(modeling_path_decision):
            if not clarification_response.user_modeling_hint:
                return (
                    part_semantics,
                    modeling_path_decision,
                    self.clarification_outlet.path_pending_result(
                        modeling_path_decision
                    ),
                )
            original_decision = modeling_path_decision
            modeling_path_decision = self.build_semantic_recovery_path_decision(
                original_decision
            )
            part_semantics = self.attach_semantic_recovery_context(
                part_semantics,
                original_decision,
            )

        modeling_result = build_modeling_result(part_semantics, modeling_path_decision)
        return part_semantics, modeling_path_decision, modeling_result

    def _is_semantic_confidence_sufficient(self, part_semantics: Dict[str, Any]) -> bool:
        confidence = float(part_semantics.get("confidence") or 0.0)
        return confidence >= self.semantic_min_confidence

    @staticmethod
    def _needs_path_clarification(modeling_path_decision: Dict[str, Any]) -> bool:
        return ModelingPathDecision.from_mapping(
            modeling_path_decision
        ).requires_clarification

    @staticmethod
    def build_blocked_modeling_result(part_semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_summary": part_semantics.get("summary", ""),
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": part_semantics.get("key_dimensions", []),
            "warnings": [
                "Part semantics confidence is insufficient; automatic modeling stopped.",
                *list(part_semantics.get("uncertainties", []) or []),
                *list(part_semantics.get("warnings", []) or []),
            ],
            "blocked_by_semantic_confidence": True,
        }

    @staticmethod
    def build_semantic_recovery_path_decision(
        original_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "modeling_path": "semantic_reconstruction",
            "reason": (
                "专用路径契约仍缺少字段，但用户已提供补充建模提示；"
                "改交由语义重建路径结合图纸上下文继续尝试"
            ),
            "candidate_paths": original_decision.get("candidate_paths", []),
            "fallback_from_path_clarification": True,
            "original_modeling_path_decision": original_decision,
        }

    @staticmethod
    def attach_semantic_recovery_context(
        part_semantics: Dict[str, Any],
        original_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = ModelingPathDecision.from_mapping(original_decision)

        updated = dict(part_semantics)
        updated["path_clarification_fallback"] = {
            "reason": (
                "专用路径契约仍缺少字段，但用户已提供补充建模提示，"
                "已改交由语义重建路径继续尝试"
            ),
            "missing_fields": decision.missing_contract_fields,
            "clarification_questions": original_decision.get(
                "clarification_questions",
                [],
            ),
            "original_modeling_path": decision.path_requiring_clarification,
        }
        return updated
