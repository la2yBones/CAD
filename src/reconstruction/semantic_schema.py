#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构化零件语义的 Schema 辅助工具。"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


PART_SEMANTICS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "part_type",
        "confidence",
        "summary",
        "evidence",
        "candidate_interpretations",
        "coordinate_system",
        "dimension_source",
        "base_features",
        "additive_features",
        "subtractive_features",
        "key_dimensions",
        "uncertainties",
        "warnings",
    ],
}


class PartSemanticsValidator:
    """语义交接阶段的轻量校验器。"""

    REQUIRED_LIST_FIELDS = (
        "base_features",
        "additive_features",
        "subtractive_features",
        "key_dimensions",
        "uncertainties",
        "warnings",
        "candidate_interpretations",
        "evidence",
    )

    def validate(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None = None,
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        if not isinstance(result, dict):
            return False, ["part_semantics 必须是对象"]

        for field in PART_SEMANTICS_SCHEMA["required"]:
            if field not in result:
                errors.append(f"缺少字段: {field}")

        for field in self.REQUIRED_LIST_FIELDS:
            if field in result and not isinstance(result.get(field), list):
                errors.append(f"{field} 必须是列表")

        coordinate_system = result.get("coordinate_system")
        if coordinate_system is not None and not isinstance(coordinate_system, dict):
            errors.append("coordinate_system 必须是对象")

        dimension_source = result.get("dimension_source")
        if dimension_source not in ("annotation", "geometry", "unresolved"):
            errors.append("dimension_source 必须是 annotation、geometry 或 unresolved")

        confidence = result.get("confidence")
        if confidence is not None:
            if not isinstance(confidence, (int, float)):
                errors.append("confidence 必须是数值")
            elif not 0.0 <= float(confidence) <= 1.0:
                errors.append("confidence 必须介于 0 到 1 之间")

        if reconstruction_context and dimension_source == "annotation":
            annotation_values = self._annotation_values(reconstruction_context)
            key_dimension_values = self._key_dimension_values(result)
            unexpected_values = sorted(
                value for value in key_dimension_values
                if not self._matches_annotation_value(value, annotation_values)
            )
            if unexpected_values:
                errors.append(
                    "声明按标注建模时，key_dimensions 只能使用标注值；"
                    f"发现非标注值: {unexpected_values}"
                )

        return not errors, errors

    @staticmethod
    def _annotation_values(reconstruction_context: Dict[str, Any]) -> List[float]:
        values: List[float] = []
        for dimension in reconstruction_context.get("dimensions", []) or []:
            value = dimension.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def _key_dimension_values(result: Dict[str, Any]) -> List[float]:
        values: List[float] = []
        for dimension in result.get("key_dimensions", []) or []:
            value = dimension.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def _matches_annotation_value(value: float, annotation_values: List[float]) -> bool:
        return any(abs(value - annotated) <= 1e-6 for annotated in annotation_values)
