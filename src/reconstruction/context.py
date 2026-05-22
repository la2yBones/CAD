#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建从 CAD 分析到三维重建的结构化交接数据。"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


class ReconstructionContextBuilder:
    """创建面向模型的稳定上下文，不在此层做语义猜测。"""

    CONTEXT_VERSION = "reconstruction_context_v1"

    def build(
        self,
        geometry_data: Dict[str, Any],
        view_analysis: Optional[Dict[str, Any]],
        dimension_data: Optional[Dict[str, Any]],
        local_relationships: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entities = geometry_data.get("entities", []) or []
        views = (view_analysis or {}).get("views", []) or []
        dimensions = (dimension_data or {}).get("dimensions", []) or []
        relationships = local_relationships or geometry_data.get("_local_relationships") or {}

        return {
            "context_version": self.CONTEXT_VERSION,
            "drawing": {
                "version": geometry_data.get("version"),
                "units": geometry_data.get("units"),
                "entity_count": len(entities),
                "entity_type_count": self._count_entity_types(entities),
                "layer_count": self._count_layers(entities),
            },
            "geometry_summary": self._summarize_geometry(entities),
            "view_analysis": {
                "drawing_type": (view_analysis or {}).get("drawing_type"),
                "confidence": (view_analysis or {}).get("confidence"),
                "reason_summary": (view_analysis or {}).get("reason_summary", ""),
                "warnings": (view_analysis or {}).get("warnings", []),
                "views": [self._compact_view(view) for view in views],
                "relationships": (view_analysis or {}).get("relationships", []),
            },
            "dimensions": [self._compact_dimension(dim) for dim in dimensions],
            "local_geometry": {
                "summary": relationships.get("summary"),
                "entity_pairs": relationships.get("entity_pairs", []),
            },
            "source_entities": [self._compact_entity(entity) for entity in entities],
        }

    def _compact_view(self, view: Dict[str, Any]) -> Dict[str, Any]:
        entities = view.get("entities", []) or []
        return {
            "name": view.get("name"),
            "label": view.get("type") or view.get("label"),
            "bbox": view.get("bbox"),
            "centroid": view.get("centroid"),
            "entity_count": view.get("entity_count", len(entities)),
            "layers": view.get("layers", []),
            "entity_type_count": self._count_entity_types(entities),
            "entities": [self._compact_entity(entity) for entity in entities],
        }

    @staticmethod
    def _compact_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "type",
            "layer",
            "start",
            "end",
            "center",
            "radius",
            "vertices",
            "closed",
            "start_angle",
            "end_angle",
            "measurement",
            "rendered_text",
            "text",
            "text_position",
            "dimension_type",
            "definition_points",
        )
        return {key: entity.get(key) for key in keep_keys if key in entity}

    @staticmethod
    def _compact_dimension(dimension: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "text",
            "value",
            "type",
            "position",
            "associated_lines",
            "definition_points",
            "measurement",
            "dimension_type",
        )
        return {key: dimension.get(key) for key in keep_keys if key in dimension}

    @staticmethod
    def _count_entity_types(entities: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for entity in entities:
            entity_type = str(entity.get("type", "unknown"))
            result[entity_type] = result.get(entity_type, 0) + 1
        return result

    @staticmethod
    def _count_layers(entities: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for entity in entities:
            layer = str(entity.get("layer", "default"))
            result[layer] = result.get(layer, 0) + 1
        return result

    @classmethod
    def _summarize_geometry(cls, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "line_summary": cls._summarize_lines(entities),
            "circle_summary": cls._summarize_circles(entities),
            "arc_summary": cls._summarize_arcs(entities),
            "polyline_summary": cls._summarize_polylines(entities),
        }

    @staticmethod
    def _summarize_lines(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        lines = [
            entity for entity in entities
            if str(entity.get("type", "")).upper() == "LINE"
        ]
        orientations = {"horizontal": 0, "vertical": 0, "diagonal": 0}
        lengths: List[float] = []
        for line in lines:
            start = line.get("start") or []
            end = line.get("end") or []
            if len(start) < 2 or len(end) < 2:
                continue
            dx = float(end[0]) - float(start[0])
            dy = float(end[1]) - float(start[1])
            lengths.append(math.hypot(dx, dy))
            if abs(dx) >= abs(dy) * 2.5:
                orientations["horizontal"] += 1
            elif abs(dy) >= abs(dx) * 2.5:
                orientations["vertical"] += 1
            else:
                orientations["diagonal"] += 1
        return {
            "count": len(lines),
            "orientation_count": orientations,
            "length_range": ReconstructionContextBuilder._numeric_range(lengths),
        }

    @staticmethod
    def _summarize_circles(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        radii = [
            float(entity.get("radius"))
            for entity in entities
            if str(entity.get("type", "")).upper() == "CIRCLE"
            and isinstance(entity.get("radius"), (int, float))
        ]
        return {
            "count": len(radii),
            "radius_values": ReconstructionContextBuilder._unique_numbers(radii),
            "radius_range": ReconstructionContextBuilder._numeric_range(radii),
        }

    @staticmethod
    def _summarize_arcs(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        arcs = [
            entity for entity in entities
            if str(entity.get("type", "")).upper() == "ARC"
        ]
        radii = [
            float(entity.get("radius"))
            for entity in arcs
            if isinstance(entity.get("radius"), (int, float))
        ]
        return {
            "count": len(arcs),
            "radius_values": ReconstructionContextBuilder._unique_numbers(radii),
            "radius_range": ReconstructionContextBuilder._numeric_range(radii),
        }

    @staticmethod
    def _summarize_polylines(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        polylines = [
            entity for entity in entities
            if str(entity.get("type", "")).upper() in ("LWPOLYLINE", "POLYLINE")
        ]
        return {
            "count": len(polylines),
            "closed_count": sum(1 for entity in polylines if entity.get("closed")),
            "vertex_counts": [
                len(entity.get("vertices", []) or [])
                for entity in polylines
            ][:12],
        }

    @staticmethod
    def _numeric_range(values: List[float]) -> List[float]:
        if not values:
            return []
        return [min(values), max(values)]

    @staticmethod
    def _unique_numbers(values: List[float]) -> List[float]:
        unique: List[float] = []
        for value in values:
            rounded = round(float(value), 6)
            if rounded not in unique:
                unique.append(rounded)
        return unique[:20]

    def build_summary(self, full_context: Dict[str, Any]) -> Dict[str, Any]:
        """从完整重建上下文生成精简摘要，用于截断重试或低 token 场景。

        砍掉：source_entities 详细坐标、每个 view 的 entities 列表、
        local_geometry.entity_pairs 详细数据。
        保留：drawing 元信息、视图 bbox/统计、投影关系、尺寸清单、
        关键轮廓特征摘要。
        """
        drawing = full_context.get("drawing", {})
        view_analysis = full_context.get("view_analysis", {})
        views = view_analysis.get("views", []) or []
        dimensions = full_context.get("dimensions", []) or []

        summary_views = []
        for view in views:
            summary_views.append({
                "name": view.get("name"),
                "label": view.get("label"),
                "bbox": view.get("bbox"),
                "centroid": view.get("centroid"),
                "entity_count": view.get("entity_count"),
                "entity_type_count": view.get("entity_type_count"),
                "layers": view.get("layers", []),
            })

        summary = {
            "context_version": "reconstruction_summary_v1",
            "drawing": drawing,
            "view_analysis": {
                "drawing_type": view_analysis.get("drawing_type"),
                "confidence": view_analysis.get("confidence"),
                "reason_summary": view_analysis.get("reason_summary", ""),
                "warnings": view_analysis.get("warnings", []),
                "views": summary_views,
                "relationships": view_analysis.get("relationships", []),
            },
            "dimensions": dimensions,
            "shape_hints": self._derive_shape_hints(views),
        }
        if "semantic_policy" in full_context:
            summary["semantic_policy"] = full_context["semantic_policy"]
        return summary

    @staticmethod
    def _derive_shape_hints(views: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从视图统计中提取轻量形状提示，供 LLM 在极简重试时使用。"""
        hints: Dict[str, Any] = {}
        for view in views:
            name = view.get("name", "unknown")
            type_counts = view.get("entity_type_count", {})
            circle_arc_count = type_counts.get("CIRCLE", 0) + type_counts.get("ARC", 0)
            line_count = type_counts.get("LINE", 0)
            hints[name] = {
                "circle_arc_count": circle_arc_count,
                "line_count": line_count,
                "bbox": view.get("bbox"),
            }
        return hints
