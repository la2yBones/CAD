#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在语义生成前裁决可安全使用的重建上下文。"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Sequence


class SemanticPolicy:
    """对尺寸来源和特征升级门槛做确定性裁决。"""

    UNKNOWN_ANSWER = "__unknown__"

    def evaluate(
        self,
        reconstruction_context: Dict[str, Any],
        clarification_answers: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
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
        if clarification_answers:
            dimension_bindings = self._apply_clarification_answers(
                dimension_bindings,
                clarification_answers,
            )
        dimension_plan = self._build_dimension_plan(dimension_bindings)
        clarification_questions = self._build_clarification_questions(
            dimension_bindings,
            reconstruction_context,
        )
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

        # 选择标注尺寸时，不再把可反推出测量尺寸的坐标细节暴露给 LLM。
        if dimension_source == "annotation":
            context.pop("source_entities", None)
            views = context.get("view_analysis", {}).get("views", []) or []
            for view in views:
                view.pop("entities", None)

        return context

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
                "semantic_role": semantic_role,
                "confidence": confidence,
                "evidence": evidence,
                "span": cls._build_dimension_span(dimension, reconstruction_context),
            })
        cls._apply_dimension_chain_roles(bindings)
        return bindings

    @classmethod
    def _build_dimension_plan(cls, bindings: List[Dict[str, Any]]) -> Dict[str, Any]:
        allowed_roles = {
            "profile_length",
            "profile_height",
            "radius",
            "diameter",
            "thread_size",
            "chamfer",
            "projected_profile_horizontal_extent",
            "projected_profile_vertical_extent",
        }
        segment_roles = {"profile_length_segment"}
        allowed_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if binding.get("semantic_role") in allowed_roles
        ]
        segment_dimensions = [
            cls._plan_item(binding)
            for binding in bindings
            if binding.get("semantic_role") in segment_roles
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
            "segment_dimensions": segment_dimensions,
            "unresolved_dimensions": unresolved_dimensions,
            "excluded_dimensions": excluded_dimensions,
            "rules": [
                "key_dimensions 只能使用 allowed_dimensions 中的值和语义角色。",
                "segment_dimensions 只能作为组合尺寸的证据，不能单独命名为总长、深度、对边、对角、法兰直径或孔径。",
                "unresolved_dimensions 不得进入 key_dimensions；若建模需要它们，必须写入 uncertainties 或触发追问。",
            ],
        }

    @classmethod
    def _plan_item(cls, binding: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "text": binding.get("text"),
            "value": binding.get("value"),
            "role": binding.get("semantic_role"),
            "confidence": binding.get("confidence"),
            "evidence": binding.get("evidence", []),
            "span": binding.get("span"),
        }

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
        if str(dimension.get("type") or "") != "线性":
            return None

        line = cls._nearest_associated_line(dimension)
        if not line:
            return None

        orientation = cls._line_orientation(line)
        if orientation is None:
            return None

        view_name = cls._locate_dimension_view(dimension, reconstruction_context)
        if orientation == "horizontal":
            if view_name == "main":
                return "profile_length", 0.8, ["主视图中的水平标注线"]
            if view_name in ("left", "right"):
                return "projected_profile_horizontal_extent", 0.8, [f"{view_name} 视图中的水平外形尺寸"]
        elif orientation == "vertical" and view_name in ("main", "left", "right"):
            return "profile_height", 0.7, ["竖直标注线"]

        return None

    @classmethod
    def _build_dimension_span(
        cls,
        dimension: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        if str(dimension.get("type") or "") != "线性":
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
    def _is_real_point(point: Any) -> bool:
        if not isinstance(point, list) or len(point) < 2:
            return False
        return abs(float(point[0])) > 1e-9 or abs(float(point[1])) > 1e-9

    @classmethod
    def _apply_dimension_chain_roles(cls, bindings: List[Dict[str, Any]]) -> None:
        span_bindings = [
            binding for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
            and binding.get("span")
            and isinstance(binding.get("value"), (int, float))
        ]
        cls._apply_projected_profile_extent_roles(span_bindings)
        cls._append_main_view_composite_length(bindings, span_bindings)

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
        clarification_answers: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        resolved = deepcopy(bindings)
        answer_to_role = {
            "bind_profile_length": "profile_length",
            "bind_profile_height": "profile_height",
        }
        for question_id, role in answer_to_role.items():
            if question_id not in clarification_answers:
                continue
            if cls._is_unknown_answer(clarification_answers[question_id]):
                cls._exclude_unresolved_for_question(resolved, question_id)
                continue
            cls._bind_selected_value(
                resolved,
                role=role,
                selected_value=clarification_answers[question_id],
            )

        for question_id, answer in clarification_answers.items():
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
        if question_id != "bind_profile_length":
            return
        for binding in bindings:
            if binding.get("semantic_role") == "unresolved_linear":
                binding["semantic_role"] = "excluded_by_user"
                binding["confidence"] = 0.0
                binding["evidence"] = ["用户不确定该标注是否为主视图总长，已排除自动绑定"]

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
            questions.append({
                "id": f"resolve_{role}",
                "text": f"{role} 出现多个互相冲突的标注值，请确认建模应采用哪一个。",
                "kind": "single_choice",
                "options": [
                    {
                        "label": cls._format_dimension_value(value),
                        "value": cls._format_dimension_value(value),
                    }
                    for value in values
                ],
                "reason": "同一关键尺寸角色存在多个不同标注值，继续自动建模会改变关键尺寸。",
            })
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
        unresolved = [
            binding for binding in bindings
            if binding.get("semantic_role") == "unresolved_linear"
            and isinstance(binding.get("value"), (int, float))
        ]
        if not unresolved:
            return []

        unresolved_options = [
            {
                "label": cls._binding_label(binding),
                "value": cls._format_dimension_value(binding["value"]),
            }
            for binding in unresolved
        ]
        unresolved_options.append({
            "label": "我不确定 / 这些都不要绑定为总长",
            "value": cls.UNKNOWN_ANSWER,
        })

        questions: List[Dict[str, Any]] = []
        required_roles = (
            ("profile_length", "主视图中的水平总尺寸"),
        )
        for role, label in required_roles:
            if role in bound_roles:
                continue
            questions.append({
                "id": f"bind_{role}",
                "text": f"请看图纸标注：哪一个值表示{label}？如果你也看不出来，选择“不确定”。",
                "kind": "single_choice",
                "options": unresolved_options,
                "reason": "多视图重建缺少这个关键尺寸；不确定时不会强行把某个裸尺寸绑定为总长。",
            })
        return questions

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
