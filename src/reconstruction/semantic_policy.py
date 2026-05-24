#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在语义生成前裁决可安全使用的重建上下文。"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Dict, List, Mapping, Sequence

from .clarification_questions import clarification_question, choice_option
from .clarification_response import ClarificationResponse, USER_MODELING_HINT_KEY


class SemanticPolicy:
    """对尺寸来源和特征升级门槛做确定性裁决。"""

    UNKNOWN_ANSWER = "__unknown__"
    USER_MODELING_HINT_KEY = USER_MODELING_HINT_KEY
    FEATURE_DETAIL_DIMENSION_KEY = "bind_feature_detail_dimension"

    def evaluate(
        self,
        reconstruction_context: Dict[str, Any],
        clarification_answers: Mapping[str, Any] | ClarificationResponse | None = None,
    ) -> Dict[str, Any]:
        clarification_response = ClarificationResponse.from_input(clarification_answers)
        dimensions = reconstruction_context.get("dimensions", []) or []
        annotation_dimensions = [
            dimension for dimension in dimensions
            if isinstance(dimension.get("value"), (int, float))
        ]

        if annotation_dimensions:
            dimension_source = "annotation"
            assumptions = [
                "存在可用尺寸标注，后续语义生成仅可使用标注尺寸；图形坐标仅保留形状提示。"
            ]
        else:
            dimension_source = "geometry"
            assumptions = [
                "未发现可用尺寸标注，后续语义生成只能依据图形几何做保守解释。"
            ]

        dimension_bindings = self._build_dimension_bindings(
            annotation_dimensions,
            reconstruction_context,
        )
        user_modeling_hint = clarification_response.user_modeling_hint
        if clarification_response.has_any_input():
            dimension_bindings = self._apply_clarification_answers(
                dimension_bindings,
                clarification_response,
            )
        dimension_plan = self._build_dimension_plan(dimension_bindings)
        clarification_questions = self._build_clarification_questions(
            dimension_bindings,
            reconstruction_context,
        )
        if user_modeling_hint:
            assumptions.append(
                "用户提供了补充建模提示；该提示可用于解释建模意图和细节偏好，但不得覆盖图纸事实、关键尺寸来源、主体方向或主体外形。"
            )
            if clarification_questions:
                assumptions.append(
                    "未结构化回答的追问不再阻塞本次局部恢复；相关裸尺寸仍不得进入 key_dimensions，必要时应降级为部分建模成果或跳过细节。"
                )
                clarification_questions = []
        if any(binding["semantic_role"] == "unresolved_linear" for binding in dimension_bindings):
            assumptions.append(
                "裸线性尺寸尚未完成语义绑定；在没有额外证据前，不得把它们擅自命名为总长、对边、对角、法兰直径或孔径。"
            )
        feature_constraints = {
            "subtractive_features_require_explicit_evidence": True,
            "hidden_lines_alone_are_insufficient": True,
            "concentric_projection_alone_is_insufficient": True,
            "chamfer_is_external_corner_removal": True,
            "chamfer_must_not_create_recess_or_slot": True,
        }

        adjudicated_context = self._build_adjudicated_context(
            reconstruction_context,
            dimension_source=dimension_source,
            dimension_bindings=dimension_bindings,
            dimension_plan=dimension_plan,
            feature_constraints=feature_constraints,
            assumptions=assumptions,
            user_modeling_hint=user_modeling_hint,
            user_modeling_hint_policy=clarification_response.conflict_policy,
        )

        return {
            "dimension_source": dimension_source,
            "dimension_bindings": dimension_bindings,
            "dimension_plan": dimension_plan,
            "feature_constraints": feature_constraints,
            "clarification_questions": clarification_questions,
            "assumptions": assumptions,
            "adjudicated_context": adjudicated_context,
        }

    def _build_adjudicated_context(
        self,
        reconstruction_context: Dict[str, Any],
        *,
        dimension_source: str,
        dimension_bindings: List[Dict[str, Any]],
        dimension_plan: Dict[str, Any],
        feature_constraints: Dict[str, Any],
        assumptions: List[str],
        user_modeling_hint: str = "",
        user_modeling_hint_policy: str = "",
    ) -> Dict[str, Any]:
        context = deepcopy(reconstruction_context)
        context["context_version"] = "adjudicated_context_v1"
        context["semantic_policy"] = {
            "dimension_source": dimension_source,
            "dimension_bindings": dimension_bindings,
            "dimension_plan": dimension_plan,
            "feature_constraints": feature_constraints,
            "assumptions": assumptions,
        }
        if user_modeling_hint:
            context["semantic_policy"]["user_modeling_hint"] = user_modeling_hint
            context["semantic_policy"]["user_modeling_hint_policy"] = (
                user_modeling_hint_policy
            )
            context["user_modeling_hint"] = user_modeling_hint
            context["user_modeling_hint_policy"] = user_modeling_hint_policy

        # 选择标注尺寸时，不再把可反推出测量尺寸的坐标细节暴露给 LLM。
        if dimension_source == "annotation":
            context.pop("source_entities", None)
            views = context.get("view_analysis", {}).get("views", []) or []
            for view in views:
                view.pop("entities", None)

        return context

    @classmethod
    def _extract_user_modeling_hint(
        cls,
        clarification_answers: Mapping[str, Any] | ClarificationResponse | None,
    ) -> str:
        return ClarificationResponse.from_input(clarification_answers).user_modeling_hint

    @classmethod
    def _build_dimension_bindings(
        cls,
        dimensions: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        bindings: List[Dict[str, Any]] = []
        for dimension in dimensions:
            semantic_role, confidence, evidence = cls._classify_dimension(
                dimension,
                reconstruction_context,
            )
            bindings.append({
                "text": dimension.get("text"),
                "value": dimension.get("value"),
                "type": dimension.get("type"),
                "repeat_count": dimension.get("repeat_count"),
                "radius_value": dimension.get("radius_value"),
                "diameter_value": dimension.get("diameter_value"),
                "thread_value": dimension.get("thread_value"),
                "callout": dimension.get("callout"),
                "position": dimension.get("position"),
                "semantic_role": semantic_role,
                "confidence": confidence,
                "evidence": evidence,
                "span": cls._build_dimension_span(dimension, reconstruction_context),
            })
        cls._apply_dimension_chain_roles(bindings, reconstruction_context)
        return bindings

    @classmethod
    def _build_dimension_plan(cls, bindings: List[Dict[str, Any]]) -> Dict[str, Any]:
        allowed_roles = {
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
        construction_roles = {
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
        allowed_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if (
                binding.get("semantic_role") in allowed_roles
                and not cls._is_construction_dimension(binding)
            )
        ]
        construction_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if (
                binding.get("semantic_role") in construction_roles
                or cls._is_construction_dimension(binding)
            )
        ]
        unresolved_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
        ]
        excluded_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if binding.get("semantic_role") == "excluded_by_user"
        ]
        return {
            "allowed_dimensions": allowed_dimensions,
            "construction_dimensions": construction_dimensions,
            "unresolved_dimensions": unresolved_dimensions,
            "excluded_dimensions": excluded_dimensions,
            "rules": [
                "key_dimensions 只能直接使用 allowed_dimensions 中的主体关键尺寸。",
                "construction_dimensions 可用于建模构造；若进入 key_dimensions，必须保留具体构造语义，不得命名为总长、深度、对边、对角、法兰直径或孔径。",
                "unresolved_dimensions 不得进入 key_dimensions；若建模需要它们，必须写入 uncertainties 或触发追问。",
            ],
        }

    @classmethod
    def _plan_item(cls, binding: Dict[str, Any]) -> Dict[str, Any]:
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
        }
        dimension_kind = cls._construction_dimension_kind(binding)
        if dimension_kind:
            item["dimension_kind"] = dimension_kind
            item["binding_status"] = "adjudicated"
        if not item.get("feature_kind"):
            feature_kind = cls._feature_kind_from_callout(binding)
            if feature_kind:
                item["feature_kind"] = feature_kind
        return item

    @classmethod
    def _is_construction_dimension(cls, binding: Dict[str, Any]) -> bool:
        return bool(cls._construction_dimension_kind(binding))

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

    @classmethod
    def _classify_dimension(
        cls,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str]]:
        text = str(dimension.get("text") or "")
        dim_type = str(dimension.get("type") or "")
        normalized = text.replace(" ", "")

        if dim_type == "半径" or re.search(r"^[Rr]\d", normalized):
            return "radius", 1.0, ["标注文本包含半径符号 R"]

        if dim_type == "直径" or any(symbol in normalized for symbol in ("φ", "Φ", "∅", "⌀", "Ø")):
            return "diameter", 1.0, ["标注文本包含直径符号"]

        if dim_type == "螺纹" or re.search(r"^[Mm]\d", normalized):
            return "thread_size", 1.0, ["标注文本包含螺纹前缀 M"]

        if re.search(r"\d+(?:\.\d+)?[xX×]\d+(?:\.\d+)?(?:%%d|°)", normalized):
            return "chamfer", 1.0, [
                "标注文本符合倒角格式",
                "倒角表示外部尖角削除，不表示内陷槽或凹坑",
            ]

        inferred_role = cls._infer_linear_role_from_annotation_geometry(
            dimension,
            reconstruction_context,
        )
        if inferred_role is not None:
            return inferred_role

        return "unresolved_linear", 0.0, ["裸线性尺寸缺少足够文本语义"]

    @classmethod
    def _infer_linear_role_from_annotation_geometry(
        cls,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str]] | None:
        if not cls._is_linear_dimension_type(dimension):
            return None

        line = cls._nearest_associated_line(dimension)
        orientation = cls._line_orientation(line) if line else None
        view_name = cls._locate_dimension_view(dimension, reconstruction_context)
        inferred_from_span = False
        span = None
        if orientation is None or view_name is None:
            span = cls._build_dimension_span(dimension, reconstruction_context)
            if span:
                orientation = orientation or span.get("orientation")
                view_name = view_name or span.get("view_name")
                inferred_from_span = True

        if orientation is None or view_name is None:
            return None
        if inferred_from_span and span and not cls._span_matches_view_extent(
            span,
            reconstruction_context,
        ):
            return None

        if orientation == "horizontal":
            if view_name == "main":
                return "profile_length", 0.8, ["主视图中的水平标注线"]
            if view_name in ("left", "right", "top"):
                return "projected_profile_horizontal_extent", 0.8, [f"{view_name} 视图中的水平外形尺寸"]
        elif orientation == "vertical":
            if view_name == "main":
                return "profile_height", 0.8, ["主视图中的竖直外形尺寸"]
            if view_name in ("left", "right", "top"):
                return "projected_profile_vertical_extent", 0.85, [f"{view_name} 视图中的竖直外形尺寸"]

        inferred_by_value = cls._infer_linear_role_from_value_and_near_view(
            dimension,
            reconstruction_context,
        )
        if inferred_by_value is not None:
            return inferred_by_value

        return None

    @staticmethod
    def _span_matches_view_extent(
        span: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> bool:
        view_name = span.get("view_name")
        orientation = span.get("orientation")
        span_range = span.get("range") or []
        if view_name is None or orientation not in ("horizontal", "vertical"):
            return False
        if len(span_range) < 2:
            return False

        axis = 0 if orientation == "horizontal" else 1
        views = reconstruction_context.get("view_analysis", {}).get("views", []) or []
        view = next((item for item in views if item.get("name") == view_name), None)
        if not view:
            return False
        bbox = view.get("bbox") or []
        if len(bbox) < 4:
            return False

        extent = [float(bbox[axis]), float(bbox[axis + 2])]
        extent.sort()
        span_min, span_max = sorted((float(span_range[0]), float(span_range[1])))
        extent_size = max(extent[1] - extent[0], 1e-6)
        tolerance = max(extent_size * 0.08, 1e-6)
        return (
            abs(span_min - extent[0]) <= tolerance
            and abs(span_max - extent[1]) <= tolerance
        )

    @classmethod
    def _infer_linear_role_from_value_and_near_view(
        cls,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str]] | None:
        value = dimension.get("value")
        if not isinstance(value, (int, float)):
            return None
        position = dimension.get("position") or []
        if len(position) < 2:
            return None

        view = cls._nearest_view_to_point(position, reconstruction_context)
        if not view:
            return None
        view_name = str(view.get("name") or "")
        bbox = view.get("bbox") or []
        if len(bbox) < 4:
            return None
        width = abs(float(bbox[2]) - float(bbox[0]))
        height = abs(float(bbox[3]) - float(bbox[1]))
        if height <= 1e-6 or width <= 1e-6:
            return None

        if abs(float(value) - height) <= max(height * 0.08, 1e-6):
            if view_name in ("top", "bottom", "left", "right"):
                return "projected_profile_vertical_extent", 0.85, [
                    f"线性尺寸值等于{view_name}视图竖向外形尺寸"
                ]
        if abs(float(value) - width) <= max(width * 0.08, 1e-6):
            if view_name == "main":
                return "profile_length", 0.8, [
                    "线性尺寸值等于主视图水平外包络"
                ]
            if view_name in ("top", "bottom", "left", "right"):
                return "projected_profile_horizontal_extent", 0.85, [
                    f"线性尺寸值等于{view_name}视图水平外形尺寸"
                ]
        return None

    @staticmethod
    def _nearest_view_to_point(
        point: List[float],
        reconstruction_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        x, y = float(point[0]), float(point[1])
        best_view = None
        best_distance = float("inf")
        for view in reconstruction_context.get("view_analysis", {}).get("views", []) or []:
            bbox = view.get("bbox") or []
            if len(bbox) < 4:
                continue
            min_x, min_y, max_x, max_y = map(float, bbox[:4])
            width = max(max_x - min_x, 1e-6)
            height = max(max_y - min_y, 1e-6)
            tolerance = max(width, height) * 0.5
            dx = max(min_x - x, 0.0, x - max_x)
            dy = max(min_y - y, 0.0, y - max_y)
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= tolerance and distance < best_distance:
                best_distance = distance
                best_view = view
        return best_view

    @classmethod
    def _build_dimension_span(
        cls,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        if not cls._is_linear_dimension_type(dimension):
            return None
        raw_points = dimension.get("definition_points", []) or []
        points = raw_points[:2]
        if len(points) >= 2 and not cls._is_real_point(points[0]) and not cls._is_real_point(points[1]):
            points = [
                point for point in raw_points
                if cls._is_real_point(point)
            ]
        if len(points) < 2:
            return None
        start = points[0]
        end = points[1]
        line = {"start": start, "end": end}
        orientation = cls._line_orientation(line)
        if orientation is None:
            return None
        axis = 0 if orientation == "horizontal" else 1
        a = float(start[axis])
        b = float(end[axis])
        span_min, span_max = sorted((a, b))
        midpoint = [
            (float(start[0]) + float(end[0])) / 2,
            (float(start[1]) + float(end[1])) / 2,
            0.0,
        ]
        return {
            "start": start,
            "end": end,
            "axis": "x" if axis == 0 else "y",
            "orientation": orientation,
            "range": [span_min, span_max],
            "midpoint": midpoint,
            "view_name": cls._locate_point_view(midpoint, reconstruction_context),
        }

    @staticmethod
    def _is_linear_dimension_type(dimension: Dict[str, Any]) -> bool:
        dim_type = str(dimension.get("type") or "")
        return dim_type in {"线性", "绾挎€?", "Япад"}

    @staticmethod
    def _is_real_point(point: Any) -> bool:
        if not isinstance(point, list) or len(point) < 2:
            return False
        return abs(float(point[0])) > 1e-9 or abs(float(point[1])) > 1e-9

    @classmethod
    def _apply_dimension_chain_roles(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> None:
        span_bindings = [
            binding for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
            and binding.get("span")
            and isinstance(binding.get("value"), (int, float))
        ]
        cls._apply_projected_profile_extent_roles(span_bindings)
        cls._apply_square_profile_roles(span_bindings)
        cls._append_main_view_composite_length(bindings, span_bindings)
        cls._apply_thread_length_roles(bindings)
        cls._apply_plate_projection_thickness_roles(bindings, reconstruction_context)

    @classmethod
    def _apply_square_profile_roles(cls, bindings: List[Dict[str, Any]]) -> None:
        """Bind equal orthogonal outer dimensions in the same view as a square profile."""
        unresolved = [
            binding for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
            and isinstance(binding.get("value"), (int, float))
            and (binding.get("span") or {}).get("view_name") == "main"
            and (binding.get("span") or {}).get("orientation") in ("horizontal", "vertical")
        ]
        for horizontal in unresolved:
            h_span = horizontal.get("span") or {}
            if h_span.get("orientation") != "horizontal":
                continue
            for vertical in unresolved:
                if vertical is horizontal:
                    continue
                v_span = vertical.get("span") or {}
                if v_span.get("orientation") != "vertical":
                    continue
                if not cls._values_equal(horizontal.get("value"), vertical.get("value")):
                    continue
                horizontal["semantic_role"] = "profile_length"
                horizontal["confidence"] = 0.95
                horizontal["evidence"] = [
                    "同一主视图存在相同数值的水平和竖直外形尺寸，裁决为正方形轮廓边长",
                ]
                vertical["semantic_role"] = "profile_height"
                vertical["confidence"] = 0.95
                vertical["evidence"] = [
                    "同一主视图存在相同数值的水平和竖直外形尺寸，裁决为正方形轮廓边长",
                ]
                return

    @staticmethod
    def _apply_projected_profile_extent_roles(bindings: List[Dict[str, Any]]) -> None:
        for binding in bindings:
            span = binding.get("span") or {}
            view_name = span.get("view_name")
            if view_name not in ("left", "right"):
                continue
            if span.get("orientation") == "horizontal":
                binding["semantic_role"] = "projected_profile_horizontal_extent"
                binding["confidence"] = 0.9
                binding["evidence"] = [f"{view_name} 视图中的水平外形尺寸区间"]
            elif span.get("orientation") == "vertical":
                binding["semantic_role"] = "projected_profile_vertical_extent"
                binding["confidence"] = 0.9
                binding["evidence"] = [f"{view_name} 视图中的竖直外形尺寸区间"]

    @classmethod
    def _append_main_view_composite_length(
        cls,
        bindings: List[Dict[str, Any]],
        span_bindings: List[Dict[str, Any]],
    ) -> None:
        main_horizontal = [
            binding for binding in span_bindings
            if (binding.get("span") or {}).get("view_name") == "main"
            and (binding.get("span") or {}).get("orientation") == "horizontal"
        ]
        if not main_horizontal:
            return
        outer_chain = cls._outer_adjacent_chain(main_horizontal)
        if len(outer_chain) < 2:
            return
        value = sum(float(binding["value"]) for binding in outer_chain)
        labels = [str(binding.get("text") or cls._format_dimension_value(binding["value"])) for binding in outer_chain]
        ranges = [(binding.get("span") or {}).get("range") for binding in outer_chain]
        bindings.append({
            "text": "+".join(labels),
            "value": value,
            "type": "组合线性",
            "semantic_role": "profile_length",
            "confidence": 0.95,
            "evidence": ["由主视图相邻尺寸链组合得到"],
            "span": {
                "orientation": "horizontal",
                "axis": "x",
                "view_name": "main",
                "range": [ranges[0][0], ranges[-1][1]],
                "components": labels,
            },
        })
        for binding in outer_chain:
            if binding.get("semantic_role") == "unresolved_linear":
                binding["semantic_role"] = "profile_length_segment"
                binding["confidence"] = 0.85
                binding["evidence"] = ["主视图总长尺寸链的一段"]

    @classmethod
    def _apply_thread_length_roles(cls, bindings: List[Dict[str, Any]]) -> None:
        if not cls._has_bolt_thread_length_context(bindings):
            return

        containers = [
            binding for binding in bindings
            if binding.get("semantic_role") in ("profile_length_segment", "profile_length")
            and (binding.get("span") or {}).get("view_name") == "main"
            and (binding.get("span") or {}).get("orientation") == "horizontal"
        ]
        if not containers:
            return

        for binding in bindings:
            span = binding.get("span") or {}
            if binding.get("semantic_role") != "unresolved_linear":
                continue
            if span.get("view_name") != "main" or span.get("orientation") != "horizontal":
                continue
            if not any(cls._is_span_inside(binding, container) for container in containers):
                continue
            binding["semantic_role"] = "thread_length"
            binding["confidence"] = 0.9
            binding["evidence"] = [
                "螺栓/轴类图纸中该主视图内部水平尺寸位于杆部长度段内，裁决为螺纹长度",
            ]

    @classmethod
    def _apply_plate_projection_thickness_roles(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> None:
        """Bind nested vertical dimensions in a narrow projection as plate thickness + raised detail."""
        views = (reconstruction_context.get("view_analysis", {}) or {}).get("views", []) or []
        for view in views:
            if str(view.get("name") or "") != "main":
                continue
            bbox = view.get("bbox") or []
            if len(bbox) < 4:
                continue
            width = abs(float(bbox[2]) - float(bbox[0]))
            height = abs(float(bbox[3]) - float(bbox[1]))
            if height <= 1e-6 or width / height < 3.0:
                continue

            vertical_candidates = []
            outer_candidates = []
            for binding in bindings:
                if binding.get("semantic_role") != "unresolved_linear":
                    continue
                value = binding.get("value")
                if not isinstance(value, (int, float)):
                    continue
                span = binding.get("span") or {}
                if (
                    span.get("view_name") == "main"
                    and span.get("orientation") == "vertical"
                ):
                    vertical_candidates.append(binding)
                    continue
                near_view = cls._nearest_view_to_point(
                    [0.0, 0.0]
                    if not binding.get("position")
                    else binding.get("position"),
                    reconstruction_context,
                )
                if (
                    near_view is view
                    and abs(float(value) - height) <= max(height * 0.08, 1e-6)
                ):
                    outer_candidates.append(binding)

            if not vertical_candidates or not outer_candidates:
                continue

            base = max(
                (
                    candidate for candidate in vertical_candidates
                    if float(candidate.get("value")) < height
                ),
                key=lambda item: float(item.get("value")),
                default=None,
            )
            outer = max(
                outer_candidates,
                key=lambda item: float(item.get("value")),
                default=None,
            )
            if not base or not outer:
                continue
            protrusion = float(outer["value"]) - float(base["value"])
            if protrusion <= 0:
                continue

            base["semantic_role"] = "extrusion_depth"
            base["confidence"] = 0.9
            base["evidence"] = [
                "窄条主视图中较小竖向尺寸位于基板厚度范围内，裁决为板厚/挤出深度",
            ]
            outer["semantic_role"] = "feature_total_height"
            outer["confidence"] = 0.85
            outer["evidence"] = [
                "窄条主视图中较大竖向尺寸等于局部凸起处总高度",
            ]
            bindings.append({
                "text": f"{outer.get('text')}-{base.get('text')}",
                "value": protrusion,
                "type": "派生线性",
                "semantic_role": "feature_height",
                "confidence": 0.9,
                "evidence": [
                    "由局部总高度减去基板厚度得到凸出高度",
                ],
                "span": {
                    "orientation": "vertical",
                    "axis": "y",
                    "view_name": "main",
                    "components": [outer.get("text"), base.get("text")],
                },
                "source": "derived_from_annotation",
            })
            return

    @staticmethod
    def _has_bolt_thread_length_context(bindings: List[Dict[str, Any]]) -> bool:
        roles = {binding.get("semantic_role") for binding in bindings}
        has_head_or_end_detail = "chamfer" in roles and "radius" in roles
        projected_roles = {
            "projected_profile_horizontal_extent",
            "projected_profile_vertical_extent",
        }
        has_end_view_extent = bool(projected_roles & roles)
        return has_head_or_end_detail and has_end_view_extent

    @classmethod
    def _is_span_inside(cls, inner: Dict[str, Any], outer: Dict[str, Any]) -> bool:
        inner_range = (inner.get("span") or {}).get("range") or []
        outer_range = (outer.get("span") or {}).get("range") or []
        if len(inner_range) < 2 or len(outer_range) < 2:
            return False
        tolerance = cls._span_tolerance(inner, outer)
        return (
            outer_range[0] - tolerance <= inner_range[0]
            and inner_range[1] <= outer_range[1] + tolerance
            and (outer_range[1] - outer_range[0]) > (inner_range[1] - inner_range[0]) + tolerance
        )

    @classmethod
    def _outer_adjacent_chain(cls, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = [
            binding for binding in bindings
            if not cls._is_span_contained_by_another(binding, bindings)
        ]
        if len(candidates) < 2:
            return []
        candidates.sort(key=lambda item: (item["span"]["range"][0], item["span"]["range"][1]))
        chain = [candidates[0]]
        for binding in candidates[1:]:
            prev_end = chain[-1]["span"]["range"][1]
            current_start = binding["span"]["range"][0]
            if abs(current_start - prev_end) <= cls._span_tolerance(chain[-1], binding):
                chain.append(binding)
            else:
                if len(chain) >= 2:
                    return chain
                chain = [binding]
        return chain if len(chain) >= 2 else []

    @classmethod
    def _is_span_contained_by_another(
        cls,
        binding: Dict[str, Any],
        bindings: List[Dict[str, Any]],
    ) -> bool:
        current = (binding.get("span") or {}).get("range") or []
        if len(current) < 2:
            return False
        for other in bindings:
            if other is binding:
                continue
            candidate = (other.get("span") or {}).get("range") or []
            if len(candidate) < 2:
                continue
            tolerance = cls._span_tolerance(binding, other)
            if candidate[0] <= current[0] + tolerance and candidate[1] >= current[1] - tolerance:
                if (candidate[1] - candidate[0]) > (current[1] - current[0]) + tolerance:
                    return True
        return False

    @staticmethod
    def _span_tolerance(*bindings: Dict[str, Any]) -> float:
        ranges = []
        for binding in bindings:
            span_range = (binding.get("span") or {}).get("range") or []
            if len(span_range) >= 2:
                ranges.append(abs(float(span_range[1]) - float(span_range[0])))
        scale = max(ranges) if ranges else 1.0
        return max(scale * 0.03, 1e-6)

    @staticmethod
    def _nearest_associated_line(dimension: Dict[str, Any]) -> Dict[str, Any] | None:
        associated = dimension.get("associated_lines") or []
        if not associated:
            return None
        nearest = associated[0]
        return nearest.get("line") if isinstance(nearest, dict) else None

    @staticmethod
    def _line_orientation(line: Dict[str, Any]) -> str | None:
        start = line.get("start") or []
        end = line.get("end") or []
        if len(start) < 2 or len(end) < 2:
            return None
        dx = abs(float(end[0]) - float(start[0]))
        dy = abs(float(end[1]) - float(start[1]))
        if dx == 0 and dy == 0:
            return None
        if dx >= dy * 2.5:
            return "horizontal"
        if dy >= dx * 2.5:
            return "vertical"
        return None

    @staticmethod
    def _locate_dimension_view(
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> str | None:
        position = dimension.get("position") or []
        if len(position) < 2:
            return None
        x, y = float(position[0]), float(position[1])
        views = reconstruction_context.get("view_analysis", {}).get("views", []) or []
        for view in views:
            bbox = view.get("bbox") or []
            if len(bbox) < 4:
                continue
            min_x, min_y, max_x, max_y = map(float, bbox[:4])
            if min_x <= x <= max_x and min_y <= y <= max_y:
                return view.get("name")
        return None

    @staticmethod
    def _locate_point_view(
        point: List[float],
        reconstruction_context: Dict[str, Any],
    ) -> str | None:
        if len(point) < 2:
            return None
        x, y = float(point[0]), float(point[1])
        views = reconstruction_context.get("view_analysis", {}).get("views", []) or []
        for view in views:
            bbox = view.get("bbox") or []
            if len(bbox) < 4:
                continue
            min_x, min_y, max_x, max_y = map(float, bbox[:4])
            tolerance = max(max_x - min_x, max_y - min_y) * 0.08
            if min_x - tolerance <= x <= max_x + tolerance and min_y - tolerance <= y <= max_y + tolerance:
                return view.get("name")
        return None

    @classmethod
    def _build_clarification_questions(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        questions: List[Dict[str, Any]] = []
        questions.extend(cls._questions_for_conflicting_key_roles(bindings))
        questions.extend(cls._questions_for_missing_multiview_axes(bindings, reconstruction_context))
        return questions

    @classmethod
    def _apply_clarification_answers(
        cls,
        bindings: List[Dict[str, Any]],
        clarification_answers: Mapping[str, Any] | ClarificationResponse,
    ) -> List[Dict[str, Any]]:
        response = ClarificationResponse.from_input(clarification_answers)
        resolved = deepcopy(bindings)
        answer_to_role = {
            "bind_profile_length": "profile_length",
            "bind_profile_height": "profile_height",
        }
        for question_id, role in answer_to_role.items():
            if question_id not in response:
                continue
            answer = response.get(question_id)
            if cls._is_unknown_answer(answer):
                cls._exclude_unresolved_for_question(resolved, question_id)
                continue
            cls._bind_selected_value(
                resolved,
                role=role,
                selected_value=answer,
            )

        if cls.FEATURE_DETAIL_DIMENSION_KEY in response:
            cls._apply_feature_detail_dimension_answer(
                resolved,
                response.get(cls.FEATURE_DETAIL_DIMENSION_KEY),
            )

        for question_id, answer in response.answers.items():
            if not question_id.startswith("resolve_"):
                continue
            if cls._is_unknown_answer(answer):
                cls._exclude_unresolved_for_question(resolved, question_id)
                continue
            role = question_id.removeprefix("resolve_")
            cls._resolve_conflicting_role(
                resolved,
                role=role,
                selected_value=answer,
            )
        return resolved

    @classmethod
    def _apply_feature_detail_dimension_answer(
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

    @classmethod
    def _bind_selected_value(
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
                binding.get("semantic_role") == "unresolved_linear"
                and cls._values_equal(binding.get("value"), selected)
            ):
                binding["semantic_role"] = role
                binding["confidence"] = 1.0
                binding["evidence"] = ["用户澄清确认"]
                return

    @classmethod
    def _resolve_conflicting_role(
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
                binding["evidence"] = ["用户澄清确认"]
            else:
                binding["semantic_role"] = "unresolved_linear"
                binding["confidence"] = 0.0
                binding["evidence"] = ["用户澄清排除"]

    @classmethod
    def _exclude_unresolved_for_question(
        cls,
        bindings: List[Dict[str, Any]],
        question_id: str,
    ) -> None:
        role_by_question = {
            "bind_profile_length": "profile_length",
            "bind_profile_height": "profile_height",
        }
        role = role_by_question.get(question_id)
        if role is None:
            return
        for binding in bindings:
            if (
                binding.get("semantic_role") == "unresolved_linear"
                and cls._is_subject_axis_candidate(binding, role)
            ):
                binding["semantic_role"] = "excluded_by_user"
                binding["confidence"] = 0.0
                binding["evidence"] = ["用户不确定该标注是否为主体关键尺寸，已排除自动绑定"]

    @classmethod
    def _questions_for_conflicting_key_roles(
        cls,
        bindings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        questions: List[Dict[str, Any]] = []
        singular_roles = (
            "profile_length",
            "profile_height",
            "projected_profile_horizontal_extent",
            "projected_profile_vertical_extent",
        )
        for role in singular_roles:
            role_bindings = [
                binding for binding in bindings
                if binding.get("semantic_role") == role
                and isinstance(binding.get("value"), (int, float))
            ]
            values = cls._unique_values(binding.get("value") for binding in role_bindings)
            if len(values) <= 1:
                continue
            role_label = cls._role_display_label(role)
            questions.append(clarification_question(
                question_id=f"resolve_{role}",
                text=f"图纸里有多个值都可能表示{role_label}，请确认建模采用哪一个。",
                kind="single_choice",
                options=[
                    choice_option(
                        cls._format_dimension_value(value),
                        cls._format_dimension_value(value),
                    )
                    for value in values
                ],
                reason=f"{role_label}会影响主体尺寸；不确认时系统不会强行选择其中一个。",
                example="选择图纸上真正表示该尺寸的标注值；看不出来可在补充提示里说明。",
            ))
        return questions

    @classmethod
    def _questions_for_missing_multiview_axes(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        drawing_type = reconstruction_context.get("view_analysis", {}).get("drawing_type")
        if drawing_type not in ("two_view", "three_view"):
            return []

        bound_roles = {
            binding.get("semantic_role")
            for binding in bindings
            if binding.get("semantic_role") not in (None, "unresolved_linear")
        }
        questions: List[Dict[str, Any]] = []
        if not (
            "profile_length" in bound_roles
            or "projected_profile_horizontal_extent" in bound_roles
        ):
            role = "profile_length"
            candidates = cls._subject_axis_candidates(bindings, role)
            if candidates:
                unresolved_options = [
                    choice_option(
                        cls._binding_label(binding),
                        cls._format_dimension_value(binding["value"]),
                    )
                    for binding in candidates
                ]
                unresolved_options.append(choice_option(
                    "我不确定 / 这些都不要绑定为总长",
                    cls.UNKNOWN_ANSWER,
                ))
                questions.append(clarification_question(
                    question_id=f"bind_{role}",
                    text="请确认哪个标注值表示主视图中的水平总尺寸。如果你也看不出来，选择“不确定”。",
                    kind="single_choice",
                    options=unresolved_options,
                    reason="多视图重建缺少这个关键尺寸；不确定时不会强行把某个裸尺寸绑定为总长。",
                    example="选择图纸上表示总尺寸的值；不确定就选“不确定”。",
                ))
        return questions

    @classmethod
    def _subject_axis_candidates(
        cls,
        bindings: List[Dict[str, Any]],
        role: str,
    ) -> List[Dict[str, Any]]:
        return [
            binding for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
            and isinstance(binding.get("value"), (int, float))
            and cls._is_subject_axis_candidate(binding, role)
        ]

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
    def _role_display_label(role: str) -> str:
        labels = {
            "profile_length": "主视图水平总尺寸",
            "profile_height": "主视图竖向总尺寸",
            "projected_profile_horizontal_extent": "投影视图水平外形尺寸",
            "projected_profile_vertical_extent": "投影视图竖向外形尺寸",
        }
        return labels.get(role, "关键尺寸")

    @staticmethod
    def _unique_values(values: Sequence[Any]) -> List[float]:
        unique: List[float] = []
        for value in values:
            if not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if not any(abs(numeric - existing) <= 1e-6 for existing in unique):
                unique.append(numeric)
        return unique

    @staticmethod
    def _coerce_numeric_answer(value: Any) -> float | None:
        if isinstance(value, dict):
            value = value.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_unknown_answer(cls, value: Any) -> bool:
        if isinstance(value, dict):
            value = value.get("value")
        return str(value).strip() == cls.UNKNOWN_ANSWER

    @classmethod
    def _values_equal(cls, left: Any, right: Any) -> bool:
        left_num = cls._coerce_numeric_answer(left)
        right_num = cls._coerce_numeric_answer(right)
        if left_num is None or right_num is None:
            return False
        return abs(left_num - right_num) <= 1e-6

    @classmethod
    def _binding_label(cls, binding: Dict[str, Any]) -> str:
        text = str(binding.get("text") or "").strip()
        value = binding.get("value")
        if text:
            return text
        return cls._format_dimension_value(value)

    @staticmethod
    def _format_dimension_value(value: Any) -> str:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(numeric)
