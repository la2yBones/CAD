#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build semantic dimension bindings before permission planning."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .dimension_role_candidates import DimensionChainRoleCandidateApplier


class DimensionBindingBuilder:
    """Classify annotation dimensions into adjudication-ready bindings."""

    def build(
        self,
        dimensions: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        bindings: List[Dict[str, Any]] = []
        for dimension in dimensions:
            semantic_role, confidence, evidence, source, binding_status = self._classify_dimension(
                dimension,
                reconstruction_context,
            )
            binding = {
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
                "span": self._build_dimension_span(dimension, reconstruction_context),
            }
            if source:
                binding["source"] = source
            if binding_status:
                binding["binding_status"] = binding_status
            bindings.append(binding)
        self._apply_dimension_chain_roles(bindings, reconstruction_context)
        return bindings

    def _classify_dimension(
        self,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str], str | None, str | None]:
        text = str(dimension.get("text") or "")
        dim_type = str(dimension.get("type") or "")
        normalized = text.replace(" ", "")

        if dim_type == "半径" or re.search(r"^[Rr]\d", normalized):
            return "radius", 1.0, ["标注文本包含半径符号 R"], None, None

        if dim_type == "直径" or any(symbol in normalized for symbol in ("φ", "Φ", "∅", "⌀", "Ø")):
            return "diameter", 1.0, ["标注文本包含直径符号"], None, None

        if dim_type == "螺纹" or re.search(r"^[Mm]\d", normalized):
            return "thread_size", 1.0, ["标注文本包含螺纹前缀 M"], None, None

        if re.search(r"\d+(?:\.\d+)?[xX×]\d+(?:\.\d+)?(?:%%d|°)", normalized):
            return "chamfer", 1.0, [
                "标注文本符合倒角格式",
                "倒角表示外部尖角削除，不表示内陷槽或凹坑",
            ], None, None

        inferred_role = self._infer_linear_role_from_annotation_geometry(
            dimension,
            reconstruction_context,
        )
        if inferred_role is not None:
            return inferred_role

        return "unresolved_linear", 0.0, ["裸线性尺寸缺少足够文本语义"], None, None

    def _infer_linear_role_from_annotation_geometry(
        self,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str], str, str] | None:
        if not self._is_linear_dimension_type(dimension):
            return None

        line = self._nearest_associated_line(dimension)
        orientation = self._line_orientation(line) if line else None
        view_name = self._locate_dimension_view(dimension, reconstruction_context)
        inferred_from_span = False
        span = None
        if orientation is None or view_name is None:
            span = self._build_dimension_span(dimension, reconstruction_context)
            if span:
                orientation = orientation or span.get("orientation")
                view_name = view_name or span.get("view_name")
                inferred_from_span = True

        if orientation is None or view_name is None:
            return None
        if inferred_from_span and span and not self._span_matches_view_extent(
            span,
            reconstruction_context,
        ):
            return None

        if orientation == "horizontal":
            if view_name == "main":
                return self._linear_geometry_candidate(
                    "profile_length",
                    0.8,
                    ["主视图中的水平标注线候选"],
                )
            if view_name in ("left", "right", "top"):
                return self._linear_geometry_candidate(
                    "projected_profile_horizontal_extent",
                    0.8,
                    [f"{view_name} 视图中的水平外形尺寸候选"],
                )
        elif orientation == "vertical":
            if view_name == "main":
                return self._linear_geometry_candidate(
                    "profile_height",
                    0.8,
                    ["主视图中的竖直外形尺寸候选"],
                )
            if view_name in ("left", "right", "top"):
                return self._linear_geometry_candidate(
                    "projected_profile_vertical_extent",
                    0.85,
                    [f"{view_name} 视图中的竖直外形尺寸候选"],
                )

        inferred_by_value = self._infer_linear_role_from_value_and_near_view(
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

    @staticmethod
    def _linear_geometry_candidate(
        role: str,
        confidence: float,
        evidence: List[str],
    ) -> tuple[str, float, List[str], str, str]:
        return role, confidence, evidence, "legacy_linear_geometry_candidate", "candidate"

    def _infer_linear_role_from_value_and_near_view(
        self,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[str, float, List[str], str, str] | None:
        value = dimension.get("value")
        if not isinstance(value, (int, float)):
            return None
        position = dimension.get("position") or []
        if len(position) < 2:
            return None

        view = self._nearest_view_to_point(position, reconstruction_context)
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
                return self._linear_geometry_candidate(
                    "projected_profile_vertical_extent",
                    0.85,
                    [f"线性尺寸值等于{view_name}视图竖向外形尺寸候选"],
                )
        if abs(float(value) - width) <= max(width * 0.08, 1e-6):
            if view_name == "main":
                return self._linear_geometry_candidate(
                    "profile_length",
                    0.8,
                    ["线性尺寸值等于主视图水平外包络候选"],
                )
            if view_name in ("top", "bottom", "left", "right"):
                return self._linear_geometry_candidate(
                    "projected_profile_horizontal_extent",
                    0.85,
                    [f"线性尺寸值等于{view_name}视图水平外形尺寸候选"],
                )
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

    def _build_dimension_span(
        self,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        if not self._is_linear_dimension_type(dimension):
            return None
        raw_points = dimension.get("definition_points", []) or []
        points = raw_points[:2]
        if len(points) >= 2 and not self._is_real_point(points[0]) and not self._is_real_point(points[1]):
            points = [
                point for point in raw_points
                if self._is_real_point(point)
            ]
        if len(points) < 2:
            return None
        start = points[0]
        end = points[1]
        line = {"start": start, "end": end}
        orientation = self._line_orientation(line)
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
            "view_name": self._locate_point_view(midpoint, reconstruction_context),
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

    @staticmethod
    def _apply_dimension_chain_roles(
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> None:
        DimensionChainRoleCandidateApplier.apply(bindings, reconstruction_context)

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
