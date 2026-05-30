#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零件语义的后处理，位于校验和建模任务组装之前。"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional

from .semantic_dimension_authority import SemanticDimensionAuthority
from src.utils.modeling_utils import looks_like_english_sentence


class PartSemanticsPostprocessor:
    """在第二阶段边界归一化 LLM 零件语义。"""

    USER_VISIBLE_LIST_FIELDS = ("uncertainties", "warnings")

    def normalize(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return result
        normalized = deepcopy(result)
        self._normalize_modeling_path(normalized)
        self._remove_unauthorized_key_dimensions(normalized, reconstruction_context)
        self._inject_circle_cut_features(normalized, reconstruction_context)
        self._normalize_user_visible_language(normalized)
        return normalized

    def _normalize_modeling_path(self, result: Dict[str, Any]) -> None:
        path_aliases = {
            "旋转建模": "revolve",
            "回转建模": "revolve",
            "旋转": "revolve",
            "回转": "revolve",
            "平面拉伸": "planar_extrude",
            "拉伸": "planar_extrude",
            "语义重建": "semantic_reconstruction",
            "通用语义重建": "semantic_reconstruction",
        }
        preferred_path = result.get("preferred_modeling_path")
        if isinstance(preferred_path, str):
            normalized_path = (
                path_aliases.get(preferred_path.strip())
                or self._normalize_modeling_path_token(preferred_path)
            )
            if normalized_path:
                result["preferred_modeling_path"] = normalized_path

        revolve = result.get("revolve_modeling_semantics")
        if not isinstance(revolve, dict):
            return

        required_revolve_fields = {
            "axis_point",
            "axis_direction",
            "profile_points",
            "angle_degrees",
            "uncertainties",
        }
        if required_revolve_fields.issubset(revolve):
            return

        result["revolve_modeling_semantics"] = None
        if result.get("preferred_modeling_path") == "revolve":
            result["preferred_modeling_path"] = "semantic_reconstruction"
        uncertainties = result.setdefault("uncertainties", [])
        if isinstance(uncertainties, list):
            uncertainties.append(
                "回转语义缺少精确轴线或轮廓点，已降级为语义重建路径处理"
            )

    def _remove_unauthorized_key_dimensions(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None,
    ) -> None:
        if not reconstruction_context:
            return
        dimensions = result.get("key_dimensions")
        if not isinstance(dimensions, list):
            return

        authority = SemanticDimensionAuthority(reconstruction_context)
        if authority.has_authoritative_values:
            permitted_values = authority.allowed_values + authority.construction_values
        elif result.get("dimension_source") == "annotation":
            permitted_values = authority.permitted_annotation_values
        else:
            return

        kept = []
        removed = []
        for dimension in dimensions:
            value = dimension.get("value") if isinstance(dimension, dict) else None
            if not isinstance(value, (int, float)):
                kept.append(dimension)
                continue
            if authority.matches_value(float(value), permitted_values):
                kept.append(dimension)
            else:
                removed.append(dimension)

        if not removed:
            return
        result["key_dimensions"] = kept
        message = f"已移除 {len(removed)} 个未获语义裁决许可的关键尺寸。"
        self._append_list_message(result, "uncertainties", message)
        self._append_list_message(
            result,
            "warnings",
            "存在模型输出的未授权关键尺寸，已在进入建模任务前拦截。",
        )

    def _inject_circle_cut_features(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None,
    ) -> None:
        if not reconstruction_context:
            return
        planar = result.get("planar_modeling_semantics")
        if not isinstance(planar, dict):
            return

        circles = self._profile_circle_candidates(reconstruction_context)
        if not circles:
            return

        existing = self._existing_circle_feature_keys(result)
        injected = []
        for circle in circles:
            key = self._circle_feature_key(circle)
            if key in existing:
                continue
            feature = self._circle_feature_payload(circle)
            injected.append(feature)
            existing.add(key)

        if not injected:
            return

        subtractive = result.setdefault("subtractive_features", [])
        if isinstance(subtractive, list):
            subtractive.extend(deepcopy(injected))

        cut_features = planar.setdefault("cut_features", [])
        if isinstance(cut_features, list):
            cut_features.extend(deepcopy(injected))

        message = f"已根据 CAD 轮廓线 CIRCLE 实体补全 {len(injected)} 个可定位圆孔。"
        self._append_list_message(result, "warnings", message)

    def _profile_circle_candidates(
        self,
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        package = (
            (reconstruction_context.get("semantic_policy", {}) or {})
            .get("drawing_evidence_package", {})
            or reconstruction_context.get("drawing_evidence_package", {})
            or {}
        )
        views = package.get("view_candidates", []) or []
        profile_view = self._select_profile_view(views)
        profile_view_id = profile_view.get("id") if profile_view else None
        profile_centroid = self._clean_point(
            (profile_view or {}).get("centroid")
            or self._bbox_center((profile_view or {}).get("bbox"))
        )

        source_circles = self._source_circle_entities(reconstruction_context)
        candidates = []
        for item in package.get("geometry_candidates", []) or []:
            if str(item.get("source_entity_type") or "").upper() != "CIRCLE":
                continue
            if item.get("candidate_kind") != "circle":
                continue
            if profile_view_id and item.get("source_view_candidate_id") not in (None, profile_view_id):
                continue
            center = self._clean_point(item.get("center"))
            radius = item.get("radius")
            if not center or not isinstance(radius, (int, float)):
                continue
            layer = item.get("layer") or self._matching_source_layer(
                source_circles,
                center,
                float(radius),
            )
            if self._is_construction_layer(layer):
                continue
            circle = {
                "id": item.get("id"),
                "center": center,
                "radius": float(radius),
                "diameter": round(float(radius) * 2.0, 6),
                "bbox": deepcopy(item.get("bbox")),
                "layer": layer,
                "source_view_candidate_id": item.get("source_view_candidate_id"),
            }
            if profile_centroid:
                circle["center_relative_to_profile"] = [
                    round(center[0] - profile_centroid[0], 6),
                    round(center[1] - profile_centroid[1], 6),
                ]
            candidates.append(circle)
        return self._dedupe_circles(candidates)

    @staticmethod
    def _select_profile_view(views: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not views:
            return {}
        return max(
            views,
            key=lambda view: (
                int((view.get("entity_type_count") or {}).get("CIRCLE", 0) or 0),
                int((view.get("entity_type_count") or {}).get("ARC", 0) or 0),
                int(view.get("entity_count") or 0),
            ),
        )

    @staticmethod
    def _source_circle_entities(context: Dict[str, Any]) -> List[Dict[str, Any]]:
        entities = list(context.get("source_entities", []) or [])
        if not entities:
            for view in (context.get("view_analysis", {}) or {}).get("views", []) or []:
                entities.extend(view.get("entities", []) or [])
        return [
            entity for entity in entities
            if str(entity.get("type") or "").upper() == "CIRCLE"
        ]

    @classmethod
    def _matching_source_layer(
        cls,
        source_circles: List[Dict[str, Any]],
        center: List[float],
        radius: float,
    ) -> str:
        for entity in source_circles:
            entity_center = cls._clean_point(entity.get("center"))
            entity_radius = entity.get("radius")
            if not entity_center or not isinstance(entity_radius, (int, float)):
                continue
            if abs(float(entity_radius) - radius) > 1e-6:
                continue
            if all(abs(entity_center[i] - center[i]) <= 1e-6 for i in range(2)):
                return str(entity.get("layer") or "")
        return ""

    @staticmethod
    def _is_construction_layer(layer: Any) -> bool:
        text = str(layer or "").lower()
        return any(
            marker in text
            for marker in ("点划", "中心", "构造", "隐藏", "center", "dash", "hidden", "construction")
        )

    @staticmethod
    def _existing_circle_feature_keys(result: Dict[str, Any]) -> set[tuple[float, float, float]]:
        features = []
        if isinstance(result.get("subtractive_features"), list):
            features.extend(result["subtractive_features"])
        planar = result.get("planar_modeling_semantics")
        if isinstance(planar, dict) and isinstance(planar.get("cut_features"), list):
            features.extend(planar["cut_features"])

        keys = set()
        for feature in features:
            if not isinstance(feature, dict):
                continue
            center = (
                feature.get("center")
                or feature.get("center_abs")
                or feature.get("center_absolute")
            )
            radius = feature.get("radius")
            diameter = feature.get("diameter")
            dimensions = feature.get("dimensions") if isinstance(feature.get("dimensions"), dict) else {}
            center = center or dimensions.get("center")
            radius = radius or dimensions.get("radius")
            diameter = diameter or dimensions.get("diameter")
            if not isinstance(radius, (int, float)) and isinstance(diameter, (int, float)):
                radius = float(diameter) / 2.0
            point = PartSemanticsPostprocessor._clean_point(center)
            if point and isinstance(radius, (int, float)):
                keys.add((round(point[0], 4), round(point[1], 4), round(float(radius), 4)))
        return keys

    @staticmethod
    def _circle_feature_key(circle: Dict[str, Any]) -> tuple[float, float, float]:
        center = circle.get("center") or [0.0, 0.0]
        return (round(float(center[0]), 4), round(float(center[1]), 4), round(float(circle.get("radius")), 4))

    @staticmethod
    def _circle_feature_payload(circle: Dict[str, Any]) -> Dict[str, Any]:
        radius = float(circle["radius"])
        diameter = float(circle["diameter"])
        relative = circle.get("center_relative_to_profile")
        description = f"CAD轮廓线圆孔，直径{diameter:g}"
        payload = {
            "kind": "through_hole",
            "description": description,
            "dimensions": {
                "radius": radius,
                "diameter": diameter,
                "center": deepcopy(circle["center"]),
            },
            "center": deepcopy(circle["center"]),
            "radius": radius,
            "diameter": diameter,
            "evidence": [circle.get("id")] if circle.get("id") else [],
            "source": "cad_circle_entity",
            "layer": circle.get("layer") or "",
        }
        if relative:
            payload["center_relative_to_profile"] = deepcopy(relative)
            payload["dimensions"]["center_relative_to_profile"] = deepcopy(relative)
        return payload

    @staticmethod
    def _dedupe_circles(circles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        smallest_by_center: Dict[tuple[float, float], Dict[str, Any]] = {}
        for circle in circles:
            center = circle.get("center") or [0.0, 0.0]
            center_key = (round(float(center[0]), 4), round(float(center[1]), 4))
            previous = smallest_by_center.get(center_key)
            if previous is None or float(circle.get("radius", 0.0)) < float(previous.get("radius", 0.0)):
                smallest_by_center[center_key] = circle

        seen = set()
        deduped = []
        for circle in smallest_by_center.values():
            key = PartSemanticsPostprocessor._circle_feature_key(circle)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(circle)
        return deduped

    @staticmethod
    def _clean_point(value: Any) -> List[float]:
        if not isinstance(value, list) or len(value) < 2:
            return []
        try:
            point = [float(value[0]), float(value[1])]
            if len(value) > 2:
                point.append(float(value[2]))
            return point
        except (TypeError, ValueError):
            return []

    @staticmethod
    def _bbox_center(value: Any) -> List[float]:
        if not isinstance(value, list) or len(value) < 4:
            return []
        try:
            return [
                (float(value[0]) + float(value[2])) / 2.0,
                (float(value[1]) + float(value[3])) / 2.0,
            ]
        except (TypeError, ValueError):
            return []

    def _normalize_user_visible_language(self, result: Dict[str, Any]) -> None:
        for field in self.USER_VISIBLE_LIST_FIELDS:
            value = result.get(field)
            if not isinstance(value, list):
                continue
            normalized_items = []
            for item in value:
                if isinstance(item, str) and looks_like_english_sentence(item):
                    normalized_items.append(
                        "模型返回了非中文风险说明，已替换为中文兜底提示；请依据图纸事实和未决项继续处理。"
                    )
                else:
                    normalized_items.append(item)
            result[field] = normalized_items

    @staticmethod
    def _normalize_modeling_path_token(value: str) -> Optional[str]:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if "revolve" in normalized or "回转" in normalized or "旋转" in normalized:
            return "revolve"
        if "planar" in normalized or "extrude" in normalized or "拉伸" in normalized:
            return "planar_extrude"
        if "semantic" in normalized or "语义" in normalized:
            return "semantic_reconstruction"
        return None



    @staticmethod
    def _append_list_message(result: Dict[str, Any], field: str, message: str) -> None:
        values = result.setdefault(field, [])
        if isinstance(values, list) and message not in values:
            values.append(message)
