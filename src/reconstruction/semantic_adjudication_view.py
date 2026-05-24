#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only view over LLM semantic adjudication results."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping


class SemanticAdjudicationView:
    """Interpret semantic adjudication dictionaries behind a stable interface."""

    LIST_FIELDS = (
        "view_roles",
        "dimension_roles",
        "feature_roles",
        "derived_dimensions",
        "clarification_questions",
        "uncertainties",
        "warnings",
    )

    def __init__(self, data: Mapping[str, Any] | None):
        self._data = dict(data or {})

    @classmethod
    def from_policy(cls, semantic_policy: Mapping[str, Any] | None) -> "SemanticAdjudicationView":
        policy = semantic_policy or {}
        return cls(policy.get("semantic_adjudication"))

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
            exported.setdefault("source", "semantic_adjudication.dimension_roles")
            dimensions.append(exported)
        for item in self.derived_dimensions:
            exported = deepcopy(item)
            exported.setdefault("source", "semantic_adjudication.derived_dimensions")
            dimensions.append(exported)
        return dimensions

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
