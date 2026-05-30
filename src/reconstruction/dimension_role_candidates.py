#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy dimension-chain role candidates used before LLM semantic adjudication."""
from __future__ import annotations

from typing import Any, Dict, List


class DimensionChainRoleCandidateApplier:
    """Apply legacy dimension-chain candidate roles to policy bindings.

    This module keeps compatibility with the pre-adjudication dimension plan. It
    should not grow into a part-specific semantic decision layer.
    """

    @classmethod
    def apply(
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

    @staticmethod
    def _mark_candidate(binding: Dict[str, Any]) -> None:
        binding.setdefault("source", "legacy_dimension_candidate")
        binding["binding_status"] = "candidate"

    @classmethod
    def _apply_square_profile_roles(cls, bindings: List[Dict[str, Any]]) -> None:
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
                    "同一主视图存在相同数值的水平和竖直外形尺寸，作为正方形轮廓边长候选",
                ]
                cls._mark_candidate(horizontal)
                vertical["semantic_role"] = "profile_height"
                vertical["confidence"] = 0.95
                vertical["evidence"] = [
                    "同一主视图存在相同数值的水平和竖直外形尺寸，作为正方形轮廓边长候选",
                ]
                cls._mark_candidate(vertical)
                return

    @classmethod
    def _apply_projected_profile_extent_roles(cls, bindings: List[Dict[str, Any]]) -> None:
        for binding in bindings:
            span = binding.get("span") or {}
            view_name = span.get("view_name")
            if view_name not in ("left", "right"):
                continue
            if span.get("orientation") == "horizontal":
                binding["semantic_role"] = "projected_profile_horizontal_extent"
                binding["confidence"] = 0.9
                binding["evidence"] = [f"{view_name} 视图中的水平外形尺寸候选"]
                cls._mark_candidate(binding)
            elif span.get("orientation") == "vertical":
                binding["semantic_role"] = "projected_profile_vertical_extent"
                binding["confidence"] = 0.9
                binding["evidence"] = [f"{view_name} 视图中的竖直外形尺寸候选"]
                cls._mark_candidate(binding)

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
        labels = [
            str(binding.get("text") or cls._format_dimension_value(binding["value"]))
            for binding in outer_chain
        ]
        ranges = [(binding.get("span") or {}).get("range") for binding in outer_chain]
        bindings.append({
            "text": "+".join(labels),
            "value": value,
            "type": "组合线性",
            "semantic_role": "profile_length",
            "confidence": 0.95,
            "evidence": ["由主视图相邻尺寸链组合得到的总长候选"],
            "source": "legacy_dimension_candidate",
            "binding_status": "candidate",
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
                binding["evidence"] = ["主视图总长尺寸链的一段候选"]
                cls._mark_candidate(binding)

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
                "螺栓/轴类图纸中该主视图内部水平尺寸位于杆部长度段内，作为螺纹长度候选",
            ]
            cls._mark_candidate(binding)

    @classmethod
    def _apply_plate_projection_thickness_roles(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> None:
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
                    [0.0, 0.0] if not binding.get("position") else binding.get("position"),
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
                "窄条主视图中较小竖向尺寸位于基板厚度范围内，作为板厚/挤出深度候选",
            ]
            cls._mark_candidate(base)
            outer["semantic_role"] = "feature_total_height"
            outer["confidence"] = 0.85
            outer["evidence"] = [
                "窄条主视图中较大竖向尺寸等于局部凸起处总高度候选",
            ]
            cls._mark_candidate(outer)
            bindings.append({
                "text": f"{outer.get('text')}-{base.get('text')}",
                "value": protrusion,
                "type": "派生线性",
                "semantic_role": "feature_height",
                "confidence": 0.9,
                "evidence": ["由局部总高度减去基板厚度得到凸出高度候选"],
                "span": {
                    "orientation": "vertical",
                    "axis": "y",
                    "view_name": "main",
                    "components": [outer.get("text"), base.get("text")],
                },
                "source": "derived_from_annotation",
                "binding_status": "candidate",
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
    def _values_equal(cls, left: Any, right: Any) -> bool:
        try:
            return abs(float(left) - float(right)) <= 1e-6
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _format_dimension_value(value: Any) -> str:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(numeric)
