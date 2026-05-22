#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""View decision payload builder for LLM view semantic correction."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def build_view_decision_payload(
    *,
    geometry_data: Dict[str, Any],
    rule_result: Dict[str, Any],
    rule_standard: Dict[str, Any],
    dimension_data: Optional[Dict[str, Any]] = None,
    file_path: Optional[str] = None,
    confidence_threshold: float = 0.60,
) -> Dict[str, Any]:
    """Build the stage-specific payload for view semantic correction."""
    return {
        "task": "校正CAD工程图视图识别结果",
        "file_hint": _build_file_hint(file_path),
        "local_rule_summary": _summarize_rule_result(rule_result, rule_standard),
        "layout_summary": _summarize_layout(geometry_data),
        "candidate_views": [
            _summarize_candidate_view(view)
            for view in rule_result.get("views", []) or []
            if isinstance(view, dict)
        ],
        "projection_evidence": _summarize_projection_evidence(rule_result),
        "dimension_summary": _summarize_dimensions(dimension_data or {}),
        "output_contract": {
            "required_fields": [
                "analysis_id",
                "timestamp",
                "drawing_type",
                "views",
                "relationships",
                "confidence",
                "evidence",
                "reason_summary",
                "warnings",
            ],
            "drawing_type_values": [
                "single_view",
                "two_view",
                "three_view",
                "assembly_drawing",
                "section_view",
                "unknown",
            ],
            "view_required_fields": [
                "object_id",
                "name",
                "label",
                "bbox",
                "confidence",
            ],
            "relationship_required_fields": [
                "object_id",
                "type",
                "views",
                "confidence",
            ],
            "confidence_threshold": confidence_threshold,
            "file_hint_policy": "文件名只能作为弱提示，不得覆盖几何布局证据",
            "reasoning_policy": "不要输出完整推理链，只输出简短reason_summary和evidence",
            "format": "只输出一个JSON对象，不要Markdown",
        },
    }


def _build_file_hint(file_path: Optional[str]) -> Dict[str, Any]:
    if not file_path:
        return {"name": None, "policy": "missing"}
    return {
        "name": Path(file_path).name,
        "policy": "weak_evidence_only",
    }


def _summarize_rule_result(
    rule_result: Dict[str, Any],
    rule_standard: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "detection_method": rule_result.get("detection_method"),
        "drawing_type": (
            rule_standard.get("drawing_type")
            or rule_result.get("drawing_type")
            or rule_result.get("type")
        ),
        "confidence": rule_standard.get("confidence"),
        "view_count": len(rule_result.get("views", []) or []),
        "relationship_count": len(rule_result.get("relationships", []) or []),
        "total_entities": rule_result.get("total_entities"),
        "reason_summary": rule_standard.get("reason_summary", ""),
        "warnings": list(rule_standard.get("warnings", []) or []),
    }


def _summarize_layout(geometry_data: Dict[str, Any]) -> Dict[str, Any]:
    entities = geometry_data.get("entities", []) or []
    return {
        "version": geometry_data.get("version"),
        "units": geometry_data.get("units"),
        "entity_count": len(entities),
        "type_count": _count_by_key(entities, "type", "unknown"),
        "layer_count": _count_by_key(entities, "layer", "default"),
        "drawing_bbox": _drawing_bbox(entities),
    }


def _summarize_candidate_view(view: Dict[str, Any]) -> Dict[str, Any]:
    entities = view.get("entities", []) or []
    summary = {
        "name": view.get("name"),
        "label": view.get("type") or view.get("label"),
        "bbox": view.get("bbox"),
        "centroid": view.get("centroid"),
        "entity_count": view.get("entity_count", len(entities)),
        "layers": view.get("layers", []),
    }
    if entities:
        summary["type_count"] = _count_by_key(entities, "type", "unknown")
    return summary


def _summarize_projection_evidence(rule_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    evidence = []
    for index, rel in enumerate(rule_result.get("relationships", []) or [], start=1):
        if not isinstance(rel, dict):
            continue
        evidence.append({
            "id": rel.get("object_id") or f"relationship_{index}",
            "type": rel.get("type", "unknown"),
            "views": rel.get("views", []),
            "description": rel.get("description") or rel.get("evidence") or "",
            "confidence": rel.get("confidence"),
        })
    return evidence


def _summarize_dimensions(dimension_data: Dict[str, Any]) -> Dict[str, Any]:
    dimensions = dimension_data.get("dimensions", []) or []
    return {
        "dimension_count": len(dimensions),
        "dimensions": [
            _summarize_dimension(dimension)
            for dimension in dimensions[:20]
            if isinstance(dimension, dict)
        ],
        "statistics": dimension_data.get("statistics", {}),
    }


def _summarize_dimension(dimension: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: dimension.get(key)
        for key in (
            "text",
            "value",
            "type",
            "position",
            "bbox",
            "anchor",
            "nearest_view",
            "region",
        )
        if key in dimension
    }


def _count_by_key(items: list[Dict[str, Any]], key: str, default: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        value = str(item.get(key, default))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _drawing_bbox(entities: list[Dict[str, Any]]) -> Optional[list[float]]:
    xs = []
    ys = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        for key in ("start", "end", "center", "position"):
            point = entity.get(key)
            _append_point(point, xs, ys)
        for vertex in entity.get("vertices", []) or []:
            _append_point(vertex, xs, ys)
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _append_point(point: Any, xs: list[float], ys: list[float]) -> None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return
    try:
        xs.append(float(point[0]))
        ys.append(float(point[1]))
    except (TypeError, ValueError):
        return
