#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executable contracts for specialized modeling paths."""
from __future__ import annotations

from typing import Any, Dict, List

from .clarification_helpers import clarification_question, choice_option


PLANAR_EXTRUDE = "planar_extrude"
REVOLVE = "revolve"


def build_planar_modeling_semantics(part_semantics: Dict[str, Any]) -> Dict[str, Any]:
    """Return explicit planar semantics; missing fields must stay visible to the contract."""
    explicit = part_semantics.get("planar_modeling_semantics")
    if isinstance(explicit, dict):
        return explicit

    return {
        "profile": None,
        "extrusion_direction": "unknown",
        "extrusion_depth": None,
        "cut_features": [],
        "dimension_bindings": [],
        "uncertainties": ["planar_modeling_semantics_missing"],
    }


def evaluate_planar_extrude_contract(
    view_analysis: Dict[str, Any],
    part_semantics: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate whether planar extrusion is semantically closed and executable."""
    semantics = build_planar_modeling_semantics(part_semantics)
    missing_fields: List[str] = []
    rejection_reasons: List[str] = []

    if view_analysis.get("drawing_type") != "single_view":
        rejection_reasons.append("drawing_type_not_single_view")

    base_features = list(part_semantics.get("base_features", []) or [])
    if len(base_features) != 1:
        rejection_reasons.append("base_feature_count_not_one")
    elif base_features[0].get("kind") not in {"profile_extrusion", "plate"}:
        rejection_reasons.append("base_feature_not_planar")

    if part_semantics.get("additive_features"):
        rejection_reasons.append("has_additive_features")

    coordinate_system = part_semantics.get("coordinate_system", {}) or {}
    if coordinate_system.get("profile_plane") in (None, "", "unknown"):
        missing_fields.append("profile_plane")
    if semantics.get("extrusion_direction") in (None, "", "unknown"):
        missing_fields.append("extrusion_direction")
    if not semantics.get("profile"):
        missing_fields.append("profile")
    if semantics.get("extrusion_depth") in (None, ""):
        missing_fields.append("extrusion_depth")
    if semantics.get("uncertainties"):
        rejection_reasons.append("has_uncertainties")

    semantic_closed = not missing_fields and not rejection_reasons
    return {
        "path": PLANAR_EXTRUDE,
        "implemented": True,
        "eligible": semantic_closed,
        "semantic_closed": semantic_closed,
        "missing_fields": missing_fields,
        "rejection_reasons": rejection_reasons,
        "semantics": semantics,
    }


def evaluate_revolve_contract(
    view_analysis: Dict[str, Any],
    part_semantics: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a future deterministic revolve path without claiming execution support."""
    semantics = part_semantics.get("revolve_modeling_semantics")
    if not isinstance(semantics, dict):
        semantics = {
            "axis_point": None,
            "axis_direction": None,
            "profile_points": None,
            "angle_degrees": None,
            "uncertainties": ["revolve_modeling_semantics_missing"],
        }

    missing_fields: List[str] = []
    rejection_reasons: List[str] = []
    if not _is_point3(semantics.get("axis_point")):
        missing_fields.append("axis_point")
    if not _is_point3(semantics.get("axis_direction")):
        missing_fields.append("axis_direction")
    if not _is_closed_profile_points(semantics.get("profile_points")):
        missing_fields.append("profile_points")
    if semantics.get("angle_degrees") in (None, ""):
        missing_fields.append("angle_degrees")
    if semantics.get("uncertainties"):
        rejection_reasons.append("has_uncertainties")

    semantic_closed = not missing_fields and not rejection_reasons
    return {
        "path": REVOLVE,
        "implemented": True,
        "eligible": semantic_closed,
        "semantic_closed": semantic_closed,
        "missing_fields": missing_fields,
        "rejection_reasons": rejection_reasons,
        "semantics": semantics,
    }


def build_planar_contract_clarification_questions(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build user questions for missing fields that block planar execution."""
    questions: List[Dict[str, Any]] = []
    missing_fields = set(contract.get("missing_fields", []) or [])
    if "extrusion_depth" in missing_fields:
        questions.append(clarification_question(
            question_id="provide_extrusion_depth",
            text="请补充这个零件的厚度或拉伸深度，例如 10mm。",
            kind="free_text",
            reason="缺少拉伸深度时，系统无法生成可靠的平面实体。",
            example="10mm、12.5，或“按标注 8”。",
        ))
    if "extrusion_direction" in missing_fields:
        questions.append(clarification_question(
            question_id="provide_extrusion_direction",
            text="请确认外轮廓应沿哪个方向拉伸成实体。",
            kind="single_choice",
            options=[
                choice_option("X 方向", "X"),
                choice_option("Y 方向", "Y"),
                choice_option("Z 方向", "Z"),
            ],
            reason="缺少拉伸方向时，系统无法确定外轮廓如何形成三维实体。",
            example="常见平面轮廓可选 Z 方向；若图纸另有说明，按图纸选择。",
        ))
    return questions


def _is_point3(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(item, (int, float)) for item in value)
    )


def _is_closed_profile_points(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 4
        and all(_is_point3(point) for point in value)
        and value[0] == value[-1]
    )
