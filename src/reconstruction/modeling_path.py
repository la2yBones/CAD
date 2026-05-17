#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Choose the final modeling path from structured intelligent-analysis output."""
from __future__ import annotations

from typing import Any, Dict


PLANAR_EXTRUDE = "planar_extrude"
SEMANTIC_RECONSTRUCTION = "semantic_reconstruction"


def choose_modeling_path(
    view_analysis: Dict[str, Any],
    part_semantics: Dict[str, Any],
) -> Dict[str, str]:
    """Return a stable routing decision from already adjudicated semantics."""
    if view_analysis.get("drawing_type") != "single_view":
        return _decision(SEMANTIC_RECONSTRUCTION, "视图类型不是单视图")

    if part_semantics.get("uncertainties"):
        return _decision(SEMANTIC_RECONSTRUCTION, "零件语义仍存在未决事项")

    base_features = list(part_semantics.get("base_features", []) or [])
    if len(base_features) != 1:
        return _decision(SEMANTIC_RECONSTRUCTION, "基础特征数量不是单一轮廓")

    base_kind = base_features[0].get("kind")
    if base_kind not in {"profile_extrusion", "plate"}:
        return _decision(SEMANTIC_RECONSTRUCTION, f"基础特征 {base_kind or 'unknown'} 不属于平面拉伸")

    if part_semantics.get("additive_features"):
        return _decision(SEMANTIC_RECONSTRUCTION, "存在需要额外重建的增材特征")

    coordinate_system = part_semantics.get("coordinate_system", {}) or {}
    if coordinate_system.get("profile_plane") == "unknown":
        return _decision(SEMANTIC_RECONSTRUCTION, "轮廓平面未知")
    if coordinate_system.get("depth_axis") == "unknown":
        return _decision(SEMANTIC_RECONSTRUCTION, "拉伸方向未知")

    return _decision(PLANAR_EXTRUDE, "单一轮廓可由平面拉伸表达")


def _decision(path: str, reason: str) -> Dict[str, str]:
    return {"modeling_path": path, "reason": reason}
