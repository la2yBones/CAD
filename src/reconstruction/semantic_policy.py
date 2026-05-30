#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在语义生成前裁决可安全使用的重建上下文。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from .clarification import (
    CLARIFIABLE_CANDIDATE_ROLES,
    UNKNOWN_ANSWER,
    build_candidate_role_questions,
    build_conflicting_key_role_questions,
    build_missing_multiview_axis_questions,
)
from .clarification_response import ClarificationResponse, USER_MODELING_HINT_KEY
from .dimension_binding_builder import DimensionBindingBuilder
from .dimension_permission_plan import DimensionPermissionPlan
from .drawing_evidence import DrawingEvidencePackageBuilder
from .semantic_clarification_answers import (
    FEATURE_DETAIL_DIMENSION_KEY,
    SemanticClarificationAnswerApplier,
)


USER_MODELING_HINT_ASSUMPTION = (
    "用户提供了补充建模提示；该提示可用于解释建模意图和细节偏好，但不得覆盖图纸事实、关键尺寸来源、主体方向或主体外形。"
)

UNSTRUCTURED_HINT_UNBLOCKS_RECOVERY_ASSUMPTION = (
    "未结构化回答的追问不再阻塞本次局部恢复；相关裸尺寸仍不得进入 key_dimensions，必要时应降级为部分建模成果或跳过细节。"
)

UNRESOLVED_LINEAR_ASSUMPTION = (
    "裸线性尺寸尚未完成语义绑定；在没有额外证据前，不得把它们擅自命名为总长、对边、对角、法兰直径或孔径。"
)


@dataclass(frozen=True)
class PolicyAssumptionResult:
    """语义策略假设说明和追问清单的更新结果。"""

    assumptions: List[str]
    clarification_questions: List[Dict[str, Any]]


class SemanticPolicyAssumptionBuilder:
    """集中维护语义策略的用户可见假设说明。"""

    def build(
        self,
        *,
        base_assumptions: List[str],
        dimension_bindings: List[Dict[str, Any]],
        clarification_questions: List[Dict[str, Any]],
        user_modeling_hint: str | None,
    ) -> PolicyAssumptionResult:
        assumptions = list(base_assumptions)
        questions = list(clarification_questions)

        if user_modeling_hint:
            assumptions.append(USER_MODELING_HINT_ASSUMPTION)
            if questions:
                assumptions.append(UNSTRUCTURED_HINT_UNBLOCKS_RECOVERY_ASSUMPTION)
                questions = []

        if any(binding.get("semantic_role") == "unresolved_linear" for binding in dimension_bindings):
            assumptions.append(UNRESOLVED_LINEAR_ASSUMPTION)

        return PolicyAssumptionResult(
            assumptions=assumptions,
            clarification_questions=questions,
        )


@dataclass(frozen=True)
class DimensionSourceDecision:
    """尺寸来源裁决结果。"""

    dimension_source: str
    annotation_dimensions: List[Dict[str, Any]]
    assumptions: List[str]


class DimensionSourceDecider:
    """判断后续语义生成应使用标注尺寸还是几何尺寸。"""

    def decide(self, reconstruction_context: Dict[str, Any]) -> DimensionSourceDecision:
        dimensions = reconstruction_context.get("dimensions", []) or []
        annotation_dimensions = [
            dimension
            for dimension in dimensions
            if isinstance(dimension.get("value"), (int, float))
        ]

        if annotation_dimensions:
            return DimensionSourceDecision(
                dimension_source="annotation",
                annotation_dimensions=annotation_dimensions,
                assumptions=[
                    "存在可用尺寸标注，后续语义生成仅可使用标注尺寸；图形坐标仅保留形状提示。"
                ],
            )

        return DimensionSourceDecision(
            dimension_source="geometry",
            annotation_dimensions=[],
            assumptions=[
                "未发现可用尺寸标注，后续语义生成只能依据图形几何做保守解释。"
            ],
        )


def default_feature_constraints() -> Dict[str, Any]:
    return {
        "subtractive_features_require_explicit_evidence": True,
        "hidden_lines_alone_are_insufficient": True,
        "concentric_projection_alone_is_insufficient": True,
        "chamfer_is_external_corner_removal": True,
        "chamfer_must_not_create_recess_or_slot": True,
    }


