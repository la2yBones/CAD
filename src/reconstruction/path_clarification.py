#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clarification helpers for specialized modeling path contracts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping

from .clarification_response import ClarificationResponse


def build_path_contract_pending_result(modeling_path_decision: Dict[str, Any]) -> Dict[str, Any]:
    """Build a modeling result that pauses execution for path-contract clarification."""
    return {
        "analysis_summary": "",
        "modeling_strategy": "",
        "freecad_script": "",
        "instructions": [],
        "key_dimensions": [],
        "warnings": [
            "specialized modeling path semantics are incomplete; waiting for clarification"
        ],
        "blocked_by_clarification": True,
        "blocked_by_path_contract": True,
        "clarification_questions": modeling_path_decision.get("clarification_questions", []),
    }


def needs_path_clarification(modeling_path_decision: Dict[str, Any]) -> bool:
    """Return whether the path decision must pause for user clarification."""
    return bool(
        modeling_path_decision.get("blocked_by_path_contract")
        or modeling_path_decision.get("requires_path_preference")
    )


def build_path_clarification_payload(
    *,
    modeling_result: Dict[str, Any],
    base_context: Dict[str, Any],
    policy_result: Dict[str, Any],
    adjudicated_context: Dict[str, Any],
    part_semantics: Dict[str, Any],
    modeling_path_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach path-layer recovery state to a pending reconstruction result."""
    if not modeling_result.get("blocked_by_path_contract"):
        return {}
    context = deepcopy(base_context)
    context.update({
        "clarification_stage": "modeling_path",
        "semantic_policy": policy_result,
        "adjudicated_context": adjudicated_context,
        "part_semantics": part_semantics,
        "modeling_path_decision": modeling_path_decision,
    })
    return {"clarification_context": context}


def apply_path_clarification_answers(
    part_semantics: Dict[str, Any],
    clarification_answers: Mapping[str, Any] | ClarificationResponse,
) -> Dict[str, Any]:
    """Write path-layer clarification answers back into explicit part semantics."""
    response = ClarificationResponse.from_input(
        clarification_answers,
        source_stage="modeling_path",
    )
    updated = deepcopy(part_semantics)
    planar = updated.setdefault("planar_modeling_semantics", {})
    if "provide_extrusion_depth" in response:
        planar["extrusion_depth"] = _parse_numeric_answer(
            response.get("provide_extrusion_depth")
        )
    if "provide_extrusion_direction" in response:
        planar["extrusion_direction"] = response.get("provide_extrusion_direction")
    if "select_modeling_path" in response:
        updated["preferred_modeling_path"] = response.get("select_modeling_path")
    if response.user_modeling_hint:
        updated["user_modeling_hint"] = response.user_modeling_hint
        updated["user_modeling_hint_policy"] = response.conflict_policy
    return updated


def _parse_numeric_answer(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return value
