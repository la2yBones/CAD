#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追问问题构建、候选尺寸澄清和路径层追问。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .clarification_helpers import choice_option, clarification_question
from .clarification_response import ClarificationResponse
from .modeling_path import ModelingPathDecision
from .semantic_adjudication_session import SemanticAdjudicationSession


UNKNOWN_ANSWER = "__unknown__"

CLARIFIABLE_CANDIDATE_ROLES = (
    "profile_length",
    "profile_height",
    "extrusion_depth",
    "feature_depth",
    "feature_height",
    "feature_total_height",
    "thread_length",
    "projected_profile_horizontal_extent",
    "projected_profile_vertical_extent",
)


def build_candidate_role_questions(
    bindings: List[Dict[str, Any]],
    existing_questions: List[Dict[str, Any]],
    *,
    roles: Sequence[str] = CLARIFIABLE_CANDIDATE_ROLES,
    unknown_answer: str = UNKNOWN_ANSWER,
) -> List[Dict[str, Any]]:
    existing_ids = {str(question.get("id") or "") for question in existing_questions}
    questions: List[Dict[str, Any]] = []
    for role in roles:
        question_id = f"resolve_{role}"
        if question_id in existing_ids:
            continue
        if has_adjudicated_role(bindings, role):
            continue
        candidates = candidate_role_bindings(bindings, role)
        if not candidates:
            continue
        role_label = role_display_label(role)
        options = [
            choice_option(
                binding_label_with_evidence(binding),
                format_dimension_value(binding["value"]),
            )
            for binding in candidates
        ]
        options.append(choice_option(
            "不确定 / 暂不使用这些候选",
            unknown_answer,
        ))
        questions.append(clarification_question(
            question_id=question_id,
            text=f"系统只找到了{role_label}的候选值，请确认是否采用。",
            kind="single_choice",
            options=options,
            reason=f"{role_label}目前只是本地候选，不确认时不会作为最终建模尺寸。",
            example="如果图纸上能确认该标注表示这个尺寸，就选择对应值；看不出来请选择\u201c不确定\u201d。",
        ))
    return questions


