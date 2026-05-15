#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建从 CAD 分析到三维重建的结构化交接数据。"""
from __future__ import annotations

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
        keep_keys = ("text", "value", "type", "position", "associated_lines")
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