def build_adjudicated_context(
    reconstruction_context: Dict[str, Any],
    *,
    dimension_source: str,
    dimension_bindings: List[Dict[str, Any]],
    dimension_plan: Dict[str, Any],
    feature_constraints: Dict[str, Any],
    assumptions: List[str],
    drawing_evidence_package: Dict[str, Any],
    user_modeling_hint: str = "",
    user_modeling_hint_policy: str = "",
) -> Dict[str, Any]:
    context = deepcopy(reconstruction_context)
    context["context_version"] = "adjudicated_context_v1"
    context["semantic_policy"] = {
        "dimension_source": dimension_source,
        "dimension_bindings": dimension_bindings,
        "dimension_plan": dimension_plan,
        "feature_constraints": feature_constraints,
        "assumptions": assumptions,
        "drawing_evidence_package": drawing_evidence_package,
    }
    if user_modeling_hint:
        context["semantic_policy"]["user_modeling_hint"] = user_modeling_hint
        context["semantic_policy"]["user_modeling_hint_policy"] = (
            user_modeling_hint_policy
        )
        context["user_modeling_hint"] = user_modeling_hint
        context["user_modeling_hint_policy"] = user_modeling_hint_policy

    if dimension_source == "annotation":
        context.pop("source_entities", None)
        views = context.get("view_analysis", {}).get("views", []) or []
        for view in views:
            view.pop("entities", None)

    return context


class SemanticPolicy:
    """对尺寸来源和特征升级门槛做确定性裁决。"""

    UNKNOWN_ANSWER = UNKNOWN_ANSWER
    USER_MODELING_HINT_KEY = USER_MODELING_HINT_KEY
    FEATURE_DETAIL_DIMENSION_KEY = FEATURE_DETAIL_DIMENSION_KEY
    CLARIFIABLE_CANDIDATE_ROLES = CLARIFIABLE_CANDIDATE_ROLES

    def evaluate(
        self,
        reconstruction_context: Dict[str, Any],
        clarification_answers: Mapping[str, Any] | ClarificationResponse | None = None,
    ) -> Dict[str, Any]:
        clarification_response = ClarificationResponse.from_input(clarification_answers)
        source_decision = DimensionSourceDecider().decide(reconstruction_context)
        annotation_dimensions = source_decision.annotation_dimensions
        dimension_source = source_decision.dimension_source
        assumptions = list(source_decision.assumptions)

        drawing_evidence_package = DrawingEvidencePackageBuilder().build(
            reconstruction_context
        )
        dimension_bindings = DimensionBindingBuilder().build(
            annotation_dimensions,
            reconstruction_context,
        )
        user_modeling_hint = clarification_response.user_modeling_hint
        if clarification_response.has_any_input():
            dimension_bindings = SemanticClarificationAnswerApplier().apply(
                dimension_bindings,
                clarification_response,
            )
        dimension_plan = self._build_dimension_plan(dimension_bindings)
        clarification_questions = self._build_clarification_questions(
            dimension_bindings,
            reconstruction_context,
        )
        assumption_result = SemanticPolicyAssumptionBuilder().build(
            base_assumptions=assumptions,
            dimension_bindings=dimension_bindings,
            clarification_questions=clarification_questions,
            user_modeling_hint=user_modeling_hint,
        )
        assumptions = assumption_result.assumptions
        clarification_questions = assumption_result.clarification_questions
        feature_constraints = default_feature_constraints()

        adjudicated_context = build_adjudicated_context(
            reconstruction_context,
            dimension_source=dimension_source,
            dimension_bindings=dimension_bindings,
            dimension_plan=dimension_plan,
            feature_constraints=feature_constraints,
            assumptions=assumptions,
            drawing_evidence_package=drawing_evidence_package,
            user_modeling_hint=user_modeling_hint,
            user_modeling_hint_policy=clarification_response.conflict_policy,
        )

        return {
            "dimension_source": dimension_source,
            "dimension_bindings": dimension_bindings,
            "dimension_plan": dimension_plan,
            "feature_constraints": feature_constraints,
            "clarification_questions": clarification_questions,
            "assumptions": assumptions,
            "drawing_evidence_package": drawing_evidence_package,
            "adjudicated_context": adjudicated_context,
        }

    @classmethod
    def _build_dimension_plan(cls, bindings: List[Dict[str, Any]]) -> Dict[str, Any]:
        return DimensionPermissionPlan.from_bindings(bindings).to_dict()

    @classmethod
    def _build_clarification_questions(
        cls,
        bindings: List[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        questions: List[Dict[str, Any]] = []
        questions.extend(build_conflicting_key_role_questions(bindings))
        questions.extend(build_candidate_role_questions(
            bindings,
            questions,
            roles=cls.CLARIFIABLE_CANDIDATE_ROLES,
            unknown_answer=cls.UNKNOWN_ANSWER,
        ))
        questions.extend(build_missing_multiview_axis_questions(
            bindings,
            reconstruction_context,
            unknown_answer=cls.UNKNOWN_ANSWER,
        ))
        return questions
