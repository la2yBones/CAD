#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standard schema and validation helpers for engineering view analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging
import re
import uuid

logger = logging.getLogger(__name__)


DRAWING_TYPES = {
    "single_view",
    "two_view",
    "three_view",
    "assembly_drawing",
    "section_view",
    "unknown",
}

VIEW_NAMES = {"single", "main", "top", "bottom", "left", "right", "section", "detail", "unknown"}
RELATIONSHIP_TYPES = {"projection", "section", "detail", "assembly", "alignment", "unknown"}
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0
DEFAULT_ACCEPT_CONFIDENCE = 0.60


VIEW_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": True,
    "required": [
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
    "properties": {
        "analysis_id": {"type": "string"},
        "timestamp": {"type": "string"},
        "drawing_type": {"type": "string", "enum": sorted(DRAWING_TYPES)},
        "views": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["object_id", "name", "label", "bbox", "confidence"],
                "properties": {
                    "object_id": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "enum": sorted(VIEW_NAMES)},
                    "label": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "number"},
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": MIN_CONFIDENCE,
                        "maximum": MAX_CONFIDENCE,
                    },
                    "entity_count": {"type": "integer", "minimum": 0},
                    "source": {"type": "string"},
                },
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["object_id", "type", "views", "confidence"],
                "properties": {
                    "object_id": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": sorted(RELATIONSHIP_TYPES)},
                    "views": {"type": "array", "items": {"type": "string"}},
                    "confidence": {
                        "type": "number",
                        "minimum": MIN_CONFIDENCE,
                        "maximum": MAX_CONFIDENCE,
                    },
                    "evidence": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number", "minimum": MIN_CONFIDENCE, "maximum": MAX_CONFIDENCE},
        "evidence": {"type": "array"},
        "reason_summary": {"type": "string"},
        "warnings": {"type": "array"},
    },
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_analysis_id() -> str:
    return f"view_{uuid.uuid4().hex[:12]}"


def normalize_bbox(raw_bbox: Any) -> Optional[List[float]]:
    if raw_bbox is None:
        return None
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in raw_bbox]
    except (TypeError, ValueError):
        return None
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return [x1, y1, x2, y2]


def build_standard_view_analysis(
    rule_result: Dict[str, Any],
    drawing_type: Optional[str] = None,
    confidence: float = 0.75,
    reason_summary: str = "由本地规则分析生成",
    evidence: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    source: str = "rule",
) -> Dict[str, Any]:
    views = []
    for index, view in enumerate(rule_result.get("views", []) or []):
        bbox = normalize_bbox(view.get("bbox"))
        views.append({
            "object_id": str(view.get("object_id") or f"view_{index + 1}"),
            "name": view.get("name", "unknown"),
            "label": view.get("type") or view.get("label") or view.get("name", "unknown"),
            "bbox": bbox or [0.0, 0.0, 0.0, 0.0],
            "confidence": float(view.get("confidence", confidence)),
            "entity_count": int(view.get("entity_count", len(view.get("entities", []) or []))),
            "source": source,
        })

    relationships = []
    for index, rel in enumerate(rule_result.get("relationships", []) or []):
        relationships.append({
            "object_id": str(rel.get("object_id") or f"rel_{index + 1}"),
            "type": rel.get("type", "unknown"),
            "views": list(rel.get("views", []) or []),
            "confidence": float(rel.get("confidence", confidence)),
            "evidence": rel.get("description") or rel.get("evidence") or "",
        })

    inferred_type = drawing_type or infer_drawing_type(views, rule_result)
    return {
        "analysis_id": str(rule_result.get("analysis_id") or new_analysis_id()),
        "timestamp": str(rule_result.get("timestamp") or utc_timestamp()),
        "drawing_type": inferred_type,
        "views": views,
        "relationships": relationships,
        "confidence": float(confidence),
        "evidence": evidence or [f"本地检测方法: {rule_result.get('detection_method', 'unknown')}"],
        "reason_summary": reason_summary,
        "warnings": warnings or [],
        "schema_version": "view_analysis_v1",
        "source": source,
        "rule_detection_method": rule_result.get("detection_method", "unknown"),
    }


def infer_drawing_type(views: List[Dict[str, Any]], rule_result: Dict[str, Any]) -> str:
    names = {view.get("name") for view in views}
    if names == {"single"}:
        label_text = " ".join(str(view.get("label", "")) for view in views)
        if "装配" in label_text:
            return "assembly_drawing"
        return "single_view"
    if len(views) == 2:
        return "two_view"
    if len(views) >= 3:
        return "three_view"
    return "unknown"


