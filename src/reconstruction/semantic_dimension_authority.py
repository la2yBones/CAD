#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零件语义校验的尺寸权限视图。"""
from __future__ import annotations

from typing import Any, Dict, List

from .semantic_adjudication_view import SemanticAdjudicationView


class SemanticDimensionAuthority:
    """解释零件语义可使用哪些尺寸值。"""

    def __init__(self, reconstruction_context: Dict[str, Any] | None = None):
        self._context = reconstruction_context or {}
        self._semantic_policy = self._context.get("semantic_policy", {}) or {}
        self._adjudication_view = SemanticAdjudicationView.from_policy(
            self._semantic_policy
        )
        self.allowed_values, self.construction_values = self._build_value_groups()

    @property
    def policy_dimension_source(self) -> str | None:
        value = self._semantic_policy.get("dimension_source")
        return value if value in ("annotation", "geometry", "unresolved") else None

    @property
    def has_authoritative_values(self) -> bool:
        return bool(self.allowed_values or self.construction_values)

    @property
    def annotation_values(self) -> List[float]:
        values: List[float] = []
        for dimension in self._context.get("dimensions", []) or []:
            value = dimension.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @property
    def permitted_annotation_values(self) -> List[float]:
        adjudicated_values = self.allowed_values + self.construction_values
        return adjudicated_values or self.annotation_values

    def unexpected_annotation_key_values(
        self,
        result: Dict[str, Any],
    ) -> List[float]:
        return sorted(
            value for value in self.key_dimension_values(result)
            if not self.matches_value(value, self.permitted_annotation_values)
        )

    def unauthorized_key_values(
        self,
        result: Dict[str, Any],
    ) -> List[float]:
        adjudicated_values = self.allowed_values + self.construction_values
        return sorted(
            value for value in self.key_dimension_values(result)
            if not self.matches_value(value, adjudicated_values)
        )

    def misnamed_construction_key_dimensions(
        self,
        result: Dict[str, Any],
    ) -> List[str]:
        misnamed: List[str] = []
        for dimension in result.get("key_dimensions", []) or []:
            value = dimension.get("value")
            name = str(dimension.get("name") or "").strip()
            if not isinstance(value, (int, float)) or not name:
                continue
            numeric_value = float(value)
            if self.matches_value(numeric_value, self.allowed_values):
                continue
            if not self.matches_value(numeric_value, self.construction_values):
                continue
            if self._is_forbidden_construction_key_name(name):
                misnamed.append(f"{name}={numeric_value:g}")
        return sorted(misnamed)

    def _build_value_groups(self) -> tuple[List[float], List[float]]:
        adjudication_allowed, adjudication_construction = (
            self._adjudication_view.adjudicated_value_groups()
        )
        if self._adjudication_view.is_successful:
            return adjudication_allowed, adjudication_construction

        policy_plan = self._semantic_policy.get("dimension_plan", {}) or {}
        allowed_values = self._dimension_plan_values(
            policy_plan,
            "allowed_dimensions",
        )
        construction_values = self._dimension_plan_values(
            policy_plan,
            "construction_dimensions",
        )
        allowed_values.extend(adjudication_allowed)
        construction_values.extend(adjudication_construction)
        return allowed_values, construction_values

    @staticmethod
    def key_dimension_values(result: Dict[str, Any]) -> List[float]:
        values: List[float] = []
        for dimension in result.get("key_dimensions", []) or []:
            value = dimension.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def matches_value(value: float, values: List[float]) -> bool:
        return any(abs(value - permitted) <= 1e-6 for permitted in values)

    @staticmethod
    def _dimension_plan_values(policy_plan: Dict[str, Any], field: str) -> List[float]:
        values: List[float] = []
        for dimension in policy_plan.get(field, []) or []:
            value = dimension.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def _is_forbidden_construction_key_name(name: str) -> bool:
        normalized = name.lower().replace("-", "_").replace(" ", "_")
        forbidden_names = {
            "total_length",
            "overall_length",
            "profile_length",
            "profile_height",
            "depth",
            "extrusion_depth",
            "hole_diameter",
            "flange_diameter",
            "across_flats",
            "across_corners",
        }
        return normalized in forbidden_names
