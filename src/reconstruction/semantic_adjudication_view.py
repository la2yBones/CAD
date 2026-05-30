#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 语义裁决结果的只读视图。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping


class SemanticAdjudicationView:
    """在稳定接口后解释语义裁决字典。"""

    LIST_FIELDS = (
        "view_roles",
        "dimension_roles",
        "feature_roles",
        "derived_dimensions",
        "clarification_questions",
        "uncertainties",
        "warnings",
    )

    CONSTRUCTION_ROLES = {
        "construction",
        "feature_depth",
        "feature_height",
        "feature_total_height",
        "radius",
        "chamfer",
        "thread_length",
    }

    def __init__(
        self,
        data: Mapping[str, Any] | None,
        evidence_package: Mapping[str, Any] | None = None,
    ):
        self._data = dict(data or {})
        self._evidence_package = dict(evidence_package or {})

    @classmethod
    def from_policy(cls, semantic_policy: Mapping[str, Any] | None) -> "SemanticAdjudicationView":
        policy = semantic_policy or {}
        return cls(
            policy.get("semantic_adjudication"),
            policy.get("drawing_evidence_package"),
        )

    @property
    def is_successful(self) -> bool:
        return bool(self._data) and self._data.get("status") != "failed"

    @property
    def confidence(self) -> float:
        try:
            return float(self._data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def clarification_questions(self) -> List[Dict[str, Any]]:
        return self._list("clarification_questions")

    @property
    def uncertainties(self) -> List[Any]:
        return self._list("uncertainties")

    @property
    def warnings(self) -> List[Any]:
        return self._list("warnings")

    @property
    def confirmed_dimensions(self) -> List[Dict[str, Any]]:
        return [
            item for item in self._list("dimension_roles")
            if item.get("role") not in (None, "", "unresolved")
        ]

    @property
    def confirmed_features(self) -> List[Dict[str, Any]]:
        return [
            item for item in self._list("feature_roles")
            if item.get("role") not in (None, "", "unknown", "unresolved")
        ]

    @property
    def derived_dimensions(self) -> List[Dict[str, Any]]:
        return [
            item for item in self._list("derived_dimensions")
            if item.get("role") not in (None, "", "unresolved")
        ]

    @property
    def modeling_dimensions(self) -> List[Dict[str, Any]]:
        if not self.is_successful:
            return []
        dimensions: List[Dict[str, Any]] = []
        for item in self.confirmed_dimensions:
            exported = deepcopy(item)
            self._attach_candidate_value(
                exported,
                id_field="dimension_id",
                candidates_field="dimension_candidates",
            )
            exported.setdefault("source", "semantic_adjudication.dimension_roles")
            dimensions.append(exported)
        for item in self.derived_dimensions:
            exported = deepcopy(item)
            self._attach_candidate_value(
                exported,
                id_field="source_derived_dimension_id",
                candidates_field="derived_dimension_candidates",
            )
            exported.setdefault("source", "semantic_adjudication.derived_dimensions")
            dimensions.append(exported)
        return dimensions

    def adjudicated_value_groups(self) -> tuple[List[float], List[float]]:
        allowed: List[float] = []
        construction: List[float] = []
        for item in self.modeling_dimensions:
            value = item.get("value")
            role = str(item.get("role") or "")
            if not isinstance(value, (int, float)):
                continue
            target = construction if role in self.CONSTRUCTION_ROLES else allowed
            if not any(abs(float(value) - existing) <= 1e-6 for existing in target):
                target.append(float(value))
        return allowed, construction

    def has_dimension_role(self, role: str) -> bool:
        if not self.is_successful:
            return False
        return any(
            item.get("role") == role
            for item in [*self.confirmed_dimensions, *self.derived_dimensions]
        )

    def has_feature_role(self, role: str) -> bool:
        if not self.is_successful:
            return False
        return any(item.get("role") == role for item in self.confirmed_features)

    def has_role(self, role: str) -> bool:
        return self.has_dimension_role(role) or self.has_feature_role(role)

    def to_dict(self) -> Dict[str, Any]:
        result = deepcopy(self._data)
        result.setdefault("status", "completed" if self.is_successful else "failed")
        result.setdefault("confidence", self.confidence)
        for field in self.LIST_FIELDS:
            result.setdefault(field, [])
        return result

    def _list(self, field: str) -> List[Any]:
        value = self._data.get(field)
        return deepcopy(value) if isinstance(value, list) else []

    def _attach_candidate_value(
        self,
        item: Dict[str, Any],
        *,
        id_field: str,
        candidates_field: str,
    ) -> None:
        candidate_id = str(item.get(id_field) or "")
        candidate = self._candidate_by_id(candidates_field).get(candidate_id)
        if not candidate:
            return
        item.setdefault("value", candidate.get("value"))
        item.setdefault("text", candidate.get("text"))

    def _candidate_by_id(self, field: str) -> Dict[str, Dict[str, Any]]:
        return {
            str(item.get("id")): item
            for item in self._evidence_package.get(field, []) or []
            if item.get("id")
        }
