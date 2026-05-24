#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantic reconstruction pipeline decoupled from drawing-analysis orchestration."""

from typing import Any, Dict, Optional

from .context import ReconstructionContextBuilder
from .clarification_response import ClarificationResponse
from .semantic_adjudicator import LLMSemanticAdjudicator
from .semantic_adjudication_view import SemanticAdjudicationView
from .semantic_policy import SemanticPolicy
from .semantics import PartSemanticGenerator
from .instruction_generator import FreeCADInstructionGenerator
from .modeling_task import ModelingTaskBuilder
from .modeling_path import ModelingPathDecision, default_modeling_path_registry
from .path_clarification import (
    apply_path_clarification_answers,
    build_path_clarification_payload,
    build_path_contract_pending_result,
    needs_path_clarification,
)
from src.utils.stage_confirmation import (
    StageConfirmationStopped,
    StageReview,
    ensure_stage_stop_message,
    request_stage_confirmation,
    resolve_stage_confirmation,
)


class SemanticReconstructionPipeline:
    """Build reconstruction context, part semantics, and executable modeling instructions."""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_builder = ReconstructionContextBuilder()
        self.semantic_policy = SemanticPolicy()
        self.semantic_adjudicator = LLMSemanticAdjudicator(api_key, self.config)
        self.semantic_generator = PartSemanticGenerator(api_key, self.config)
        self.instruction_generator = FreeCADInstructionGenerator(api_key, self.config)
        self.modeling_task_builder = ModelingTaskBuilder()
        self.modeling_path_registry = default_modeling_path_registry()
        self.stage_confirmation = resolve_stage_confirmation(self.config)

    def run(
        self,
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        enriched_geometry = dict(geometry_data)
        if local_relationships:
            enriched_geometry["_local_relationships"] = local_relationships

        reconstruction_context = self.context_builder.build(
            geometry_data=enriched_geometry,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
        )
        policy_result = self.semantic_policy.evaluate(reconstruction_context)
        self._confirm_stage("view_analysis", {
            "view_analysis": view_analysis,
            "dimension_data": dimension_data,
            "semantic_policy": policy_result,
        })
        policy_result, adjudicated_context = self._apply_semantic_adjudication(
            policy_result,
            file_path=file_path,
        )
        summary_context = self.context_builder.build_summary(adjudicated_context)
        if policy_result["clarification_questions"]:
            part_semantics = self._build_pending_semantics(policy_result)
            modeling_result = self._build_pending_modeling_result(policy_result)
            return {
                "reconstruction_context": reconstruction_context,
                "semantic_policy": policy_result,
                "adjudicated_context": adjudicated_context,
                "part_semantics": part_semantics,
                "modeling_instructions": modeling_result,
                "clarification_context": self._build_clarification_context(
                    geometry_data=geometry_data,
                    view_analysis=view_analysis,
                    dimension_data=dimension_data,
                    local_relationships=local_relationships,
                    extrude_height=extrude_height,
                    file_path=file_path,
                    reconstruction_context=reconstruction_context,
                    clarification_stage=self._clarification_stage_for_policy_result(
                        policy_result
                    ),
                ),
            }

        part_semantics = self.semantic_generator.generate(
            adjudicated_context,
            retry_context=summary_context,
            file_path=file_path,
        )
        self._confirm_stage("semantic_reconstruction", {
            "part_semantics": part_semantics,
            "semantic_policy": policy_result,
        })

        feature_detail_questions = self._build_feature_detail_clarification_questions(
            part_semantics,
            policy_result,
        )
        if feature_detail_questions:
            modeling_result = self._build_pending_modeling_result({
                **policy_result,
                "clarification_questions": feature_detail_questions,
            })
            return {
                "reconstruction_context": reconstruction_context,
                "semantic_policy": {
                    **policy_result,
                    "clarification_questions": feature_detail_questions,
                },
                "adjudicated_context": adjudicated_context,
                "part_semantics": part_semantics,
                "modeling_instructions": modeling_result,
                "clarification_context": self._build_clarification_context(
                    geometry_data=geometry_data,
                    view_analysis=view_analysis,
                    dimension_data=dimension_data,
                    local_relationships=local_relationships,
                    extrude_height=extrude_height,
                    file_path=file_path,
                    reconstruction_context=reconstruction_context,
                    clarification_stage=self._clarification_stage_for_policy_result(
                        {
                            **policy_result,
                            "clarification_questions": feature_detail_questions,
                        }
                    ),
                ),
            }

        modeling_path_decision = self._choose_modeling_path(view_analysis, part_semantics)

        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = self._build_blocked_modeling_result(part_semantics)
        elif needs_path_clarification(modeling_path_decision):
            modeling_result = build_path_contract_pending_result(modeling_path_decision)
        else:
            modeling_result = self._build_modeling_result_for_decision(
                modeling_path_decision=modeling_path_decision,
                part_semantics=part_semantics,
                geometry_data=enriched_geometry if local_relationships else geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                extrude_height=extrude_height,
                reconstruction_context=adjudicated_context,
                file_path=file_path,
            )

        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
            "modeling_instructions": modeling_result,
            **self._path_clarification_payload(
                modeling_result=modeling_result,
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
                reconstruction_context=reconstruction_context,
                policy_result=policy_result,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                modeling_path_decision=modeling_path_decision,
            ),
        }

    def continue_with_clarification(
        self,
        clarification_context: Dict[str, Any],
        clarification_answers: Dict[str, Any] | ClarificationResponse,
    ) -> Dict[str, Any]:
        """Continue from adjudication with completed parse, view, and dimension results."""
        clarification_response = ClarificationResponse.from_input(
            clarification_answers,
            source_stage=clarification_context.get("clarification_stage", "semantic_policy"),
        )
        if clarification_context.get("clarification_stage") == "modeling_path":
            return self._continue_with_path_clarification(
                clarification_context,
                clarification_response,
            )

        reconstruction_context = clarification_context["reconstruction_context"]
        policy_result = self.semantic_policy.evaluate(
            reconstruction_context,
            clarification_answers=clarification_response,
        )
        policy_result, adjudicated_context = self._apply_semantic_adjudication(
            policy_result,
            file_path=clarification_context.get("file_path"),
            clarification_response=clarification_response,
        )
        summary_context = self.context_builder.build_summary(adjudicated_context)
        if policy_result["clarification_questions"]:
            part_semantics = self._build_pending_semantics(policy_result)
            modeling_result = self._build_pending_modeling_result(policy_result)
            return {
                "reconstruction_context": reconstruction_context,
                "semantic_policy": policy_result,
                "adjudicated_context": adjudicated_context,
                "part_semantics": part_semantics,
                "modeling_instructions": modeling_result,
                "clarification_context": clarification_context,
            }

        part_semantics = self.semantic_generator.generate(
            adjudicated_context,
            retry_context=summary_context,
            file_path=clarification_context.get("file_path"),
        )
        self._confirm_stage("semantic_reconstruction", {
            "part_semantics": part_semantics,
            "semantic_policy": policy_result,
        })
        feature_detail_questions = self._build_feature_detail_clarification_questions(
            part_semantics,
            policy_result,
        )
        if feature_detail_questions:
            modeling_result = self._build_pending_modeling_result({
                **policy_result,
                "clarification_questions": feature_detail_questions,
            })
            return {
                "reconstruction_context": reconstruction_context,
                "semantic_policy": {
                    **policy_result,
                    "clarification_questions": feature_detail_questions,
                },
                "adjudicated_context": adjudicated_context,
                "part_semantics": part_semantics,
                "modeling_instructions": modeling_result,
                "clarification_context": clarification_context,
            }
        modeling_path_decision = self._choose_modeling_path(
            clarification_context["view_analysis"],
            part_semantics,
        )
        part_semantics, modeling_path_decision, modeling_result = (
            self._build_modeling_result_after_clarification(
                clarification_context=clarification_context,
                clarification_response=clarification_response,
                part_semantics=part_semantics,
                modeling_path_decision=modeling_path_decision,
                reconstruction_context=adjudicated_context,
            )
        )
        return self._build_resumed_result(
            clarification_context=clarification_context,
            reconstruction_context=reconstruction_context,
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
        )

    def _confirm_stage(self, stage: str, payload: Dict[str, Any]) -> None:
        """Let interactive callers review a completed LLM stage before continuing."""
        confirmation = getattr(self, "stage_confirmation", None)
        if confirmation is None:
            confirmation = resolve_stage_confirmation(getattr(self, "config", {}))
            self.stage_confirmation = confirmation
        decision = request_stage_confirmation(
            confirmation,
            StageReview(stage=stage, payload=payload),
        )
        if not decision.continue_processing:
            raise StageConfirmationStopped(ensure_stage_stop_message(decision, stage))

    def _apply_semantic_adjudication(
        self,
        policy_result: Dict[str, Any],
        *,
        file_path: Optional[str],
        clarification_response: Optional[ClarificationResponse] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        adjudicator = getattr(self, "semantic_adjudicator", None)
        adjudicated_context = policy_result["adjudicated_context"]
        if adjudicator is None:
            return policy_result, adjudicated_context
        if (
            clarification_response is not None
            and clarification_response.source_stage == "semantic_adjudication"
        ):
            adjudicated_context = dict(adjudicated_context)
            adjudicated_context["semantic_adjudication_clarification"] = {
                "answers": dict(clarification_response.answers),
                "user_modeling_hint": clarification_response.user_modeling_hint,
                "conflict_policy": clarification_response.conflict_policy,
            }

        semantic_adjudication = adjudicator.adjudicate(
            adjudicated_context,
            file_path=file_path,
        )
        updated_context = dict(adjudicated_context)
        semantic_policy = dict(updated_context.get("semantic_policy", {}) or {})
        semantic_policy["semantic_adjudication"] = semantic_adjudication
        updated_context["semantic_policy"] = semantic_policy

        updated_policy = dict(policy_result)
        updated_policy["semantic_adjudication"] = semantic_adjudication
        updated_policy["adjudicated_context"] = updated_context
        adjudication_view = SemanticAdjudicationView(semantic_adjudication)
        adjudication_questions = adjudication_view.clarification_questions
        if adjudication_view.is_successful:
            adjudication_questions = self._with_question_source(
                adjudication_questions,
                "semantic_adjudication",
            )
            updated_policy["clarification_questions"] = adjudication_questions
        self._confirm_stage("semantic_adjudication", {
            "semantic_adjudication": semantic_adjudication,
            "semantic_policy": updated_policy,
        })
        return updated_policy, updated_context

    @staticmethod
    def _semantic_adjudication_succeeded(semantic_adjudication: Dict[str, Any]) -> bool:
        return SemanticAdjudicationView(semantic_adjudication).is_successful

    @staticmethod
    def _with_question_source(
        questions: list[Dict[str, Any]],
        source_stage: str,
    ) -> list[Dict[str, Any]]:
        tagged = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            updated = dict(question)
            updated.setdefault("source_stage", source_stage)
            tagged.append(updated)
        return tagged

    @staticmethod
    def _clarification_stage_for_policy_result(policy_result: Dict[str, Any]) -> str:
        questions = policy_result.get("clarification_questions", []) or []
        if questions and all(
            isinstance(question, dict)
            and question.get("source_stage") == "semantic_adjudication"
            for question in questions
        ):
            return "semantic_adjudication"
        return "semantic_policy"

    def _is_semantic_confidence_sufficient(self, part_semantics: Dict[str, Any]) -> bool:
        confidence = float(part_semantics.get("confidence") or 0.0)
        threshold = float(self.config.get("semantic_min_confidence", 0.70))
        return confidence >= threshold

    def _modeling_path_registry(self):
        registry = getattr(self, "modeling_path_registry", None)
        if registry is None:
            registry = default_modeling_path_registry()
            self.modeling_path_registry = registry
        return registry

    def _choose_modeling_path(
        self,
        view_analysis: Dict[str, Any],
        part_semantics: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._modeling_path_registry().choose(view_analysis, part_semantics)

    def _build_modeling_result_for_decision(
        self,
        *,
        modeling_path_decision: Dict[str, Any],
        part_semantics: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        extrude_height: float,
        reconstruction_context: Dict[str, Any],
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        routed = self._modeling_path_registry().build_routed_modeling_result(
            modeling_path_decision,
            part_semantics,
        )
        if routed is not None:
            return routed
        builder = getattr(self, "modeling_task_builder", None) or ModelingTaskBuilder()
        modeling_task_payload = builder.build(
            part_semantics=part_semantics,
            reconstruction_context=reconstruction_context,
            modeling_path_decision=modeling_path_decision,
        )
        return self.instruction_generator.generate(
            geometry_data,
            view_analysis,
            dimension_data,
            extrude_height,
            reconstruction_context=reconstruction_context,
            part_semantics=part_semantics,
            modeling_task_payload=modeling_task_payload,
            file_path=file_path,
        )

    def _build_blocked_modeling_result(self, part_semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_summary": part_semantics.get("summary", ""),
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": part_semantics.get("key_dimensions", []),
            "warnings": [
                "Part semantics confidence is insufficient; automatic modeling stopped.",
                *list(part_semantics.get("uncertainties", []) or []),
                *list(part_semantics.get("warnings", []) or []),
            ],
            "blocked_by_semantic_confidence": True,
        }

    def _build_pending_semantics(self, policy_result: Dict[str, Any]) -> Dict[str, Any]:
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

    def _build_pending_modeling_result(self, policy_result: Dict[str, Any]) -> Dict[str, Any]:
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
    def _build_feature_detail_clarification_questions(
        part_semantics: Dict[str, Any],
        policy_result: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        adjudicated_context = policy_result.get("adjudicated_context", {}) or {}
        semantic_policy = adjudicated_context.get("semantic_policy", {}) or {}
        if (
            semantic_policy.get("user_modeling_hint")
            or policy_result.get("user_modeling_hint")
        ):
            return []

        risks = SemanticReconstructionPipeline._critical_modeling_uncertainties(
            part_semantics
        )
        if not risks:
            return []

        return [
            {
                "id": "user_modeling_hint",
                "kind": "text",
                "text": (
                    "语义阶段仍有关键建模信息未裁决。请补充主体厚度/拉伸深度、"
                    "凸台高度/位置，或说明相关圆形特征是否应作为孔/通孔处理。"
                ),
                "reason": "\n".join(risks[:6]),
                "required": True,
                "example": (
                    "例如：这是六角螺母，⌀70 是中心通孔，49 是厚度；"
                    "不存在凸台。"
                ),
            }
        ]

    @staticmethod
    def _critical_modeling_uncertainties(part_semantics: Dict[str, Any]) -> list[str]:
        risk_items = []
        risk_items.extend(part_semantics.get("uncertainties", []) or [])
        risk_items.extend(part_semantics.get("warnings", []) or [])
        planar = part_semantics.get("planar_modeling_semantics") or {}
        risk_items.extend(planar.get("uncertainties", []) or [])

        has_additive = bool(part_semantics.get("additive_features") or [])
        critical = []
        for item in risk_items:
            text = str(item or "").strip()
            if not text:
                continue
            lower = text.lower()
            is_missing = any(
                marker in lower
                for marker in (
                    "missing",
                    "not specified",
                    "not annotated",
                    "not dimensioned",
                    "未标注",
                    "缺失",
                    "缺少",
                    "不明确",
                )
            )
            if not is_missing:
                continue
            mentions_body_depth = any(
                marker in lower
                for marker in (
                    "extrusion depth",
                    "missing depth",
                    "body depth",
                    "thickness",
                    "主体厚度",
                    "拉伸深度",
                    "主体深度",
                    "厚度",
                    "深度",
                )
            )
            mentions_additive_detail = has_additive and any(
                marker in lower
                for marker in (
                    "boss",
                    "additive",
                    "height",
                    "center location",
                    "position",
                    "凸台",
                    "增材",
                    "高度",
                    "位置",
                )
            )
            if mentions_body_depth or mentions_additive_detail:
                critical.append(text)
        return list(dict.fromkeys(critical))

    def _path_clarification_payload(
        self,
        *,
        modeling_result: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
        reconstruction_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        return build_path_clarification_payload(
            modeling_result=modeling_result,
            base_context=self._build_clarification_context(
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
                reconstruction_context=reconstruction_context,
            ),
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
        )

    def _continue_with_path_clarification(
        self,
        clarification_context: Dict[str, Any],
        clarification_answers: Dict[str, Any] | ClarificationResponse,
    ) -> Dict[str, Any]:
        clarification_response = ClarificationResponse.from_input(
            clarification_answers,
            source_stage="modeling_path",
        )
        part_semantics = apply_path_clarification_answers(
            clarification_context["part_semantics"],
            clarification_response,
        )
        modeling_path_decision = self._choose_modeling_path(
            clarification_context["view_analysis"],
            part_semantics,
        )

        part_semantics, modeling_path_decision, modeling_result = (
            self._build_modeling_result_after_clarification(
                clarification_context=clarification_context,
                clarification_response=clarification_response,
                part_semantics=part_semantics,
                modeling_path_decision=modeling_path_decision,
                reconstruction_context=clarification_context["adjudicated_context"],
            )
        )

        return self._build_resumed_result(
            clarification_context=clarification_context,
            reconstruction_context=clarification_context["reconstruction_context"],
            policy_result=clarification_context["semantic_policy"],
            adjudicated_context=clarification_context["adjudicated_context"],
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
        )

    def _build_modeling_result_after_clarification(
        self,
        *,
        clarification_context: Dict[str, Any],
        clarification_response: ClarificationResponse,
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        if not self._is_semantic_confidence_sufficient(part_semantics):
            return (
                part_semantics,
                modeling_path_decision,
                self._build_blocked_modeling_result(part_semantics),
            )

        if needs_path_clarification(modeling_path_decision):
            if not clarification_response.user_modeling_hint:
                return (
                    part_semantics,
                    modeling_path_decision,
                    build_path_contract_pending_result(modeling_path_decision),
                )
            original_decision = modeling_path_decision
            modeling_path_decision = self._build_semantic_recovery_path_decision(
                original_decision
            )
            part_semantics = self._attach_semantic_recovery_context(
                part_semantics,
                original_decision,
            )

        modeling_result = self._build_modeling_result_for_decision(
            modeling_path_decision=modeling_path_decision,
            part_semantics=part_semantics,
            geometry_data=clarification_context["geometry_data"],
            view_analysis=clarification_context["view_analysis"],
            dimension_data=clarification_context["dimension_data"],
            extrude_height=clarification_context["extrude_height"],
            reconstruction_context=reconstruction_context,
            file_path=clarification_context.get("file_path"),
        )
        return part_semantics, modeling_path_decision, modeling_result

    def _build_resumed_result(
        self,
        *,
        clarification_context: Dict[str, Any],
        reconstruction_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        modeling_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
            "modeling_instructions": modeling_result,
            **self._path_clarification_payload(
                modeling_result=modeling_result,
                geometry_data=clarification_context["geometry_data"],
                view_analysis=clarification_context["view_analysis"],
                dimension_data=clarification_context["dimension_data"],
                local_relationships=clarification_context.get("local_relationships"),
                extrude_height=clarification_context["extrude_height"],
                file_path=clarification_context.get("file_path"),
                reconstruction_context=reconstruction_context,
                policy_result=policy_result,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                modeling_path_decision=modeling_path_decision,
            ),
        }

    @staticmethod
    def _build_semantic_recovery_path_decision(
        original_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "modeling_path": "semantic_reconstruction",
            "reason": (
                "专用路径契约仍缺少字段，但用户已提供补充建模提示；"
                "改交由语义重建路径结合图纸上下文继续尝试"
            ),
            "candidate_paths": original_decision.get("candidate_paths", []),
            "fallback_from_path_clarification": True,
            "original_modeling_path_decision": original_decision,
        }

    @staticmethod
    def _attach_semantic_recovery_context(
        part_semantics: Dict[str, Any],
        original_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = ModelingPathDecision.from_mapping(original_decision)

        updated = dict(part_semantics)
        updated["path_clarification_fallback"] = {
            "reason": (
                "专用路径契约仍缺少字段，但用户已提供补充建模提示，"
                "已改交由语义重建路径继续尝试"
            ),
            "missing_fields": decision.missing_contract_fields,
            "clarification_questions": original_decision.get(
                "clarification_questions",
                [],
            ),
            "original_modeling_path": decision.path_requiring_clarification,
        }
        return updated

    def _build_clarification_context(
        self,
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

