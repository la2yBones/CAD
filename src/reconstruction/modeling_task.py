#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建模任务载荷构建、完整性诊断和指令生成出口。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from .semantic_adjudication_view import SemanticAdjudicationView
from .semantic_postprocessor import PartSemanticsPostprocessor


BLOCKING_HINT_MARKERS = (
    "主体厚度",
    "主体深度",
    "主体方向",
    "主体外形",
    "拉伸深度",
    "拉伸方向",
    "轮廓不闭合",
    "外形不闭合",
    "厚度缺失",
    "深度缺失",
    "missing body",
    "missing depth",
    "extrusion depth missing",
    "body depth",
    "profile not closed",
)


class ModelingTaskReadinessChecker:
    """判断建模任务载荷是否足以进入建模指令生成阶段。"""

    def check(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        missing: List[str] = []
        risks: List[str] = []

        selected_path = (payload.get("object") or {}).get("selected_modeling_path")
        if not selected_path:
            missing.append("selected_modeling_path")

        features = payload.get("features") or {}
        dimensions = payload.get("dimensions") or {}
        recovery_hints = payload.get("recovery_hints") or {}

        if not self._has_body_source(features):
            missing.append("body_source")

        if (
            self._only_unresolved_or_candidate_dimensions(dimensions)
            and not self._has_explicit_body_metric(features)
        ):
            missing.append("authoritative_modeling_dimensions")

        if selected_path == "planar_extrude":
            self._check_planar(features, missing)
        elif selected_path == "revolve":
            self._check_revolve(features, missing)
        elif selected_path == "semantic_reconstruction":
            self._check_semantic_reconstruction(payload, features, dimensions, missing)

        for warning in self._body_blocking_hints(recovery_hints):
            risks.append(warning)
            if not self._semantic_reconstruction_can_continue_with_warning(
                selected_path,
                payload,
                features,
                dimensions,
            ):
                missing.append("body_closure_risk")

        missing = list(dict.fromkeys(missing))
        risks = list(dict.fromkeys(risks))
        ready = not missing
        return {
            "ready": ready,
            "severity": "ok" if ready else "blocking",
            "missing": missing,
            "risks": risks,
            "recommended_action": (
                "continue_with_warnings" if ready and risks else
                "continue" if ready else
                "needs_clarification"
            ),
        }

    def _has_body_source(self, features: Dict[str, Any]) -> bool:
        if features.get("base"):
            return True
        planar = features.get("planar_modeling")
        if isinstance(planar, dict) and planar.get("profile"):
            return True
        revolve = features.get("revolve_modeling")
        if isinstance(revolve, dict) and revolve.get("profile_points"):
            return True
        return False

    def _only_unresolved_or_candidate_dimensions(self, dimensions: Dict[str, Any]) -> bool:
        if dimensions.get("modeling_dimensions"):
            return False
        if dimensions.get("allowed_dimensions") or dimensions.get("construction_dimensions"):
            return False
        return bool(dimensions.get("candidate_dimensions") or dimensions.get("unresolved_dimensions"))

    @staticmethod
    def _has_explicit_body_metric(features: Dict[str, Any]) -> bool:
        planar = features.get("planar_modeling")
        if isinstance(planar, dict) and planar.get("extrusion_depth") not in (None, ""):
            return True
        revolve = features.get("revolve_modeling")
        if isinstance(revolve, dict) and revolve.get("profile_points"):
            return True
        return False

    @staticmethod
    def _check_planar(features: Dict[str, Any], missing: List[str]) -> None:
        planar = features.get("planar_modeling")
        if not isinstance(planar, dict):
            missing.append("planar_modeling")
            return
        if not planar.get("profile"):
            missing.append("planar_profile")
        if planar.get("extrusion_direction") in (None, "", "unknown"):
            missing.append("extrusion_direction")
        if planar.get("extrusion_depth") in (None, ""):
            missing.append("extrusion_depth")

    @staticmethod
    def _check_revolve(features: Dict[str, Any], missing: List[str]) -> None:
        revolve = features.get("revolve_modeling")
        if not isinstance(revolve, dict):
            missing.append("revolve_modeling")
            return
        if not revolve.get("axis_point"):
            missing.append("axis_point")
        if not revolve.get("axis_direction"):
            missing.append("axis_direction")
        if not revolve.get("profile_points"):
            missing.append("profile_points")

    @staticmethod
    def _check_semantic_reconstruction(
        payload: Dict[str, Any],
        features: Dict[str, Any],
        dimensions: Dict[str, Any],
        missing: List[str],
    ) -> None:
        has_dimensions = bool(
            dimensions.get("modeling_dimensions")
            or dimensions.get("allowed_dimensions")
            or dimensions.get("construction_dimensions")
        )
        has_primitive_body = bool(features.get("base"))
        has_body_operation = ModelingTaskReadinessChecker._has_semantic_body_operation(payload)
        if not ((has_dimensions and has_body_operation) or has_primitive_body):
            missing.append("semantic_body_dimensions_or_primitive")

    @staticmethod
    def _semantic_reconstruction_can_continue_with_warning(
        selected_path: str,
        payload: Dict[str, Any],
        features: Dict[str, Any],
        dimensions: Dict[str, Any],
    ) -> bool:
        if selected_path != "semantic_reconstruction":
            return False
        has_dimensions = bool(
            dimensions.get("modeling_dimensions")
            or dimensions.get("allowed_dimensions")
            or dimensions.get("construction_dimensions")
        )
        return bool(
            has_dimensions
            and ModelingTaskReadinessChecker._has_semantic_body_operation(payload)
        )

    @staticmethod
    def _has_semantic_body_operation(payload: Dict[str, Any]) -> bool:
        operations = payload.get("modeling_operations") or []
        if not isinstance(operations, list):
            return False
        body_markers = (
            "revolve",
            "extrude",
            "primitive",
            "base",
            "body",
            "主体",
            "基体",
        )
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            text = " ".join(
                str(operation.get(key, ""))
                for key in ("operation", "kind", "description", "target")
            ).lower()
            if any(marker in text for marker in body_markers):
                return True
        return False

    @staticmethod
    def _body_blocking_hints(recovery_hints: Dict[str, Any]) -> List[str]:
        values = []
        values.extend(recovery_hints.get("uncertainties", []) or [])
        values.extend(recovery_hints.get("warnings", []) or [])
        blocking = []
        for value in values:
            text = str(value or "").strip()
            lower = text.lower()
            if any(marker.lower() in lower for marker in BLOCKING_HINT_MARKERS):
                blocking.append(text)
        return blocking


class ModelingTaskContextBuilder:
    """构建建模约束和恢复提示。"""

    def build_constraints(
        self,
        *,
        semantic_policy: Dict[str, Any],
        modeling_path_decision: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        decision = modeling_path_decision or {}
        return {
            "feature_constraints": deepcopy(
                semantic_policy.get("feature_constraints", {}) or {}
            ),
            "assumptions": deepcopy(semantic_policy.get("assumptions", []) or []),
            "modeling_path_decision": {
                "modeling_path": decision.get("modeling_path"),
                "reason": decision.get("reason", ""),
                "fallback_from_path_clarification": bool(
                    decision.get("fallback_from_path_clarification")
                ),
            },
            "partial_modeling_policy": {
                "complete_main_body_first": True,
                "record_detail_failures_as_skipped_features": True,
                "record_only_confirmed_required_detail_failures_as_skipped_features": True,
                "speculative_or_unannotated_details_go_to_warnings": True,
                "do_not_use_unresolved_dimensions_for_key_geometry": True,
                "do_not_treat_recovery_warnings_as_modeling_facts": True,
            },
            "forbidden_inputs": [
                "raw geometry entities",
                "view entity lists",
                "local geometry relationship pairs",
                "full reconstruction context",
                "full part semantics object",
            ],
        }

    def build_recovery_hints(
        self,
        *,
        semantics: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
        semantic_policy: Dict[str, Any],
        recovery_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "user_modeling_hint": (
                reconstruction_context.get("user_modeling_hint")
                or semantic_policy.get("user_modeling_hint")
                or semantics.get("user_modeling_hint")
                or ""
            ),
            "user_modeling_hint_policy": (
                reconstruction_context.get("user_modeling_hint_policy")
                or semantic_policy.get("user_modeling_hint_policy")
                or semantics.get("user_modeling_hint_policy")
                or "drawing_facts_override_user_hint"
            ),
            "path_clarification_fallback": deepcopy(
                semantics.get("path_clarification_fallback")
            ),
            "uncertainties": deepcopy(semantics.get("uncertainties", []) or []),
            "warnings": deepcopy(semantics.get("warnings", []) or []),
            "warning_policy": (
                "warnings and uncertainties explain risk only; they are not "
                "modeling permissions and must not introduce new dimensions or features"
            ),
            "previous_partial_result": self._sanitize_recovery_context(recovery_context),
        }

    @classmethod
    def _sanitize_recovery_context(
        cls,
        recovery_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not recovery_context:
            return {}

        sanitized: Dict[str, Any] = {}
        for key in (
            "partial_modeling_recovery",
            "pre_modeling_recovery",
            "script_quality_recovery",
            "skipped_features",
            "partial_completion_reason",
            "previous_output_paths",
            "script_validation_errors",
            "script_failure_error",
            "self_correction_request",
            "self_correction_result",
            "self_correction_stage",
        ):
            if recovery_context.get(key):
                sanitized[key] = deepcopy(recovery_context[key])

        previous = recovery_context.get("previous_modeling_instructions") or {}
        if isinstance(previous, dict):
            previous_summary = {
                key: deepcopy(previous.get(key))
                for key in (
                    "analysis_summary",
                    "modeling_strategy",
                    "warnings",
                    "completed_features",
                    "skipped_features",
                    "partial_completion_reason",
                )
                if previous.get(key)
            }
            if previous_summary:
                sanitized["previous_modeling_instruction_summary"] = previous_summary

        if sanitized.get("script_quality_recovery"):
            sanitized["script_recovery_policy"] = (
                "上一版脚本未通过执行前校验；重新生成时必须修复 script_validation_errors，"
                "不要重复输出同类脚本形态。不要把失败脚本全文作为事实来源。"
            )
        return sanitized


class ModelingTaskDimensionsBuilder:
    """将语义裁决尺寸转换为建模任务尺寸契约。"""

    _ADJUDICATION_DIMENSION_FIELDS = frozenset({
        "dimension_roles",
        "derived_dimensions",
        "dimension_candidates",
        "derived_dimension_candidates",
    })

    def build(
        self,
        *,
        semantics: Dict[str, Any],
        semantic_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        dimension_plan = semantic_policy.get("dimension_plan", {}) or {}
        adjudication_view = SemanticAdjudicationView.from_policy(semantic_policy)
        payload: Dict[str, Any] = {
            "dimension_source": (
                semantic_policy.get("dimension_source")
                or semantics.get("dimension_source")
            ),
        }
        if adjudication_view.is_successful:
            slim_adjudication = {
                k: v
                for k, v in adjudication_view.to_dict().items()
                if k not in self._ADJUDICATION_DIMENSION_FIELDS
            }
            payload["semantic_adjudication"] = slim_adjudication
            payload["modeling_dimensions"] = adjudication_view.modeling_dimensions
            payload["dimensions_policy"] = (
                "modeling_dimensions is the single source of truth for all "
                "dimension values; dimension_roles and derived_dimensions have "
                "been merged into modeling_dimensions with resolved values"
            )
            return payload

        payload["semantic_adjudication"] = adjudication_view.to_dict()
        payload.update({
            "allowed_dimensions": deepcopy(
                dimension_plan.get("allowed_dimensions", []) or []
            ),
            "construction_dimensions": deepcopy(
                dimension_plan.get("construction_dimensions", []) or []
            ),
            "unresolved_dimensions": deepcopy(
                dimension_plan.get("unresolved_dimensions", []) or []
            ),
            "excluded_dimensions": deepcopy(
                dimension_plan.get("excluded_dimensions", []) or []
            ),
            "candidate_dimensions": deepcopy(
                dimension_plan.get("candidate_dimensions", []) or []
            ),
            "rules": deepcopy(dimension_plan.get("rules", []) or []),
        })
        return payload


class ModelingTaskBuilder:
    """将语义重建输出转换为阶段专用任务载荷。"""

    TASK_VERSION = "modeling_task_v1"

    def __init__(
        self,
        dimensions_builder: Optional[ModelingTaskDimensionsBuilder] = None,
        context_builder: Optional[ModelingTaskContextBuilder] = None,
    ):
        self.dimensions_builder = dimensions_builder or ModelingTaskDimensionsBuilder()
        self.context_builder = context_builder or ModelingTaskContextBuilder()
        self.postprocessor = PartSemanticsPostprocessor()
        self.readiness_checker = ModelingTaskReadinessChecker()

    def build(
        self,
        *,
        part_semantics: Optional[Dict[str, Any]] = None,
        reconstruction_context: Optional[Dict[str, Any]] = None,
        modeling_path_decision: Optional[Dict[str, Any]] = None,
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = reconstruction_context or {}
        policy = context.get("semantic_policy", {}) or {}
        semantics = self.postprocessor.normalize(part_semantics or {}, context)

        payload = {
            "task_version": self.TASK_VERSION,
            "object": self._build_object(semantics, modeling_path_decision),
            "features": self._build_features(semantics),
            "modeling_operations": self._build_modeling_operations(semantics),
            "dimensions": self.dimensions_builder.build(
                semantics=semantics,
                semantic_policy=policy,
            ),
            "constraints": self.context_builder.build_constraints(
                semantic_policy=policy,
                modeling_path_decision=modeling_path_decision,
            ),
            "recovery_hints": self.context_builder.build_recovery_hints(
                semantics=semantics,
                reconstruction_context=context,
                semantic_policy=policy,
                recovery_context=recovery_context,
            ),
        }
        payload["readiness"] = self.readiness_checker.check(payload)
        return payload

    @staticmethod
    def _build_object(
        semantics: Dict[str, Any],
        modeling_path_decision: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        decision = modeling_path_decision or {}
        return {
            "part_type": semantics.get("part_type", "unknown"),
            "summary": semantics.get("summary", ""),
            "confidence": semantics.get("confidence"),
            "coordinate_system": deepcopy(semantics.get("coordinate_system", {})),
            "preferred_modeling_path": semantics.get("preferred_modeling_path"),
            "selected_modeling_path": decision.get("modeling_path"),
            "modeling_path_reason": decision.get("reason", ""),
        }

    @staticmethod
    def _build_features(semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "base": deepcopy(semantics.get("base_features", []) or []),
            "additive": deepcopy(semantics.get("additive_features", []) or []),
            "subtractive": deepcopy(semantics.get("subtractive_features", []) or []),
            "planar_modeling": deepcopy(semantics.get("planar_modeling_semantics")),
            "revolve_modeling": deepcopy(semantics.get("revolve_modeling_semantics")),
        }

    @staticmethod
    def _build_modeling_operations(semantics: Dict[str, Any]) -> List[Dict[str, Any]]:
        llm_operations = semantics.get("modeling_operations")
        if isinstance(llm_operations, list) and llm_operations:
            return deepcopy(llm_operations)
        return _build_modeling_operations_from_features(semantics)


class ModelingTaskOutlet:
    """建模指令生成前的唯一合法载荷出口。"""

    def __init__(self, builder: Optional[ModelingTaskBuilder] = None):
        self.builder = builder or ModelingTaskBuilder()

    def build_payload(
        self,
        *,
        part_semantics: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.builder.build(
            part_semantics=part_semantics,
            reconstruction_context=adjudicated_context,
            modeling_path_decision=modeling_path_decision,
            recovery_context=recovery_context,
        )

    def generate_instructions(
        self,
        *,
        instruction_generator: Any,
        modeling_path_decision: Dict[str, Any],
        part_semantics: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        extrude_height: float,
        adjudicated_context: Dict[str, Any],
        file_path: Optional[str],
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        modeling_task_payload = self.build_payload(
            part_semantics=part_semantics,
            adjudicated_context=adjudicated_context,
            modeling_path_decision=modeling_path_decision,
            recovery_context=recovery_context,
        )
        readiness = modeling_task_payload.get("readiness") or {}
        if readiness.get("severity") == "blocking":
            return self._blocked_by_readiness(modeling_task_payload)
        instructions = instruction_generator.generate(
            geometry_data,
            view_analysis,
            dimension_data,
            extrude_height,
            reconstruction_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_task_payload=modeling_task_payload,
            file_path=file_path,
        )
        if isinstance(instructions, dict):
            instructions.setdefault("_modeling_task_payload", modeling_task_payload)
        return instructions

    @staticmethod
    def _blocked_by_readiness(modeling_task_payload: Dict[str, Any]) -> Dict[str, Any]:
        readiness = modeling_task_payload.get("readiness") or {}
        missing = readiness.get("missing", []) or []
        risks = readiness.get("risks", []) or []
        return {
            "analysis_summary": "建模任务载荷尚不足以生成可靠主体模型。",
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": [],
            "completed_features": [],
            "skipped_features": [],
            "partial_completion_reason": "",
            "warnings": [
                "建模任务完整性诊断阻塞第三阶段大模型调用。",
                f"缺失项: {', '.join(str(item) for item in missing) or '无'}",
                *[f"风险: {risk}" for risk in risks],
            ],
            "blocked_by_task_readiness": True,
            "task_readiness": readiness,
        }


_KIND_LABELS = {
    "plate": "平板",
    "block": "方块",
    "cylinder": "圆柱",
    "profile_extrusion": "轮廓拉伸体",
    "other": "其他基体",
    "boss": "凸台",
    "rib": "加强筋",
    "shoulder": "台阶",
    "through_hole": "通孔",
    "blind_hole": "盲孔",
    "counterbore": "沉孔",
    "slot": "槽",
    "cutout": "切口",
    "fillet": "圆角",
    "chamfer": "倒角",
    "hole": "孔",
    "rectangular_plate": "矩形板",
}


def _feature_kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def _describe_base(base_features: list) -> str:
    if not base_features:
        return "主体"
    parts = []
    for feat in base_features[:3]:
        kind = feat.get("kind", "")
        desc = feat.get("description", "")
        if desc:
            parts.append(desc)
        elif kind:
            parts.append(_feature_kind_label(kind))
    return "、".join(parts) if parts else "主体"


def _build_modeling_operations_from_features(semantics: Dict[str, Any]) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    coordinate_system = semantics.get("coordinate_system") or {}
    profile_plane = coordinate_system.get("profile_plane", "XY")
    depth_axis = coordinate_system.get("depth_axis", "Z")
    base_features = semantics.get("base_features") or []
    additive_features = semantics.get("additive_features") or []
    subtractive_features = semantics.get("subtractive_features") or []
    planar = semantics.get("planar_modeling_semantics") or {}
    revolve = semantics.get("revolve_modeling_semantics")

    if planar:
        extrusion_dir = planar.get("extrusion_direction") or depth_axis
        extrusion_depth = planar.get("extrusion_depth")
        dims = planar.get("dimensions") or {}
        op: Dict[str, Any] = {
            "operation": "extrude_profile",
            "description": _describe_base(base_features),
            "profile_plane": profile_plane,
            "extrusion_direction": extrusion_dir,
        }
        if extrusion_depth is not None:
            op["extrusion_depth"] = extrusion_depth
        if dims:
            op["profile_dimensions"] = dims
        cut_features = planar.get("cut_features") or []
        if cut_features:
            op["cut_features"] = cut_features
        operations.append(op)
    elif revolve:
        axis_point = revolve.get("axis_point") or {}
        axis_dir = revolve.get("axis_direction") or depth_axis
        angle = revolve.get("angle_degrees")
        profile_points = revolve.get("profile_points") or []
        op = {
            "operation": "revolve_profile",
            "description": _describe_base(base_features),
            "axis_point": axis_point,
            "axis_direction": axis_dir,
        }
        if angle is not None:
            op["angle_degrees"] = angle
        if profile_points:
            op["profile_points"] = profile_points
        operations.append(op)
    elif base_features:
        for feat in base_features:
            kind = feat.get("kind", "unknown")
            desc = feat.get("description", "")
            dims = feat.get("dimensions") or {}
            operations.append({
                "operation": "create_base",
                "feature_kind": kind,
                "description": desc or _feature_kind_label(kind),
                "dimensions": dims,
            })

    for feat in additive_features:
        kind = feat.get("kind", "unknown")
        desc = feat.get("description", "")
        dims = feat.get("dimensions") or {}
        operations.append({
            "operation": "add_feature",
            "feature_kind": kind,
            "description": desc or _feature_kind_label(kind),
            "dimensions": dims,
        })

    for feat in subtractive_features:
        kind = feat.get("kind", "unknown")
        desc = feat.get("description", "")
        dims = feat.get("dimensions") or {}
        op = {
            "operation": "subtract_feature",
            "feature_kind": kind,
            "description": desc or _feature_kind_label(kind),
            "dimensions": dims,
        }
        if kind == "through_hole":
            diameter = dims.get("diameter") or feat.get("diameter")
            if diameter:
                op["diameter"] = diameter
            center = dims.get("center") or feat.get("center")
            if center:
                op["center"] = center
        elif kind == "blind_hole":
            diameter = dims.get("diameter") or feat.get("diameter")
            depth = dims.get("depth") or feat.get("depth")
            if diameter:
                op["diameter"] = diameter
            if depth:
                op["depth"] = depth
        elif kind in ("chamfer", "fillet"):
            size = dims.get("size") or dims.get("radius") or dims.get("distance")
            if size:
                op["size"] = size
            edges = dims.get("edges") or dims.get("edge_count")
            if edges:
                op["edges"] = edges
        operations.append(op)

    return operations
