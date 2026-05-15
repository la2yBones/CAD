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

    def validate(self, result: Dict[str, Any]) -> Tuple[bool, List[str]]:
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

        confidence = result.get("confidence")
        if confidence is not None:
            if not isinstance(confidence, (int, float)):
                errors.append("confidence 必须是数值")
            elif not 0.0 <= float(confidence) <= 1.0:
                errors.append("confidence 必须介于 0 到 1 之间")

        return not errors, errors
