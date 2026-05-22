#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the stage-specific payload for part semantic understanding."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Dict, Iterable, List


class SemanticUnderstandingPayloadBuilder:
    """Summarize reconstruction context into evidence for semantic generation."""

    PAYLOAD_VERSION = "semantic_understanding_payload_v1"

    def build(self, reconstruction_context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "payload_version": self.PAYLOAD_VERSION,
            "task": {
                "stage": "semantic_understanding",
                "goal": "infer structured part semantics from adjudicated drawing evidence",
            },
            "drawing": deepcopy(reconstruction_context.get("drawing", {}) or {}),
            "view_structure": self._build_view_structure(reconstruction_context),
            "geometry_evidence": self._build_geometry_evidence(reconstruction_context),
            "dimension_evidence": self._build_dimension_evidence(reconstruction_context),
            "semantic_policy": deepcopy(
                reconstruction_context.get("semantic_policy", {}) or {}
            ),
            "recovery_hints": self._build_recovery_hints(reconstruction_context),
            "output_contract": {
                "format": "json_object",
                "schema_name": "part_semantics",
                "must_not_output": ["markdown", "reasoning_process"],
            },
        }

    def _build_view_structure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        view_analysis = context.get("view_analysis", {}) or {}
        return {
            "drawing_type": view_analysis.get("drawing_type"),
            "confidence": view_analysis.get("confidence"),
            "reason_summary": view_analysis.get("reason_summary", ""),
            "warnings": deepcopy(view_analysis.get("warnings", []) or []),
            "views": [
                self._compact_view(view)
                for view in view_analysis.get("views", []) or []
            ],
            "relationships": deepcopy(view_analysis.get("relationships", []) or []),
        }

    @staticmethod
    def _compact_view(view: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": view.get("name"),
            "label": view.get("label"),
            "bbox": deepcopy(view.get("bbox")),
            "centroid": deepcopy(view.get("centroid")),
            "entity_count": view.get("entity_count"),
            "layers": deepcopy(view.get("layers", []) or []),
            "entity_type_count": deepcopy(
                view.get("entity_type_count") or view.get("type_count") or {}
            ),
        }

    def _build_geometry_evidence(self, context: Dict[str, Any]) -> Dict[str, Any]:
        entities = self._collect_source_entities(context)
        geometry_summary = context.get("geometry_summary", {}) or {}
        return {
            "entity_type_count": deepcopy(
                (context.get("drawing", {}) or {}).get("entity_type_count", {})
            ),
            "entity_count": (context.get("drawing", {}) or {}).get("entity_count"),
            "line_summary": (
                self._summarize_lines(entities)
                if entities else deepcopy(geometry_summary.get("line_summary", {}))
            ),
            "circle_summary": (
                self._summarize_circles(entities)
                if entities else deepcopy(geometry_summary.get("circle_summary", {}))
            ),
            "arc_summary": (
                self._summarize_arcs(entities)
                if entities else deepcopy(geometry_summary.get("arc_summary", {}))
            ),
            "polyline_summary": (
                self._summarize_polylines(entities)
                if entities else deepcopy(geometry_summary.get("polyline_summary", {}))
            ),
            "view_shape_hints": self._build_view_shape_hints(context),
        }

    @staticmethod
    def _collect_source_entities(context: Dict[str, Any]) -> List[Dict[str, Any]]:
        entities = list(context.get("source_entities", []) or [])
        if entities:
            return entities
        for view in (context.get("view_analysis", {}) or {}).get("views", []) or []:
            entities.extend(view.get("entities", []) or [])
        return entities

    @staticmethod
    def _build_view_shape_hints(context: Dict[str, Any]) -> Dict[str, Any]:
        hints: Dict[str, Any] = {}
        for view in (context.get("view_analysis", {}) or {}).get("views", []) or []:
            type_count = view.get("entity_type_count") or {}
            name = str(view.get("name") or "unknown")
            hints[name] = {
                "bbox": deepcopy(view.get("bbox")),
                "entity_count": view.get("entity_count"),
                "line_count": int(type_count.get("LINE", 0) or 0),
                "circle_arc_count": (
                    int(type_count.get("CIRCLE", 0) or 0)
                    + int(type_count.get("ARC", 0) or 0)
                ),
                "polyline_count": int(type_count.get("LWPOLYLINE", 0) or 0),
            }
        return hints

    def _summarize_lines(self, entities: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        lines = [
            entity for entity in entities
            if str(entity.get("type", "")).upper() == "LINE"
        ]
        orientations: Dict[str, int] = {"horizontal": 0, "vertical": 0, "diagonal": 0}
        lengths: List[float] = []
        for line in lines:
            start = line.get("start") or []
            end = line.get("end") or []
            if len(start) < 2 or len(end) < 2:
                continue
            dx = float(end[0]) - float(start[0])
            dy = float(end[1]) - float(start[1])
            length = math.hypot(dx, dy)
            lengths.append(length)
            if abs(dx) >= abs(dy) * 2.5:
                orientations["horizontal"] += 1
            elif abs(dy) >= abs(dx) * 2.5:
                orientations["vertical"] += 1
            else:
                orientations["diagonal"] += 1
        return {
            "count": len(lines),
            "orientation_count": orientations,
            "length_range": self._numeric_range(lengths),
        }

    def _summarize_circles(self, entities: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        radii = [
            float(entity.get("radius"))
            for entity in entities
            if str(entity.get("type", "")).upper() == "CIRCLE"
            and isinstance(entity.get("radius"), (int, float))
        ]
        return {
            "count": len(radii),
            "radius_values": self._unique_numbers(radii),
            "radius_range": self._numeric_range(radii),
        }

    def _summarize_arcs(self, entities: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
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
            "radius_values": self._unique_numbers(radii),
            "radius_range": self._numeric_range(radii),
        }

    @staticmethod
    def _summarize_polylines(entities: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        polylines = [
            entity for entity in entities
            if str(entity.get("type", "")).upper() in ("LWPOLYLINE", "POLYLINE")
        ]
        vertex_counts = [
            len(entity.get("vertices", []) or [])
            for entity in polylines
        ]
        return {
            "count": len(polylines),
            "closed_count": sum(1 for entity in polylines if entity.get("closed")),
            "vertex_counts": vertex_counts[:12],
        }

    @staticmethod
    def _build_dimension_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
        semantic_policy = context.get("semantic_policy", {}) or {}
        return {
            "dimensions": [
                SemanticUnderstandingPayloadBuilder._compact_dimension(dimension)
                for dimension in context.get("dimensions", []) or []
            ],
            "dimension_source": semantic_policy.get("dimension_source"),
            "dimension_bindings": deepcopy(
                semantic_policy.get("dimension_bindings", []) or []
            ),
            "dimension_plan": deepcopy(semantic_policy.get("dimension_plan", {}) or {}),
        }

    @staticmethod
    def _compact_dimension(dimension: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "text",
            "value",
            "type",
            "position",
            "measurement",
            "dimension_type",
            "callout",
            "repeat_count",
            "radius_value",
            "diameter_value",
            "thread_value",
        )
        return {key: deepcopy(dimension.get(key)) for key in keep_keys if key in dimension}

    @staticmethod
    def _build_recovery_hints(context: Dict[str, Any]) -> Dict[str, Any]:
        semantic_policy = context.get("semantic_policy", {}) or {}
        return {
            "user_modeling_hint": (
                context.get("user_modeling_hint")
                or semantic_policy.get("user_modeling_hint")
                or ""
            ),
            "user_modeling_hint_policy": (
                context.get("user_modeling_hint_policy")
                or semantic_policy.get("user_modeling_hint_policy")
                or "drawing_facts_override_user_hint"
            ),
            "assumptions": deepcopy(semantic_policy.get("assumptions", []) or []),
            "feature_constraints": deepcopy(
                semantic_policy.get("feature_constraints", {}) or {}
            ),
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
