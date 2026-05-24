#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the narrow LLM payload for FreeCAD modeling instruction generation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from .semantic_adjudication_view import SemanticAdjudicationView


class ModelingTaskBuilder:
    """Convert semantic reconstruction outputs into a stage-specific task payload."""

    TASK_VERSION = "modeling_task_v1"

    def build(
        self,
        *,
        part_semantics: Optional[Dict[str, Any]] = None,
        reconstruction_context: Optional[Dict[str, Any]] = None,
        modeling_path_decision: Optional[Dict[str, Any]] = None,
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        semantics = part_semantics or {}
        context = reconstruction_context or {}
        policy = context.get("semantic_policy", {}) or {}

        return {
            "task_version": self.TASK_VERSION,
            "object": self._build_object(semantics, modeling_path_decision),
            "features": self._build_features(semantics),
            "dimensions": self._build_dimensions(semantics, policy),
            "constraints": self._build_constraints(policy, modeling_path_decision),
            "recovery_hints": self._build_recovery_hints(
                semantics,
                context,
                policy,
                recovery_context,
            ),
        }

    @staticmethod
    def _build_object(
        semantics: Dict[str, Any],
        modeling_path_decision: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        decision = modeling_path_decision or {}
        return {
            "part_type": semantics.get("part_type", "unknown"),
            "summary": semantics.get("summary", ""),
            "confidence": semantics.get("confidence"),
            "coordinate_system": deepcopy(semantics.get("coordinate_system", {})),
            "preferred_modeling_path": semantics.get("preferred_modeling_path"),
            "selected_modeling_path": decision.get("modeling_path"),
            "modeling_path_reason": decision.get("reason", ""),
        }

    @staticmethod
    def _build_features(semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "base": deepcopy(semantics.get("base_features", []) or []),
            "additive": deepcopy(semantics.get("additive_features", []) or []),
            "subtractive": deepcopy(semantics.get("subtractive_features", []) or []),
            "planar_modeling": deepcopy(semantics.get("planar_modeling_semantics")),
            "revolve_modeling": deepcopy(semantics.get("revolve_modeling_semantics")),
            "key_dimensions": deepcopy(semantics.get("key_dimensions", []) or []),
        }

    @staticmethod
    def _build_dimensions(
        semantics: Dict[str, Any],
        semantic_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        dimension_plan = semantic_policy.get("dimension_plan", {}) or {}
        adjudication_view = SemanticAdjudicationView.from_policy(semantic_policy)
        payload = {
            "dimension_source": (
                semantic_policy.get("dimension_source")
                or semantics.get("dimension_source")
            ),
            "semantic_adjudication": adjudication_view.to_dict(),
        }
        if adjudication_view.is_successful:
            payload["modeling_dimensions"] = adjudication_view.modeling_dimensions
            return payload
        payload.update({
            "allowed_dimensions": deepcopy(
                dimension_plan.get("allowed_dimensions", []) or []
            ),
            "construction_dimensions": deepcopy(
                dimension_plan.get("construction_dimensions", []) or []
            ),
            "unresolved_dimensions": deepcopy(
                dimension_plan.get("unresolved_dimensions", []) or []
            ),
            "excluded_dimensions": deepcopy(
                dimension_plan.get("excluded_dimensions", []) or []
            ),
            "rules": deepcopy(dimension_plan.get("rules", []) or []),
        })
        return payload

    @staticmethod
    def _build_constraints(
        semantic_policy: Dict[str, Any],
        modeling_path_decision: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        decision = modeling_path_decision or {}
        return {
            "feature_constraints": deepcopy(
                semantic_policy.get("feature_constraints", {}) or {}
            ),
            "assumptions": deepcopy(semantic_policy.get("assumptions", []) or []),
            "modeling_path_decision": {
                "modeling_path": decision.get("modeling_path"),
                "reason": decision.get("reason", ""),
                "fallback_from_path_clarification": bool(
                    decision.get("fallback_from_path_clarification")
                ),
            },
            "partial_modeling_policy": {
                "complete_main_body_first": True,
                "record_detail_failures_as_skipped_features": True,
                "record_only_confirmed_required_detail_failures_as_skipped_features": True,
                "speculative_or_unannotated_details_go_to_warnings": True,
                "do_not_use_unresolved_dimensions_for_key_geometry": True,
            },
            "forbidden_inputs": [
                "raw geometry entities",
                "view entity lists",
                "local geometry relationship pairs",
                "full reconstruction context",
                "full part semantics object",
            ],
        }

    @staticmethod
    def _build_recovery_hints(
        semantics: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
        semantic_policy: Dict[str, Any],
        recovery_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "user_modeling_hint": (
                reconstruction_context.get("user_modeling_hint")
                or semantic_policy.get("user_modeling_hint")
                or semantics.get("user_modeling_hint")
                or ""
            ),
            "user_modeling_hint_policy": (
                reconstruction_context.get("user_modeling_hint_policy")
                or semantic_policy.get("user_modeling_hint_policy")
                or semantics.get("user_modeling_hint_policy")
                or "drawing_facts_override_user_hint"
            ),
            "path_clarification_fallback": deepcopy(
                semantics.get("path_clarification_fallback")
            ),
            "uncertainties": deepcopy(semantics.get("uncertainties", []) or []),
            "warnings": deepcopy(semantics.get("warnings", []) or []),
            "previous_partial_result": deepcopy(recovery_context or {}),
        }
