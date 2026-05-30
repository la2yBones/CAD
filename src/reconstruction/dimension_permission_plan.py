#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义重建的尺寸权限计划。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Sequence


@dataclass(frozen=True)
class DimensionPermissionPlan:
    """将尺寸绑定分类为建模权限池。"""

    bindings: Sequence[Dict[str, Any]]

    ALLOWED_ROLES = {
        "profile_length",
        "profile_height",
        "radius",
        "diameter",
        "thread_size",
        "thread_length",
        "chamfer",
        "feature_depth",
        "feature_height",
        "feature_total_height",
        "extrusion_depth",
        "projected_profile_horizontal_extent",
        "projected_profile_vertical_extent",
    }
    CONSTRUCTION_ROLES = {
        "profile_length_segment",
        "radius",
        "diameter",
        "thread_size",
        "thread_length",
        "chamfer",
        "feature_depth",
        "feature_height",
        "feature_total_height",
    }
    RULES = [
        "key_dimensions 只能直接使用 allowed_dimensions 中的主体关键尺寸。",
        "construction_dimensions 可用于建模构造；若进入 key_dimensions，必须保留具体构造语义，不得命名为总长、深度、对边、对角、法兰直径或孔径。",
        "unresolved_dimensions 不得进入 key_dimensions；若建模需要它们，必须写入 uncertainties 或触发追问。",
        "candidate_dimensions 来自本地兼容候选规则或标注几何推断，只能作为语义裁决参考；未被 semantic_adjudication 或用户澄清确认前，不应视为最终建模权限。",
    ]

    @classmethod
    def from_bindings(cls, bindings: Sequence[Dict[str, Any]]) -> "DimensionPermissionPlan":
        return cls(bindings=bindings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_dimensions": self.allowed_dimensions(),
            "construction_dimensions": self.construction_dimensions(),
            "unresolved_dimensions": self.unresolved_dimensions(),
            "excluded_dimensions": self.excluded_dimensions(),
            "candidate_dimensions": self.candidate_dimensions(),
            "rules": list(self.RULES),
        }

    @classmethod
    def bind_selected_value(
        cls,
        bindings: List[Dict[str, Any]],
        *,
        role: str,
        selected_value: Any,
    ) -> None:
        selected = cls._coerce_numeric_answer(selected_value)
        if selected is None:
            return
        for binding in bindings:
            if (
                binding.get("semantic_role") in ("unresolved_linear", role)
                and cls._values_equal(binding.get("value"), selected)
            ):
                binding["semantic_role"] = role
                binding["confidence"] = 1.0
                binding["source"] = "user_confirmed"
                binding["binding_status"] = "adjudicated"
                binding["evidence"] = ["用户澄清确认"]
                return

    @classmethod
    def resolve_conflicting_role(
        cls,
        bindings: List[Dict[str, Any]],
        *,
        role: str,
        selected_value: Any,
    ) -> None:
        selected = cls._coerce_numeric_answer(selected_value)
        if selected is None:
            return
        for binding in bindings:
            if binding.get("semantic_role") != role:
                continue
            if cls._values_equal(binding.get("value"), selected):
                binding["confidence"] = 1.0
                binding["source"] = "user_confirmed"
                binding["binding_status"] = "adjudicated"
                binding["evidence"] = ["用户澄清确认"]
            else:
                binding["semantic_role"] = "unresolved_linear"
                binding["confidence"] = 0.0
                binding.pop("binding_status", None)
                binding["evidence"] = ["用户澄清排除"]

    @classmethod
    def exclude_for_question(
        cls,
        bindings: List[Dict[str, Any]],
        question_id: str,
    ) -> None:
        role_by_question = {
            "bind_profile_length": "profile_length",
            "bind_profile_height": "profile_height",
        }
        role = role_by_question.get(question_id)
        if role is None and question_id.startswith("resolve_"):
            role = question_id.removeprefix("resolve_")
        if role is None:
            return
        for binding in bindings:
            is_unresolved_axis_candidate = (
                binding.get("semantic_role") == "unresolved_linear"
                and cls._is_subject_axis_candidate(binding, role)
            )
            is_role_candidate = (
                binding.get("semantic_role") == role
                and binding.get("binding_status") == "candidate"
            )
            if not (is_unresolved_axis_candidate or is_role_candidate):
                continue
            binding["semantic_role"] = "excluded_by_user"
            binding["confidence"] = 0.0
            binding.pop("binding_status", None)
            binding["evidence"] = ["用户不确定该候选尺寸是否可用于建模，已排除自动绑定"]

    @classmethod
    def apply_feature_detail_dimension_answer(
        cls,
        bindings: List[Dict[str, Any]],
        answer: Any,
    ) -> None:
        payload = cls._parse_structured_answer(answer)
        if not payload:
            return
        action = str(payload.get("action") or "")
        if action == "bind_feature_dimension":
            selected_text = str(payload.get("dimension_text") or "")
            role = str(payload.get("role") or "feature_depth")
            feature_kind = str(payload.get("feature_kind") or "")
            feature_description = str(payload.get("feature_description") or "")
            for binding in bindings:
                if binding.get("semantic_role") != "unresolved_linear":
                    continue
                if str(binding.get("text") or binding.get("value")) != selected_text:
                    continue
                binding["semantic_role"] = role
                binding["confidence"] = 1.0
                binding["feature_kind"] = feature_kind
                binding["feature_description"] = feature_description
                binding["source"] = "user_confirmed"
                binding["evidence"] = ["用户通过系统澄清确认该尺寸用于细节特征高度/深度"]
                return
        if action in {
            "exclude_feature_dimensions",
            "skip_feature",
            "unknown_feature_dimension",
        }:
            selected_texts = {
                str(item) for item in payload.get("dimension_texts", []) or []
            }
            for binding in bindings:
                if binding.get("semantic_role") != "unresolved_linear":
                    continue
                if str(binding.get("text") or binding.get("value")) not in selected_texts:
                    continue
                binding["semantic_role"] = "excluded_by_user"
                binding["confidence"] = 0.0
                binding["source"] = "user_confirmed"
                binding["feature_description"] = payload.get("feature_description")
                binding["evidence"] = ["用户未确认该尺寸可用于细节特征高度/深度"]

    def allowed_dimensions(self) -> List[Dict[str, Any]]:
        return [
            self._plan_item(binding)
            for binding in self.bindings
            if (
                binding.get("semantic_role") in self.ALLOWED_ROLES
                and not self._is_construction_dimension(binding)
                and not self._is_candidate_binding(binding)
            )
        ]

    def construction_dimensions(self) -> List[Dict[str, Any]]:
        return [
            self._plan_item(binding)
            for binding in self.bindings
            if (
                (
                    binding.get("semantic_role") in self.CONSTRUCTION_ROLES
                    or self._is_construction_dimension(binding)
                )
                and not self._is_candidate_binding(binding)
            )
        ]

    def unresolved_dimensions(self) -> List[Dict[str, Any]]:
        return [
            self._plan_item(binding)
            for binding in self.bindings
            if binding.get("semantic_role") == "unresolved_linear"
        ]

    def excluded_dimensions(self) -> List[Dict[str, Any]]:
        return [
            self._plan_item(binding)
            for binding in self.bindings
            if binding.get("semantic_role") == "excluded_by_user"
        ]

    def candidate_dimensions(self) -> List[Dict[str, Any]]:
        return [
            self._plan_item(binding)
            for binding in self.bindings
            if self._is_candidate_binding(binding)
        ]

    @classmethod
    def _plan_item(cls, binding: Dict[str, Any]) -> Dict[str, Any]:
        binding_status = binding.get("binding_status")
        if not binding_status:
            if binding.get("semantic_role") == "unresolved_linear":
                binding_status = "unresolved"
            elif binding.get("semantic_role") == "excluded_by_user":
                binding_status = "excluded"
            else:
                binding_status = "adjudicated"
        item = {
            "text": binding.get("text"),
            "value": binding.get("value"),
            "role": binding.get("semantic_role"),
            "confidence": binding.get("confidence"),
            "evidence": binding.get("evidence", []),
            "span": binding.get("span"),
            "repeat_count": binding.get("repeat_count"),
            "radius_value": binding.get("radius_value"),
            "diameter_value": binding.get("diameter_value"),
            "thread_value": binding.get("thread_value"),
            "callout": binding.get("callout"),
            "feature_kind": binding.get("feature_kind"),
            "feature_description": binding.get("feature_description"),
            "source": binding.get("source"),
            "binding_status": binding_status,
        }
        dimension_kind = cls._construction_dimension_kind(binding)
        if dimension_kind:
            item["dimension_kind"] = dimension_kind
        if not item.get("feature_kind"):
            feature_kind = cls._feature_kind_from_callout(binding)
            if feature_kind:
                item["feature_kind"] = feature_kind
        return item

    @classmethod
    def _is_construction_dimension(cls, binding: Dict[str, Any]) -> bool:
        return bool(cls._construction_dimension_kind(binding))

    @staticmethod
    def _is_candidate_binding(binding: Dict[str, Any]) -> bool:
        return binding.get("binding_status") == "candidate"

    @classmethod
    def _construction_dimension_kind(cls, binding: Dict[str, Any]) -> str:
        if binding.get("repeat_count"):
            return "feature_count_size"
        if binding.get("semantic_role") == "profile_length_segment":
            return "linear_segment"
        if binding.get("semantic_role") in {
            "radius",
            "diameter",
            "thread_size",
            "thread_length",
            "chamfer",
            "feature_depth",
            "feature_height",
            "feature_total_height",
        }:
            return "feature_size"
        return ""

    @staticmethod
    def _feature_kind_from_callout(binding: Dict[str, Any]) -> str:
        callout = binding.get("callout")
        if callout == "repeated_radius":
            return "radius"
        if callout == "repeated_diameter":
            return "diameter"
        if callout == "repeated_thread":
            return "thread"
        return ""

    @staticmethod
    def _coerce_numeric_answer(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _values_equal(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_subject_axis_candidate(binding: Dict[str, Any], role: str) -> bool:
        span = binding.get("span") or {}
        if role == "profile_length":
            return (
                span.get("view_name") == "main"
                and span.get("orientation") == "horizontal"
            )
        if role == "profile_height":
            return (
                span.get("view_name") == "main"
                and span.get("orientation") == "vertical"
            )
        return False

    @staticmethod
    def _parse_structured_answer(answer: Any) -> Dict[str, Any]:
        if isinstance(answer, dict):
            return dict(answer)
        if not isinstance(answer, str):
            return {}
        try:
            parsed = json.loads(answer)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
