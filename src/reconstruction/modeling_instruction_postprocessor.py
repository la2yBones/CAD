#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建模指令 JSON 的后处理，位于脚本执行之前。"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List

from .semantic_dimension_authority import SemanticDimensionAuthority
from .semantic_postprocessor import PartSemanticsPostprocessor
from src.utils.modeling_utils import looks_like_english_sentence


class ModelingInstructionPostprocessor:
    """归一化用户可见的建模指令元数据。"""

    USER_VISIBLE_LIST_FIELDS = ("warnings", "instructions")

    def normalize(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None = None,
        modeling_task_payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return result
        normalized = deepcopy(result)
        self._remove_unauthorized_key_dimensions(normalized, reconstruction_context)
        self._inject_circle_hole_script_repair(
            normalized,
            reconstruction_context,
            modeling_task_payload,
        )
        self._normalize_user_visible_lists(normalized)
        self._normalize_feature_records(normalized, "skipped_features")
        self._normalize_feature_records(normalized, "completed_features")
        return normalized

    def _remove_unauthorized_key_dimensions(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None,
    ) -> None:
        if not reconstruction_context:
            return
        key_dimensions = result.get("key_dimensions")
        if not isinstance(key_dimensions, list):
            return

        authority = SemanticDimensionAuthority(reconstruction_context)
        if authority.has_authoritative_values:
            permitted_values = authority.allowed_values + authority.construction_values
        elif authority.policy_dimension_source == "annotation":
            permitted_values = authority.permitted_annotation_values
        else:
            return

        kept: List[Any] = []
        removed_count = 0
        for dimension in key_dimensions:
            value = dimension.get("value") if isinstance(dimension, dict) else None
            if not isinstance(value, (int, float)):
                kept.append(dimension)
                continue
            if authority.matches_value(float(value), permitted_values):
                kept.append(dimension)
            else:
                removed_count += 1
        if not removed_count:
            return
        result["key_dimensions"] = kept
        self._append_warning(
            result,
            f"已拦截 {removed_count} 个未获语义裁决许可的建模关键尺寸。",
        )

    def _normalize_user_visible_lists(self, result: Dict[str, Any]) -> None:
        for field in self.USER_VISIBLE_LIST_FIELDS:
            values = result.get(field)
            if not isinstance(values, list):
                continue
            result[field] = [
                self._normalize_user_visible_text(item)
                for item in values
            ]

    def _normalize_feature_records(self, result: Dict[str, Any], field: str) -> None:
        values = result.get(field)
        if not isinstance(values, list):
            return
        normalized = []
        for item in values:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            record = dict(item)
            for text_field in ("reason", "risk", "evidence"):
                if text_field in record:
                    record[text_field] = self._normalize_user_visible_text(
                        record[text_field]
                    )
            normalized.append(record)
        result[field] = normalized

    def _inject_circle_hole_script_repair(
        self,
        result: Dict[str, Any],
        reconstruction_context: Dict[str, Any] | None,
        modeling_task_payload: Dict[str, Any] | None,
    ) -> None:
        script = result.get("freecad_script")
        if not isinstance(script, str) or not script.strip():
            return
        if "CAD_SYSTEM_CIRCLE_HOLE_REPAIR" in script:
            return
        if not reconstruction_context:
            return
        if not self._should_repair_circle_holes(modeling_task_payload):
            return

        semantic_context = {
            "semantic_policy": reconstruction_context.get("semantic_policy", {}),
            "source_entities": reconstruction_context.get("source_entities", []),
            "view_analysis": reconstruction_context.get("view_analysis", {}),
            "drawing_evidence_package": reconstruction_context.get("drawing_evidence_package", {}),
        }
        circles = PartSemanticsPostprocessor()._profile_circle_candidates(semantic_context)
        repair_holes = [
            {
                "radius": float(circle["radius"]),
                "center": circle.get("center_relative_to_profile"),
                "evidence": circle.get("id") or "",
            }
            for circle in circles
            if circle.get("center_relative_to_profile")
        ]
        repair_holes = self._filter_concentric_circle_repairs(repair_holes)
        if not repair_holes:
            return

        repair_block = self._circle_hole_repair_block(repair_holes)
        result["freecad_script"] = self._insert_before_first_part_show(script, repair_block)
        self._remove_skipped_hole_records_with_missing_location(result)
        self._append_warning(
            result,
            f"已根据 CAD 轮廓线圆孔几何为脚本补充 {len(repair_holes)} 个贯穿孔切除。",
        )

    @staticmethod
    def _should_repair_circle_holes(
        modeling_task_payload: Dict[str, Any] | None,
    ) -> bool:
        if not isinstance(modeling_task_payload, dict):
            return True
        selected_path = (
            (modeling_task_payload.get("object") or {}).get("selected_modeling_path")
            or ""
        )
        if selected_path == "planar_extrude":
            return True
        features = modeling_task_payload.get("features") or {}
        candidates: List[Any] = []
        if isinstance(features.get("subtractive"), list):
            candidates.extend(features["subtractive"])
        planar = features.get("planar_modeling")
        if isinstance(planar, dict) and isinstance(planar.get("cut_features"), list):
            candidates.extend(planar["cut_features"])

        for feature in candidates:
            if not isinstance(feature, dict):
                continue
            source = str(feature.get("source") or "")
            if source == "cad_circle_entity":
                return True
            if feature.get("center_relative_to_profile"):
                return True
        return False

    @staticmethod
    def _filter_concentric_circle_repairs(
        holes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_center: Dict[tuple[float, float], Dict[str, Any]] = {}
        center_order: List[tuple[float, float]] = []
        for hole in holes:
            center = hole.get("center") or [0, 0]
            try:
                key = (round(float(center[0]), 4), round(float(center[1]), 4))
                radius = float(hole.get("radius") or 0)
            except (TypeError, ValueError, IndexError):
                continue
            current = by_center.get(key)
            if current is None:
                center_order.append(key)
                by_center[key] = hole
                continue
            if radius < float(current.get("radius") or 0):
                by_center[key] = hole
        return [by_center[key] for key in center_order if key in by_center]

    @staticmethod
    def _circle_hole_repair_block(holes: List[Dict[str, Any]]) -> str:
        return (
            "\n# CAD_SYSTEM_CIRCLE_HOLE_REPAIR: 根据解析到的轮廓线 CIRCLE 补充贯穿孔。\n"
            f"_cad_circle_holes = {repr(holes)}\n"
            "_cad_target_shape = locals().get('final_shape') or locals().get('body') or locals().get('solid') or locals().get('result_shape')\n"
            "if _cad_target_shape is not None:\n"
            "    for _cad_hole in _cad_circle_holes:\n"
            "        try:\n"
            "            _cad_center = _cad_hole.get('center') or [0, 0]\n"
            "            _cad_radius = float(_cad_hole.get('radius') or 0)\n"
            "            if _cad_radius <= 0:\n"
            "                continue\n"
            "            _cad_cutter = Part.makeCylinder(\n"
            "                _cad_radius,\n"
            "                10000,\n"
            "                FreeCAD.Vector(float(_cad_center[0]), float(_cad_center[1]), -5000),\n"
            "                FreeCAD.Vector(0, 0, 1),\n"
            "            )\n"
            "            _cad_target_shape = _cad_target_shape.cut(_cad_cutter)\n"
            "            if 'completed_features' in globals():\n"
            "                completed_features.append({'name': 'CAD解析圆孔(d={:.6g})'.format(_cad_radius * 2), 'kind': 'detail'})\n"
            "        except Exception as e:\n"
            "            if 'runtime_warnings' in globals():\n"
            "                runtime_warnings.append('CAD解析圆孔补切失败: {}'.format(str(e)))\n"
            "    body = _cad_target_shape\n"
            "    final_shape = _cad_target_shape\n"
        )

    @staticmethod
    def _insert_before_first_part_show(script: str, block: str) -> str:
        index = script.find("Part.show(")
        if index < 0:
            return script.rstrip() + "\n" + block
        line_start = script.rfind("\n", 0, index)
        insert_at = 0 if line_start < 0 else line_start + 1
        return script[:insert_at] + block + script[insert_at:]

    @staticmethod
    def _remove_skipped_hole_records_with_missing_location(result: Dict[str, Any]) -> None:
        skipped = result.get("skipped_features")
        if not isinstance(skipped, list):
            return
        kept = []
        for item in skipped:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            combined = " ".join(
                str(item.get(field) or "")
                for field in ("name", "kind", "reason", "risk")
            )
            if "孔" in combined and any(marker in combined for marker in ("缺少孔位", "缺少位置信息", "无法确定")):
                continue
            kept.append(item)
        result["skipped_features"] = kept

    @classmethod
    def _normalize_user_visible_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if not looks_like_english_sentence(value):
            return value
        return "模型返回了非中文说明，已替换为中文兜底提示；请以图纸事实和已裁决尺寸为准。"

    @staticmethod
    def _append_warning(result: Dict[str, Any], message: str) -> None:
        warnings = result.setdefault("warnings", [])
        if not isinstance(warnings, list):
            warnings = [warnings]
            result["warnings"] = warnings
        if message not in warnings:
            warnings.append(message)