def build_conflicting_key_role_questions(
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
        values = unique_values(binding.get("value") for binding in role_bindings)
        if len(values) <= 1:
            continue
        role_label = role_display_label(role)
        questions.append(clarification_question(
            question_id=f"resolve_{role}",
            text=f"图纸里有多个值都可能表示{role_label}，请确认建模采用哪一个。",
            kind="single_choice",
            options=[
                choice_option(
                    format_dimension_value(value),
                    format_dimension_value(value),
                )
                for value in values
            ],
            reason=f"{role_label}会影响主体尺寸；不确认时系统不会强行选择其中一个。",
            example="选择图纸上真正表示该尺寸的标注值；看不出来可在补充提示里说明。",
        ))
    return questions


def build_missing_multiview_axis_questions(
    bindings: List[Dict[str, Any]],
    reconstruction_context: Dict[str, Any],
    *,
    unknown_answer: str = UNKNOWN_ANSWER,
) -> List[Dict[str, Any]]:
    drawing_type = reconstruction_context.get("view_analysis", {}).get("drawing_type")
    if drawing_type not in ("two_view", "three_view"):
        return []

    bound_roles = {
        binding.get("semantic_role")
        for binding in bindings
        if binding.get("semantic_role") not in (None, "unresolved_linear")
    }
    questions: List[Dict[str, Any]] = []
    if not (
        "profile_length" in bound_roles
        or "projected_profile_horizontal_extent" in bound_roles
    ):
        role = "profile_length"
        candidates = subject_axis_candidates(bindings, role)
        if candidates:
            unresolved_options = [
                choice_option(
                    binding_label(binding),
                    format_dimension_value(binding["value"]),
                )
                for binding in candidates
            ]
            unresolved_options.append(choice_option(
                "我不确定 / 这些都不要绑定为总长",
                unknown_answer,
            ))
            questions.append(clarification_question(
                question_id=f"bind_{role}",
                text="请确认哪个标注值表示主视图中的水平总尺寸。如果你也看不出来，选择\u201c不确定\u201d。",
                kind="single_choice",
                options=unresolved_options,
                reason="多视图重建缺少这个关键尺寸；不确定时不会强行把某个裸尺寸绑定为总长。",
                example="选择图纸上表示总尺寸的值；不确定就选\u201c不确定\u201d。",
            ))
    return questions


def has_adjudicated_role(bindings: List[Dict[str, Any]], role: str) -> bool:
    return any(
        binding.get("semantic_role") == role
        and binding.get("binding_status") != "candidate"
        for binding in bindings
    )


def candidate_role_bindings(bindings: List[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    return [
        binding for binding in bindings
        if binding.get("semantic_role") == role
        and binding.get("binding_status") == "candidate"
        and isinstance(binding.get("value"), (int, float))
    ]


def is_candidate_clarification_question(question: Dict[str, Any]) -> bool:
    return (
        str(question.get("id") or "").startswith("resolve_")
        and question.get("kind") == "single_choice"
        and bool(question.get("options"))
    )


def clarification_option_label(option: Any) -> str:
    if isinstance(option, dict):
        return str(option.get("label") or option.get("value") or "")
    return str(option)


def clarification_option_value(option: Any) -> str:
    if isinstance(option, dict):
        return str(option.get("value") or option.get("label") or "")
    return str(option)


def build_candidate_clarification_summary(
    questions: List[Dict[str, Any]],
    answers: Dict[str, str],
) -> str:
    lines: List[str] = []
    for question in questions:
        if not is_candidate_clarification_question(question):
            continue
        question_id = str(question.get("id") or "")
        answer = str(answers.get(question_id) or "").strip()
        if not answer:
            continue
        text = str(question.get("text") or question_id).strip()
        if answer == UNKNOWN_ANSWER:
            lines.append(f"- {text}\n  结果：不采用候选值，系统不会把它作为建模尺寸。")
            continue
        selected_label = answer
        for option in question.get("options", []) or []:
            if clarification_option_value(option) == answer:
                selected_label = clarification_option_label(option)
                break
        lines.append(f"- {text}\n  结果：确认采用 {selected_label}。")
    if not lines:
        return ""
    return "即将提交以下候选尺寸处理结果：\n\n" + "\n".join(lines)


def role_display_label(role: str) -> str:
    labels = {
        "profile_length": "主视图水平总尺寸",
        "profile_height": "主视图竖向总尺寸",
        "projected_profile_horizontal_extent": "投影视图水平外形尺寸",
        "projected_profile_vertical_extent": "投影视图竖向外形尺寸",
    }
    return labels.get(role, "关键尺寸")


def subject_axis_candidates(
    bindings: List[Dict[str, Any]],
    role: str,
) -> List[Dict[str, Any]]:
    return [
        binding for binding in bindings
        if binding.get("semantic_role") == "unresolved_linear"
        and isinstance(binding.get("value"), (int, float))
        and is_subject_axis_candidate(binding, role)
    ]


def is_subject_axis_candidate(binding: Dict[str, Any], role: str) -> bool:
    span = binding.get("span") or {}
    if role == "profile_length":
        return (
            span.get("view_name") == "main"
            and span.get("orientation") == "horizontal"
        )
    if role == "profile_height":
        return (
            span.get("view_name") == "main"
            and span.get("orientation") == "vertical"
        )
    return False


def unique_values(values: Sequence[Any]) -> List[float]:
    unique: List[float] = []
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if not any(abs(numeric - existing) <= 1e-6 for existing in unique):
            unique.append(numeric)
    return unique


def binding_label(binding: Dict[str, Any]) -> str:
    text = str(binding.get("text") or "").strip()
    value = binding.get("value")
    if text:
        return text
    return format_dimension_value(value)


def binding_label_with_evidence(binding: Dict[str, Any]) -> str:
    label = binding_label(binding)
    evidence = binding.get("evidence") or []
    if evidence:
        return f"{label}（{str(evidence[0])}）"
    return label


def format_dimension_value(value: Any) -> str:
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else str(numeric)


class PathClarificationAnswerApplier:
    """把路径层追问答案写回显式零件语义。"""

    def apply(
        self,
        part_semantics: Dict[str, Any],
        clarification_answers: Mapping[str, Any] | ClarificationResponse,
    ) -> Dict[str, Any]:
        response = ClarificationResponse.from_input(
            clarification_answers,
            source_stage="modeling_path",
        )
        updated = deepcopy(part_semantics)
        planar = updated.setdefault("planar_modeling_semantics", {})
        if "provide_extrusion_depth" in response:
            planar["extrusion_depth"] = self._parse_numeric_answer(
                response.get("provide_extrusion_depth")
            )
        if "provide_extrusion_direction" in response:
            planar["extrusion_direction"] = response.get("provide_extrusion_direction")
        if "select_modeling_path" in response:
            updated["preferred_modeling_path"] = response.get("select_modeling_path")
        if response.user_modeling_hint:
            updated["user_modeling_hint"] = response.user_modeling_hint
            updated["user_modeling_hint_policy"] = response.conflict_policy
        return updated

    @staticmethod
    def _parse_numeric_answer(value: Any) -> Any:
        if isinstance(value, (int, float)):
            return value
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return value


def build_path_contract_pending_result(modeling_path_decision: Dict[str, Any]) -> Dict[str, Any]:
    """Build a modeling result that pauses execution for path-contract clarification."""
    return ClarificationOutlet().path_pending_result(modeling_path_decision)


def needs_path_clarification(modeling_path_decision: Dict[str, Any]) -> bool:
    """Return whether the path decision must pause for user clarification."""
    return ModelingPathDecision.from_mapping(modeling_path_decision).requires_clarification


def build_path_clarification_payload(
    *,
    modeling_result: Dict[str, Any],
    base_context: Dict[str, Any],
    policy_result: Dict[str, Any],
    adjudicated_context: Dict[str, Any],
    part_semantics: Dict[str, Any],
    modeling_path_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach path-layer recovery state to a pending reconstruction result."""
    return ClarificationOutlet().path_payload(
        modeling_result=modeling_result,
        base_context=base_context,
        policy_result=policy_result,
        adjudicated_context=adjudicated_context,
        part_semantics=part_semantics,
        modeling_path_decision=modeling_path_decision,
    )


def apply_path_clarification_answers(
    part_semantics: Dict[str, Any],
    clarification_answers: Mapping[str, Any] | ClarificationResponse,
) -> Dict[str, Any]:
    """Write path-layer clarification answers back into explicit part semantics."""
    return PathClarificationAnswerApplier().apply(
        part_semantics,
        clarification_answers,
    )


class ClarificationOutlet:
    """集中装配需要用户澄清时的语义重建返回结果。"""

    def from_policy_questions(
        self,
        *,
        policy_result: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
        clarification_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._pending_result(
            policy_result=policy_result,
            reconstruction_context=reconstruction_context,
            adjudicated_context=adjudicated_context,
            part_semantics=self.build_pending_semantics(policy_result),
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
            extrude_height=extrude_height,
            file_path=file_path,
            clarification_context=clarification_context,
        )

    def from_feature_detail_questions(
        self,
        *,
        policy_result: Dict[str, Any],
        feature_detail_questions: list[Dict[str, Any]],
        reconstruction_context: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
        clarification_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        enriched_policy = {
            **policy_result,
            "clarification_questions": feature_detail_questions,
        }
        return self._pending_result(
            policy_result=enriched_policy,
            reconstruction_context=reconstruction_context,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
            extrude_height=extrude_height,
            file_path=file_path,
            clarification_context=clarification_context,
        )

    def path_pending_result(
        self,
        modeling_path_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = ModelingPathDecision.from_mapping(modeling_path_decision)
        return {
            "analysis_summary": "",
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": [],
            "warnings": [
                "specialized modeling path semantics are incomplete; waiting for clarification"
            ],
            "blocked_by_clarification": True,
            "blocked_by_path_contract": True,
            "clarification_questions": decision.clarification_questions,
        }

    def path_payload(
        self,
        *,
        modeling_result: Dict[str, Any],
        base_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not modeling_result.get("blocked_by_path_contract"):
            return {}
        context = deepcopy(base_context)
        context.update({
            "clarification_stage": "modeling_path",
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
        })
        return {"clarification_context": context}

    def _pending_result(
        self,
        *,
        policy_result: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
        clarification_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        context = clarification_context or self.build_context(
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
            extrude_height=extrude_height,
            file_path=file_path,
            reconstruction_context=reconstruction_context,
            clarification_stage=self.clarification_stage_for_policy(policy_result),
        )
        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_instructions": self.build_pending_modeling_result(policy_result),
            "clarification_context": deepcopy(context),
        }

    @staticmethod
    def build_pending_semantics(policy_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "part_type": "unknown",
            "confidence": 0.0,
            "summary": "",
            "evidence": [],
            "candidate_interpretations": [],
            "coordinate_system": {
                "profile_plane": "unknown",
                "depth_axis": "unknown",
                "reason": "",
            },
            "dimension_source": policy_result["dimension_source"],
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "planar_modeling_semantics": {
                "profile": None,
                "extrusion_direction": "unknown",
                "extrusion_depth": None,
                "cut_features": [],
                "dimension_bindings": [],
                "uncertainties": ["semantic adjudication pending clarification"],
            },
            "revolve_modeling_semantics": None,
            "preferred_modeling_path": None,
            "key_dimensions": [],
            "uncertainties": [
                "semantic adjudication needs user clarification before automatic modeling can continue"
            ],
            "warnings": [],
        }

    @staticmethod
    def build_pending_modeling_result(policy_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_summary": "",
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": [],
            "warnings": [
                "semantic adjudication needs user clarification before automatic modeling can continue"
            ],
            "blocked_by_clarification": True,
            "clarification_questions": policy_result["clarification_questions"],
        }

    @staticmethod
    def build_context(
        *,
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
        reconstruction_context: Dict[str, Any],
        clarification_stage: str = "semantic_policy",
    ) -> Dict[str, Any]:
        return {
            "geometry_data": geometry_data,
            "view_analysis": view_analysis,
            "dimension_data": dimension_data,
            "local_relationships": local_relationships,
            "extrude_height": extrude_height,
            "file_path": file_path,
            "reconstruction_context": reconstruction_context,
            "clarification_stage": clarification_stage,
        }

    @staticmethod
    def clarification_stage_for_policy(policy_result: Dict[str, Any]) -> str:
        return SemanticAdjudicationSession.clarification_stage_for_policy_result(
            policy_result
        )
