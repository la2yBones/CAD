#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build traceable drawing evidence without deciding final engineering semantics."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class DrawingEvidencePackageBuilder:
    """Convert reconstruction context into stable evidence candidates."""

    PACKAGE_VERSION = "drawing_evidence_package_v1"

    def build(self, reconstruction_context: Dict[str, Any]) -> Dict[str, Any]:
        view_candidates = self._build_view_candidates(reconstruction_context)
        dimension_candidates = self._build_dimension_candidates(
            reconstruction_context,
            view_candidates,
        )
        geometry_candidates = self._build_geometry_candidates(
            reconstruction_context,
            view_candidates,
        )
        return {
            "package_version": self.PACKAGE_VERSION,
            "view_candidates": view_candidates,
            "dimension_candidates": dimension_candidates,
            "derived_dimension_candidates": self._build_derived_dimensions(
                dimension_candidates
            ),
            "geometry_candidates": geometry_candidates,
            "spatial_relations": self._build_spatial_relations(
                view_candidates,
                dimension_candidates,
                geometry_candidates,
            ),
        }

    def _build_view_candidates(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        views = list((context.get("view_analysis", {}) or {}).get("views", []) or [])
        views.sort(key=self._view_sort_key)
        candidates: List[Dict[str, Any]] = []
        for index, view in enumerate(views, start=1):
            candidate_id = f"V{index}"
            candidates.append({
                "id": candidate_id,
                "bbox": self._clean_number_list(view.get("bbox"), limit=4),
                "centroid": self._clean_number_list(view.get("centroid"), limit=3),
                "entity_count": view.get("entity_count"),
                "entity_type_count": deepcopy(
                    view.get("entity_type_count") or view.get("type_count") or {}
                ),
                "layers": deepcopy(view.get("layers", []) or []),
                "local_name_hint": view.get("name"),
                "local_label_hint": view.get("label"),
                "local_confidence": view.get("confidence"),
                "source": "view_analysis",
            })
        return candidates

    def _build_dimension_candidates(
        self,
        context: Dict[str, Any],
        view_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        dimensions = list(context.get("dimensions", []) or [])
        dimensions.sort(key=self._dimension_sort_key)
        candidates: List[Dict[str, Any]] = []
        for index, dimension in enumerate(dimensions, start=1):
            span = self._build_dimension_span(dimension)
            source_view_id = self._locate_dimension_view_id(
                dimension,
                span,
                view_candidates,
            )
            orientation = (
                span.get("orientation")
                if span
                else self._associated_line_orientation(dimension)
            )
            candidate = {
                "id": f"D{index}",
                "text": dimension.get("text"),
                "value": dimension.get("value"),
                "dimension_type": dimension.get("type")
                or dimension.get("dimension_type"),
                "orientation": orientation,
                "position": self._clean_number_list(dimension.get("position"), limit=3),
                "span": span,
                "source_view_candidate_id": source_view_id,
                "matches_view_extent": self._span_matches_view_extent(
                    span,
                    source_view_id,
                    view_candidates,
                ),
                "callout_family": self._callout_family(dimension),
                "repeat_count": dimension.get("repeat_count"),
                "radius_value": dimension.get("radius_value"),
                "diameter_value": dimension.get("diameter_value"),
                "thread_value": dimension.get("thread_value"),
                "near_geometry_ids": [],
                "source": "dimension_extraction",
            }
            candidates.append({k: v for k, v in candidate.items() if v not in (None, [])})
        return candidates

    def _build_geometry_candidates(
        self,
        context: Dict[str, Any],
        view_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        entities = list(context.get("source_entities", []) or [])
        if not entities:
            for view in (context.get("view_analysis", {}) or {}).get("views", []) or []:
                entities.extend(view.get("entities", []) or [])
        entities.sort(key=self._entity_sort_key)

        candidates: List[Dict[str, Any]] = []
        for entity in entities:
            entity_type = str(entity.get("type") or "").upper()
            if entity_type not in {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE"}:
                continue
            summary = self._geometry_summary(entity)
            if not summary:
                continue
            center = summary.get("center") or self._bbox_center(summary.get("bbox"))
            view_id = self._locate_point_view_id(center, view_candidates) if center else None
            candidate = {
                "id": f"G{len(candidates) + 1}",
                "candidate_kind": summary.pop("candidate_kind"),
                "source_entity_type": entity_type,
                "source_view_candidate_id": view_id,
                **summary,
            }
            candidates.append({k: v for k, v in candidate.items() if v not in (None, [])})
        return candidates

    def _build_derived_dimensions(
        self,
        dimensions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        linear = [
            item for item in dimensions
            if isinstance(item.get("value"), (int, float))
            and item.get("orientation") in {"horizontal", "vertical"}
        ]

        for group in self._group_by_view_and_orientation(linear):
            candidates.extend(self._adjacent_sum_candidates(group))
            candidates.extend(self._difference_candidates(group))

        candidates.sort(key=lambda item: (
            str(item.get("formula") or ""),
            float(item.get("value") or 0.0),
            ",".join(item.get("source_dimension_ids", []) or []),
        ))
        for index, candidate in enumerate(candidates, start=1):
            candidate["id"] = f"DD{index}"
        return candidates[:40]

    def _build_spatial_relations(
        self,
        views: List[Dict[str, Any]],
        dimensions: List[Dict[str, Any]],
        geometry: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        relations: List[Dict[str, Any]] = []
        for left_index, left in enumerate(views):
            for right in views[left_index + 1:]:
                overlap_x = self._bbox_axis_overlap_ratio(
                    left.get("bbox"),
                    right.get("bbox"),
                    axis=0,
                )
                overlap_y = self._bbox_axis_overlap_ratio(
                    left.get("bbox"),
                    right.get("bbox"),
                    axis=1,
                )
                if overlap_x >= 0.8:
                    relations.append(self._relation(
                        "aligned_x",
                        [left["id"], right["id"]],
                        confidence=round(overlap_x, 4),
                    ))
                if overlap_y >= 0.8:
                    relations.append(self._relation(
                        "aligned_y",
                        [left["id"], right["id"]],
                        confidence=round(overlap_y, 4),
                    ))

        for dimension in dimensions:
            view_id = dimension.get("source_view_candidate_id")
            if view_id:
                relations.append(self._relation(
                    "dimension_near_view",
                    [dimension["id"], view_id],
                    confidence=1.0,
                ))

        circles = [
            item for item in geometry
            if item.get("candidate_kind") in {"circle", "arc"}
            and item.get("center")
        ]
        for left_index, left in enumerate(circles):
            for right in circles[left_index + 1:]:
                if left.get("source_view_candidate_id") != right.get("source_view_candidate_id"):
                    continue
                if self._points_close(left.get("center"), right.get("center")):
                    relations.append(self._relation(
                        "concentric_2d",
                        [left["id"], right["id"]],
                        confidence=1.0,
                    ))

        for index, relation in enumerate(relations, start=1):
            relation["id"] = f"R{index}"
        return relations

    @staticmethod
    def _view_sort_key(view: Dict[str, Any]) -> Tuple[float, float, str]:
        bbox = view.get("bbox") or []
        if len(bbox) >= 4:
            return (float(bbox[1]), float(bbox[0]), str(view.get("name") or ""))
        centroid = view.get("centroid") or []
        if len(centroid) >= 2:
            return (float(centroid[1]), float(centroid[0]), str(view.get("name") or ""))
        return (0.0, 0.0, str(view.get("name") or ""))

    @staticmethod
    def _dimension_sort_key(dimension: Dict[str, Any]) -> Tuple[float, float, str, str]:
        position = dimension.get("position") or []
        x = float(position[0]) if len(position) >= 1 else 0.0
        y = float(position[1]) if len(position) >= 2 else 0.0
        return (y, x, str(dimension.get("text") or ""), str(dimension.get("type") or ""))

    @staticmethod
    def _entity_sort_key(entity: Dict[str, Any]) -> Tuple[str, float, float, float, str]:
        center = entity.get("center") or []
        if len(center) < 2:
            center = DrawingEvidencePackageBuilder._bbox_center(
                DrawingEvidencePackageBuilder._entity_bbox(entity)
            ) or [0.0, 0.0]
        radius = float(entity.get("radius") or 0.0)
        return (
            str(entity.get("type") or ""),
            float(center[1]),
            float(center[0]),
            radius,
            str(entity.get("layer") or ""),
        )

    @classmethod
    def _build_dimension_span(cls, dimension: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        points = list(dimension.get("definition_points", []) or [])[:2]
        if len(points) < 2:
            return None
        start, end = points[0], points[1]
        if not cls._is_point(start) or not cls._is_point(end):
            return None
        orientation = cls._line_orientation(start, end)
        if orientation is None:
            return None
        axis = 0 if orientation == "horizontal" else 1
        span_range = sorted((float(start[axis]), float(end[axis])))
        midpoint = [
            (float(start[0]) + float(end[0])) / 2,
            (float(start[1]) + float(end[1])) / 2,
            0.0,
        ]
        return {
            "start": cls._clean_number_list(start, limit=3),
            "end": cls._clean_number_list(end, limit=3),
            "axis": "x" if axis == 0 else "y",
            "orientation": orientation,
            "range": span_range,
            "midpoint": midpoint,
        }

    @classmethod
    def _associated_line_orientation(cls, dimension: Dict[str, Any]) -> Optional[str]:
        for item in dimension.get("associated_lines", []) or []:
            line = item.get("line") or item
            start = line.get("start") or []
            end = line.get("end") or []
            if cls._is_point(start) and cls._is_point(end):
                return cls._line_orientation(start, end)
        return None

    @staticmethod
    def _line_orientation(start: Sequence[Any], end: Sequence[Any]) -> Optional[str]:
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        if abs(dx) >= abs(dy) * 2.5:
            return "horizontal"
        if abs(dy) >= abs(dx) * 2.5:
            return "vertical"
        return None

    @classmethod
    def _locate_dimension_view_id(
        cls,
        dimension: Dict[str, Any],
        span: Optional[Dict[str, Any]],
        views: List[Dict[str, Any]],
    ) -> Optional[str]:
        point = (span or {}).get("midpoint") or dimension.get("position")
        return cls._locate_point_view_id(point, views)

    @staticmethod
    def _locate_point_view_id(
        point: Any,
        views: List[Dict[str, Any]],
    ) -> Optional[str]:
        if not isinstance(point, list) or len(point) < 2:
            return None
        x, y = float(point[0]), float(point[1])
        best_id = None
        best_distance = float("inf")
        for view in views:
            bbox = view.get("bbox") or []
            if len(bbox) < 4:
                continue
            min_x, min_y, max_x, max_y = map(float, bbox[:4])
            width = max(max_x - min_x, 1e-6)
            height = max(max_y - min_y, 1e-6)
            tolerance = max(width, height) * 0.6
            dx = max(min_x - x, 0.0, x - max_x)
            dy = max(min_y - y, 0.0, y - max_y)
            distance = math.hypot(dx, dy)
            if distance <= tolerance and distance < best_distance:
                best_distance = distance
                best_id = view.get("id")
        return best_id

    @staticmethod
    def _span_matches_view_extent(
        span: Optional[Dict[str, Any]],
        view_id: Optional[str],
        views: List[Dict[str, Any]],
    ) -> bool:
        if not span or not view_id:
            return False
        orientation = span.get("orientation")
        span_range = span.get("range") or []
        view = next((item for item in views if item.get("id") == view_id), None)
        bbox = (view or {}).get("bbox") or []
        if orientation not in {"horizontal", "vertical"} or len(span_range) < 2 or len(bbox) < 4:
            return False
        axis = 0 if orientation == "horizontal" else 1
        extent = sorted((float(bbox[axis]), float(bbox[axis + 2])))
        span_min, span_max = sorted((float(span_range[0]), float(span_range[1])))
        tolerance = max((extent[1] - extent[0]) * 0.08, 1e-6)
        return abs(span_min - extent[0]) <= tolerance and abs(span_max - extent[1]) <= tolerance

    @staticmethod
    def _callout_family(dimension: Dict[str, Any]) -> str:
        text = str(dimension.get("text") or "").replace(" ", "")
        dim_type = str(dimension.get("type") or dimension.get("dimension_type") or "")
        if dimension.get("callout"):
            return str(dimension.get("callout"))
        if dim_type == "半径" or text.upper().startswith("R"):
            return "radius_text"
        if dim_type == "直径" or any(symbol in text for symbol in ("φ", "Φ", "∅", "⌀", "Ø")):
            return "diameter_text"
        if dim_type == "螺纹" or text.upper().startswith("M"):
            return "thread_text"
        if "45" in text and any(mark in text for mark in ("x", "X", "×")):
            return "chamfer_text"
        return "linear_text"

    @classmethod
    def _geometry_summary(cls, entity: Dict[str, Any]) -> Dict[str, Any]:
        entity_type = str(entity.get("type") or "").upper()
        if entity_type == "CIRCLE":
            center = cls._clean_number_list(entity.get("center"), limit=3)
            radius = entity.get("radius")
            if not center or not isinstance(radius, (int, float)):
                return {}
            return {
                "candidate_kind": "circle",
                "center": center,
                "radius": float(radius),
                "bbox": [
                    center[0] - float(radius),
                    center[1] - float(radius),
                    center[0] + float(radius),
                    center[1] + float(radius),
                ],
            }
        if entity_type == "ARC":
            center = cls._clean_number_list(entity.get("center"), limit=3)
            radius = entity.get("radius")
            if not center or not isinstance(radius, (int, float)):
                return {}
            return {
                "candidate_kind": "arc",
                "center": center,
                "radius": float(radius),
                "start_angle": entity.get("start_angle"),
                "end_angle": entity.get("end_angle"),
                "bbox": [
                    center[0] - float(radius),
                    center[1] - float(radius),
                    center[0] + float(radius),
                    center[1] + float(radius),
                ],
            }
        if entity_type == "LINE":
            start = cls._clean_number_list(entity.get("start"), limit=3)
            end = cls._clean_number_list(entity.get("end"), limit=3)
            if not start or not end:
                return {}
            return {
                "candidate_kind": f"{cls._line_orientation(start, end) or 'diagonal'}_line",
                "start": start,
                "end": end,
                "bbox": cls._entity_bbox(entity),
                "layer": entity.get("layer"),
            }
        if entity_type in {"LWPOLYLINE", "POLYLINE"}:
            vertices = entity.get("vertices", []) or []
            bbox = cls._entity_bbox(entity)
            return {
                "candidate_kind": "polyline",
                "bbox": bbox,
                "closed": bool(entity.get("closed")),
                "vertex_count": len(vertices),
            }
        return {}

    @staticmethod
    def _group_by_view_and_orientation(
        dimensions: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for dimension in dimensions:
            key = (
                str(dimension.get("source_view_candidate_id") or ""),
                str(dimension.get("orientation") or ""),
            )
            groups.setdefault(key, []).append(dimension)
        return [items for items in groups.values() if len(items) >= 2]

    @classmethod
    def _adjacent_sum_candidates(
        cls,
        dimensions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        with_ranges = [
            item for item in dimensions
            if len(((item.get("span") or {}).get("range") or [])) >= 2
        ]
        with_ranges.sort(key=lambda item: (item["span"]["range"][0], item["span"]["range"][1]))
        results: List[Dict[str, Any]] = []
        for left, right in zip(with_ranges, with_ranges[1:]):
            left_range = left["span"]["range"]
            right_range = right["span"]["range"]
            if abs(float(left_range[1]) - float(right_range[0])) > 1e-6:
                continue
            value = float(left["value"]) + float(right["value"])
            results.append({
                "value": value,
                "formula": f"{left['id']} + {right['id']}",
                "source_dimension_ids": [left["id"], right["id"]],
                "candidate_kind": "sum",
                "evidence": ["同一视图同一方向的相邻标注尺寸可形成组合候选"],
            })
        return results

    @staticmethod
    def _difference_candidates(
        dimensions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for larger in dimensions:
            for smaller in dimensions:
                if larger is smaller:
                    continue
                if float(larger["value"]) <= float(smaller["value"]):
                    continue
                value = round(float(larger["value"]) - float(smaller["value"]), 6)
                if value <= 0:
                    continue
                results.append({
                    "value": value,
                    "formula": f"{larger['id']} - {smaller['id']}",
                    "source_dimension_ids": [larger["id"], smaller["id"]],
                    "candidate_kind": "difference",
                    "evidence": ["同一视图同一方向的标注尺寸可形成差值候选"],
                })
        return results

    @staticmethod
    def _relation(kind: str, refs: List[str], *, confidence: float) -> Dict[str, Any]:
        return {
            "relation_type": kind,
            "refs": refs,
            "confidence": confidence,
        }

    @staticmethod
    def _bbox_axis_overlap_ratio(
        left: Any,
        right: Any,
        *,
        axis: int,
    ) -> float:
        if not isinstance(left, list) or not isinstance(right, list):
            return 0.0
        if len(left) < 4 or len(right) < 4:
            return 0.0
        a1, a2 = sorted((float(left[axis]), float(left[axis + 2])))
        b1, b2 = sorted((float(right[axis]), float(right[axis + 2])))
        overlap = max(min(a2, b2) - max(a1, b1), 0.0)
        base = max(min(a2 - a1, b2 - b1), 1e-6)
        return overlap / base

    @staticmethod
    def _points_close(left: Any, right: Any, tolerance: float = 1e-4) -> bool:
        if not isinstance(left, list) or not isinstance(right, list):
            return False
        if len(left) < 2 or len(right) < 2:
            return False
        return (
            abs(float(left[0]) - float(right[0])) <= tolerance
            and abs(float(left[1]) - float(right[1])) <= tolerance
        )

    @staticmethod
    def _bbox_center(bbox: Any) -> Optional[List[float]]:
        if not isinstance(bbox, list) or len(bbox) < 4:
            return None
        return [
            (float(bbox[0]) + float(bbox[2])) / 2,
            (float(bbox[1]) + float(bbox[3])) / 2,
            0.0,
        ]

    @staticmethod
    def _entity_bbox(entity: Dict[str, Any]) -> List[float]:
        points: List[List[float]] = []
        for key in ("start", "end", "center"):
            point = entity.get(key)
            if isinstance(point, list) and len(point) >= 2:
                points.append([float(point[0]), float(point[1])])
        for vertex in entity.get("vertices", []) or []:
            if isinstance(vertex, list) and len(vertex) >= 2:
                points.append([float(vertex[0]), float(vertex[1])])
        if not points:
            return []
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    @staticmethod
    def _clean_number_list(value: Any, *, limit: int) -> List[float]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value[:limit]:
            if isinstance(item, (int, float)):
                result.append(float(item))
        return result

    @staticmethod
    def _is_point(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        )