class ViewAnalysisValidator:
    """校验 LLM 校正后的视图分析，并拒绝不安全输出。"""

    def __init__(self, confidence_threshold: float = DEFAULT_ACCEPT_CONFIDENCE):
        self.confidence_threshold = confidence_threshold

    def validate(
        self,
        result: Dict[str, Any],
        geometry_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        errors.extend(self._validate_schema(result))
        errors.extend(self._validate_business_rules(result, geometry_data))
        errors.extend(self._detect_adversarial_content(result))
        return not errors, errors

    def _validate_schema(self, result: Dict[str, Any]) -> List[str]:
        try:
            from jsonschema import Draft202012Validator

            validator = Draft202012Validator(VIEW_ANALYSIS_SCHEMA)
            schema_errors = sorted(validator.iter_errors(result), key=lambda e: list(e.path))
            if schema_errors:
                return [
                    f"JSON Schema校验失败: {'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
                    for error in schema_errors
                ]
        except ImportError:
            logger.warning("jsonschema未安装，使用内置轻量校验")

        errors: List[str] = []
        if not isinstance(result, dict):
            return ["分析结果必须是JSON对象"]

        for field in VIEW_ANALYSIS_SCHEMA["required"]:
            if field not in result:
                errors.append(f"缺少必填字段: {field}")

        drawing_type = result.get("drawing_type")
        if drawing_type not in DRAWING_TYPES:
            errors.append(f"drawing_type不合法: {drawing_type}")

        confidence = result.get("confidence")
        if not isinstance(confidence, (int, float)):
            errors.append("confidence必须是数字")
        elif not MIN_CONFIDENCE <= float(confidence) <= MAX_CONFIDENCE:
            errors.append("confidence必须在0到1之间")
        elif float(confidence) < self.confidence_threshold:
            errors.append(f"confidence低于阈值: {confidence} < {self.confidence_threshold}")

        if not isinstance(result.get("views"), list) or not result.get("views"):
            errors.append("views必须是非空数组")

        for index, view in enumerate(result.get("views", []) or []):
            prefix = f"views[{index}]"
            if not isinstance(view, dict):
                errors.append(f"{prefix}必须是对象")
                continue
            if not view.get("object_id"):
                errors.append(f"{prefix}.object_id不能为空")
            if view.get("name") not in VIEW_NAMES:
                errors.append(f"{prefix}.name不合法: {view.get('name')}")
            if normalize_bbox(view.get("bbox")) is None:
                errors.append(f"{prefix}.bbox必须是[x1,y1,x2,y2]")
            if not isinstance(view.get("confidence"), (int, float)):
                errors.append(f"{prefix}.confidence必须是数字")

        relationships = result.get("relationships", [])
        if not isinstance(relationships, list):
            errors.append("relationships必须是数组")
        for index, rel in enumerate(relationships or []):
            prefix = f"relationships[{index}]"
            if not isinstance(rel, dict):
                errors.append(f"{prefix}必须是对象")
                continue
            if rel.get("type") not in RELATIONSHIP_TYPES:
                errors.append(f"{prefix}.type不合法: {rel.get('type')}")
            if not isinstance(rel.get("views"), list):
                errors.append(f"{prefix}.views必须是数组")
            if not isinstance(rel.get("confidence"), (int, float)):
                errors.append(f"{prefix}.confidence必须是数字")

        for field in ("evidence", "warnings"):
            if field in result and not isinstance(result[field], list):
                errors.append(f"{field}必须是数组")

        if "reason_summary" in result and not isinstance(result["reason_summary"], str):
            errors.append("reason_summary必须是字符串")

        return errors

    def _validate_business_rules(
        self,
        result: Dict[str, Any],
        geometry_data: Optional[Dict[str, Any]]
    ) -> List[str]:
        errors: List[str] = []
        views = result.get("views", []) or []
        drawing_type = result.get("drawing_type")

        expected_counts = {
            "single_view": {1},
            "assembly_drawing": {1},
            "two_view": {2},
            "three_view": {3},
        }
        if drawing_type in expected_counts and len(views) not in expected_counts[drawing_type]:
            errors.append(f"{drawing_type}的视图数量不匹配: {len(views)}")

        if geometry_data:
            drawing_bbox = self._geometry_bbox(geometry_data)
            if drawing_bbox:
                for index, view in enumerate(views):
                    bbox = normalize_bbox(view.get("bbox"))
                    if bbox and not self._bbox_within_reasonable_range(bbox, drawing_bbox):
                        errors.append(f"views[{index}].bbox超出图纸合理范围")

        return errors

    def _detect_adversarial_content(self, result: Dict[str, Any]) -> List[str]:
        text = str(result)
        suspicious_patterns = [
            r"ignore\s+previous",
            r"system\s+prompt",
            r"api[_ -]?key",
            r"sk-[A-Za-z0-9]",
            r"exec\(",
            r"subprocess",
            r"powershell",
            r"cmd\.exe",
        ]
        errors = []
        for pattern in suspicious_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                errors.append(f"检测到可疑输出内容: {pattern}")
        return errors

    def _geometry_bbox(self, geometry_data: Dict[str, Any]) -> Optional[List[float]]:
        coords: List[Tuple[float, float]] = []

        def add_point(raw_point: Any) -> None:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                return
            try:
                coords.append((float(raw_point[0]), float(raw_point[1])))
            except (TypeError, ValueError):
                return

        for entity in geometry_data.get("entities", []) or []:
            etype = entity.get("type")
            if etype == "LINE":
                add_point(entity.get("start"))
                add_point(entity.get("end"))
            elif etype in ("CIRCLE", "ARC"):
                center = entity.get("center", [0, 0])
                radius = float(entity.get("radius", 0) or 0)
                if isinstance(center, (list, tuple)) and len(center) >= 2:
                    coords.extend([
                        (float(center[0]) - radius, float(center[1]) - radius),
                        (float(center[0]) + radius, float(center[1]) + radius),
                    ])
            elif etype in ("LWPOLYLINE", "ELLIPSE", "SPLINE"):
                for vertex in entity.get("vertices", []):
                    add_point(vertex)
            elif etype in ("TEXT", "MTEXT"):
                add_point(entity.get("position"))

        if not coords:
            return None
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return [min(xs), min(ys), max(xs), max(ys)]

    def _bbox_within_reasonable_range(self, bbox: List[float], drawing_bbox: List[float]) -> bool:
        x1, y1, x2, y2 = drawing_bbox
        width = max(x2 - x1, 1.0)
        height = max(y2 - y1, 1.0)
        margin_x = width * 0.25
        margin_y = height * 0.25
        return (
            x1 - margin_x <= bbox[0] <= x2 + margin_x and
            x1 - margin_x <= bbox[2] <= x2 + margin_x and
            y1 - margin_y <= bbox[1] <= y2 + margin_y and
            y1 - margin_y <= bbox[3] <= y2 + margin_y
        )
