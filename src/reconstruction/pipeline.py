#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantic reconstruction pipeline decoupled from drawing-analysis orchestration."""

import logging
from typing import Any, Dict, List, Optional

from .context import ReconstructionContextBuilder
from .clarified_modeling_result import ClarifiedModelingResultBuilder
from .clarification import ClarificationOutlet, PathClarificationAnswerApplier
from .clarification_response import ClarificationResponse
from .semantic_adjudicator import LLMSemanticAdjudicator
from .semantic_adjudication_view import SemanticAdjudicationView
from .semantic_adjudication_session import SemanticAdjudicationSession
from .semantic_policy import SemanticPolicy
from .semantics import PartSemanticGenerator
from .instruction_generator import FreeCADInstructionGenerator
from .modeling_task import ModelingTaskBuilder, ModelingTaskOutlet
from .modeling_path import default_modeling_path_registry
from .clarification import needs_path_clarification
from .reconstruction_result import ReconstructionResultBuilder
from src.utils.deepseek_options import STAGE_MODELING_GENERATION
from src.utils.stage_confirmation import (
    StageConfirmationResult,
    StageConfirmationStopped,
    StageReview,
    ensure_stage_stop_message,
    request_stage_confirmation,
    resolve_stage_confirmation,
)
from src.utils.stage_self_correction import (
    StageSelfCorrectionCase,
    StageSelfCorrectionSession,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


class SemanticReconstructionPipeline:
    """Build reconstruction context, part semantics, and executable modeling instructions."""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_builder = ReconstructionContextBuilder()
        self.semantic_policy = SemanticPolicy()
        self.semantic_adjudicator = LLMSemanticAdjudicator(api_key, self.config)
        self.semantic_adjudication_session = SemanticAdjudicationSession(
            self.semantic_adjudicator,
            self._request_stage_decision,
        )
        self.semantic_generator = PartSemanticGenerator(api_key, self.config)
        self.instruction_generator = FreeCADInstructionGenerator(api_key, self.config)
        self.modeling_task_builder = ModelingTaskBuilder()
        self.modeling_task_outlet = ModelingTaskOutlet(self.modeling_task_builder)
        self.clarification_outlet = ClarificationOutlet()
        self.clarified_modeling_result_builder = ClarifiedModelingResultBuilder(
            clarification_outlet=self.clarification_outlet,
            semantic_min_confidence=float(self.config.get("semantic_min_confidence", 0.70)),
        )
        self.reconstruction_result_builder = ReconstructionResultBuilder(
            self.clarification_outlet
        )
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
        preview_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("语义重建内核开始: file=%s", file_path or "<memory>")
        enriched_geometry = dict(geometry_data)
        if local_relationships:
            enriched_geometry["_local_relationships"] = local_relationships

        logger.info("语义重建步骤1/6: 构建重建上下文")
        reconstruction_context = self.context_builder.build(
            geometry_data=enriched_geometry,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
        )
        logger.info("语义重建步骤2/6: 执行本地语义策略")
        policy_result = self.semantic_policy.evaluate(reconstruction_context)
        self._confirm_stage("view_analysis", {
            "view_analysis": view_analysis,
            "dimension_data": dimension_data,
            "semantic_policy": policy_result,
        })
        logger.info("语义重建步骤3/6: 执行图纸语义裁决")
        policy_result, adjudicated_context = self._apply_semantic_adjudication(
            policy_result,
            file_path=file_path,
            preview_path=preview_path,
        )
        summary_context = self.context_builder.build_summary(adjudicated_context)
        if policy_result["clarification_questions"]:
            return self._clarification_outlet().from_policy_questions(
                policy_result=policy_result,
                reconstruction_context=reconstruction_context,
                adjudicated_context=adjudicated_context,
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
            )

        logger.info("语义重建步骤4/6: 生成零件语义")
        part_semantics = self.semantic_generator.generate(
            adjudicated_context,
            retry_context=summary_context,
            file_path=file_path,
        )
        part_semantics = self._confirm_semantic_reconstruction(
            part_semantics=part_semantics,
            adjudicated_context=adjudicated_context,
            summary_context=summary_context,
            policy_result=policy_result,
            file_path=file_path,
        )

        feature_detail_questions = self._build_feature_detail_clarification_questions(
            part_semantics,
            policy_result,
        )
        if feature_detail_questions:
            return self._clarification_outlet().from_feature_detail_questions(
                policy_result=policy_result,
                feature_detail_questions=feature_detail_questions,
                reconstruction_context=reconstruction_context,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
            )

        logger.info("语义重建步骤5/6: 选择建模路径")
        modeling_path_decision = self._choose_modeling_path(view_analysis, part_semantics)

        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = ClarifiedModelingResultBuilder.build_blocked_modeling_result(
                part_semantics
            )
        elif needs_path_clarification(modeling_path_decision):
            modeling_result = self._clarification_outlet().path_pending_result(
                modeling_path_decision
            )
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
        modeling_result = self._confirm_modeling_generation(
            modeling_result,
            modeling_path_decision,
            file_path=file_path,
        )

        logger.info("语义重建步骤6/6: 装配语义重建结果")
        return self._reconstruction_result_builder().build(
            reconstruction_context=reconstruction_context,
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
            base_clarification_context=self._build_clarification_context(
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
                reconstruction_context=reconstruction_context,
                preview_path=preview_path,
            ),
        )

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
            preview_path=clarification_context.get("preview_path"),
            clarification_response=clarification_response,
        )
        summary_context = self.context_builder.build_summary(adjudicated_context)
        if policy_result["clarification_questions"]:
            return self._clarification_outlet().from_policy_questions(
                policy_result=policy_result,
                reconstruction_context=reconstruction_context,
                adjudicated_context=adjudicated_context,
                geometry_data=clarification_context["geometry_data"],
                view_analysis=clarification_context["view_analysis"],
                dimension_data=clarification_context["dimension_data"],
                local_relationships=clarification_context.get("local_relationships"),
                extrude_height=clarification_context["extrude_height"],
                file_path=clarification_context.get("file_path"),
                clarification_context=clarification_context,
            )

        part_semantics = self.semantic_generator.generate(
            adjudicated_context,
            retry_context=summary_context,
            file_path=clarification_context.get("file_path"),
        )
        part_semantics = self._confirm_semantic_reconstruction(
            part_semantics=part_semantics,
            adjudicated_context=adjudicated_context,
            summary_context=summary_context,
            policy_result=policy_result,
            file_path=clarification_context.get("file_path"),
        )
        feature_detail_questions = self._build_feature_detail_clarification_questions(
            part_semantics,
            policy_result,
        )
        if feature_detail_questions:
            return self._clarification_outlet().from_feature_detail_questions(
                policy_result=policy_result,
                feature_detail_questions=feature_detail_questions,
                reconstruction_context=reconstruction_context,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                geometry_data=clarification_context["geometry_data"],
                view_analysis=clarification_context["view_analysis"],
                dimension_data=clarification_context["dimension_data"],
                local_relationships=clarification_context.get("local_relationships"),
                extrude_height=clarification_context["extrude_height"],
                file_path=clarification_context.get("file_path"),
                clarification_context=clarification_context,
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
                reconstruction_context=adjudicated_context,
            )
        )
        modeling_result = self._confirm_modeling_generation(
            modeling_result,
            modeling_path_decision,
            file_path=clarification_context.get("file_path"),
        )
        return self._reconstruction_result_builder().build(
            reconstruction_context=reconstruction_context,
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
            base_clarification_context=self._build_clarification_context(
                geometry_data=clarification_context["geometry_data"],
                view_analysis=clarification_context["view_analysis"],
                dimension_data=clarification_context["dimension_data"],
                local_relationships=clarification_context.get("local_relationships"),
                extrude_height=clarification_context["extrude_height"],
                file_path=clarification_context.get("file_path"),
                reconstruction_context=reconstruction_context,
                preview_path=clarification_context.get("preview_path"),
            ),
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

    def _confirm_modeling_generation(
        self,
        modeling_result: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._should_confirm_modeling_generation(modeling_result):
            return modeling_result
        decision = self._request_stage_decision("modeling_generation", {
            "modeling_instructions": modeling_result,
            "modeling_path_decision": modeling_path_decision,
        })
        if decision.continue_processing:
            return modeling_result
        if getattr(decision, "requests_self_correction", False):
            corrected = self._self_correct_modeling_generation(modeling_result, file_path)
            self._confirm_stage("modeling_generation", {
                "modeling_instructions": corrected,
                "modeling_path_decision": modeling_path_decision,
            })
            return corrected
        if getattr(decision, "requests_retry", False):
            retried = self._retry_modeling_generation(modeling_result, file_path)
            self._confirm_stage("modeling_generation", {
                "modeling_instructions": retried,
                "modeling_path_decision": modeling_path_decision,
            })
            return retried
        if getattr(decision, "requests_retry_with_partial", False):
            retained = getattr(decision, "retained_items", {})
            retried = self._retry_modeling_generation(
                modeling_result, file_path, retained_items=retained,
            )
            self._confirm_stage("modeling_generation", {
                "modeling_instructions": retried,
                "modeling_path_decision": modeling_path_decision,
            })
            return retried
        raise StageConfirmationStopped(
            ensure_stage_stop_message(decision, "modeling_generation")
        )

    def _confirm_semantic_reconstruction(
        self,
        *,
        part_semantics: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        summary_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        part_semantics = self._auto_self_correct_semantic_reconstruction(
            part_semantics=part_semantics,
            summary_context=summary_context,
            file_path=file_path,
        )
        decision = self._request_stage_decision("semantic_reconstruction", {
            "part_semantics": part_semantics,
            "semantic_policy": policy_result,
        })
        if decision.continue_processing:
            return part_semantics
        if getattr(decision, "requests_retry", False):
            primary_context = self._build_semantic_retry_context(
                summary_context=adjudicated_context,
                part_semantics=part_semantics,
                policy_result=policy_result,
                retained_items={},
                trigger="user_requested_retry_stage",
            )
            compact_context = self._build_semantic_retry_context(
                summary_context=summary_context,
                part_semantics=part_semantics,
                policy_result=policy_result,
                retained_items={},
                trigger="user_requested_retry_stage",
            )
            retried = self.semantic_generator.generate(
                primary_context,
                retry_context=compact_context,
                file_path=file_path,
            )
            if isinstance(retried, dict):
                retried.setdefault("stage_retry_applied", True)
                retried.setdefault("stage_retry_log", [{
                    "stage": "semantic_reconstruction",
                    "trigger": "user_requested_retry_stage",
                    "result": "用户触发后已重跑零件语义重建阶段",
                }])
                part_semantics = retried
            self._confirm_stage("semantic_reconstruction", {
                "part_semantics": part_semantics,
                "semantic_policy": policy_result,
            })
            return part_semantics
        if getattr(decision, "requests_retry_with_partial", False):
            retained = getattr(decision, "retained_items", {})
            primary_context = self._build_semantic_retry_context(
                summary_context=adjudicated_context,
                part_semantics=part_semantics,
                policy_result=policy_result,
                retained_items=retained,
                trigger="user_requested_retry_with_partial",
            )
            compact_context = self._build_semantic_retry_context(
                summary_context=summary_context,
                part_semantics=part_semantics,
                policy_result=policy_result,
                retained_items=retained,
                trigger="user_requested_retry_with_partial",
            )
            retried = self.semantic_generator.generate(
                primary_context,
                retry_context=compact_context,
                file_path=file_path,
            )
            if isinstance(retried, dict):
                retried.setdefault("stage_retry_applied", True)
                retried.setdefault("stage_retry_log", [{
                    "stage": "semantic_reconstruction",
                    "trigger": "user_requested_retry_with_partial",
                    "result": "用户触发后已带部分成果重跑零件语义重建阶段",
                    "retained_items": retained,
                }])
                part_semantics = retried
            self._confirm_stage("semantic_reconstruction", {
                "part_semantics": part_semantics,
                "semantic_policy": policy_result,
            })
            return part_semantics
        raise StageConfirmationStopped(
            ensure_stage_stop_message(decision, "semantic_reconstruction")
        )

    @classmethod
    def _build_semantic_retry_context(
        cls,
        *,
        summary_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        policy_result: Dict[str, Any],
        retained_items: Dict[str, Any],
        trigger: str,
    ) -> Dict[str, Any]:
        """为语义重跑补充明确目标，避免模型只重复上一轮结论。"""
        retry_context = dict(summary_context)
        retained_items = retained_items or {}
        if retained_items:
            retry_context["retained_items"] = retained_items

        focus_issues = cls._semantic_retry_focus_issues(part_semantics, policy_result)
        retry_context["stage_retry_directives"] = {
            "stage": "semantic_reconstruction",
            "trigger": trigger,
            "objective": (
                "本次重跑必须优先核查并改写未决风险，不是复述上一轮零件语义；"
                "已保留项目只能作为硬约束，未保留或仍有风险的项目必须重新判定。"
            ),
            "focus_issues": focus_issues,
            "required_output_behavior": [
                "逐项处理 focus_issues；能根据图纸证据解决的，写入对应特征或关键尺寸。",
                "仍无法解决的，必须保留为 uncertainties，并说明缺少哪类证据。",
                "不得把同心外轮廓圆和内孔圆同时解释为两个通孔；外径只作为主体轮廓证据。",
            ],
        }
        return retry_context

    @classmethod
    def _semantic_retry_focus_issues(
        cls,
        part_semantics: Dict[str, Any],
        policy_result: Dict[str, Any],
    ) -> List[str]:
        issues: List[str] = []
        issues.extend(cls._string_list(part_semantics.get("uncertainties")))
        issues.extend(cls._string_list(part_semantics.get("warnings")))

        planar = part_semantics.get("planar_modeling_semantics")
        if isinstance(planar, dict):
            issues.extend(cls._string_list(planar.get("uncertainties")))
        revolve = part_semantics.get("revolve_modeling_semantics")
        if isinstance(revolve, dict):
            issues.extend(cls._string_list(revolve.get("uncertainties")))

        issues.extend(cls._question_issue_lines(policy_result.get("clarification_questions")))
        issues.extend(cls._string_list(policy_result.get("uncertainties")))
        issues.extend(cls._string_list(policy_result.get("warnings")))

        adjudication = policy_result.get("semantic_adjudication")
        if isinstance(adjudication, dict):
            issues.extend(cls._question_issue_lines(adjudication.get("clarification_questions")))
            issues.extend(cls._string_list(adjudication.get("uncertainties")))
            issues.extend(cls._string_list(adjudication.get("warnings")))
            issues.extend(cls._question_issue_lines(adjudication.get("risks")))

        return cls._dedupe_text(issues)[:12]

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def _question_issue_lines(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        lines: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            parts = [
                item.get("id") or item.get("dimension_id") or item.get("feature_id"),
                item.get("question") or item.get("text") or item.get("message"),
                item.get("reason"),
            ]
            line = "；".join(str(part).strip() for part in parts if str(part).strip())
            if line:
                lines.append(line)
        return lines

    @staticmethod
    def _dedupe_text(values: List[str]) -> List[str]:
        seen = set()
        deduped = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _auto_self_correct_semantic_reconstruction(
        self,
        *,
        part_semantics: Dict[str, Any],
        summary_context: Dict[str, Any],
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        from .semantic_schema import PartSemanticsValidator

        validator = PartSemanticsValidator()
        valid, errors = validator.validate(part_semantics)
        if valid:
            return part_semantics

        logger.warning(
            "零件语义校验失败，自动触发模型自纠: %s",
            "; ".join(errors[:3]),
        )
        max_rounds = 2
        for round_index in range(1, max_rounds + 1):
            corrected = self._self_correct_semantic_reconstruction(
                part_semantics=part_semantics,
                summary_context=summary_context,
                file_path=file_path,
                round_index=round_index,
                max_rounds=max_rounds,
                validation_errors=errors,
            )
            valid, errors = validator.validate(corrected)
            if valid:
                logger.info(
                    "零件语义自动自纠第 %s 轮成功",
                    round_index,
                )
                return corrected
            logger.warning(
                "零件语义自动自纠第 %s 轮后仍校验失败: %s",
                round_index,
                "; ".join(errors[:3]),
            )
            part_semantics = corrected

        part_semantics.setdefault("self_correction_applied", True)
        logger.warning(
            "零件语义自动自纠 %s 轮后仍未通过校验，进入阶段确认",
            max_rounds,
        )
        return part_semantics

    def _self_correct_semantic_reconstruction(
        self,
        *,
        part_semantics: Dict[str, Any],
        summary_context: Dict[str, Any],
        file_path: Optional[str],
        round_index: int = 1,
        max_rounds: int = 2,
        validation_errors: Optional[list] = None,
    ) -> Dict[str, Any]:
        generator = getattr(self.semantic_generator, "generate_from_self_correction", None)
        if not callable(generator):
            logger.warning("零件语义生成器不支持模型自纠，跳过自动自纠")
            return part_semantics
        is_auto = validation_errors is not None
        issues = _build_semantic_validation_issues(validation_errors) if is_auto else [
            ValidationIssue(
                code="user_requested_semantic_reconstruction_self_correction",
                message="用户在零件语义重建阶段要求模型自纠",
                severity="warning",
                fixable=True,
                impact="用户认为当前零件类型、特征或关键尺寸语义可能需要复核",
                correction_target="重新检查零件类型、主体/增材/减材特征、关键尺寸和不确定项",
                details=_semantic_reconstruction_issue_details(part_semantics),
            )
        ]
        trigger = "auto_self_correction" if is_auto else "user_requested_semantic_reconstruction_self_correction"
        log_result = f"自动自纠第{round_index}轮完成" if is_auto else "用户触发后已重新生成零件语义"
        case = StageSelfCorrectionCase(
            stage="semantic_reconstruction",
            stage_payload=summary_context,
            previous_output={
                "part_type": part_semantics.get("part_type"),
                "confidence": part_semantics.get("confidence"),
                "summary": part_semantics.get("summary", ""),
                "evidence": part_semantics.get("evidence", []),
                "candidate_interpretations": part_semantics.get("candidate_interpretations", []),
                "coordinate_system": part_semantics.get("coordinate_system"),
                "dimension_source": part_semantics.get("dimension_source"),
                "base_features": part_semantics.get("base_features", []),
                "additive_features": part_semantics.get("additive_features", []),
                "subtractive_features": part_semantics.get("subtractive_features", []),
                "planar_modeling_semantics": part_semantics.get("planar_modeling_semantics"),
                "revolve_modeling_semantics": part_semantics.get("revolve_modeling_semantics"),
                "preferred_modeling_path": part_semantics.get("preferred_modeling_path"),
                "key_dimensions": part_semantics.get("key_dimensions", []),
                "uncertainties": part_semantics.get("uncertainties", []),
                "warnings": part_semantics.get("warnings", []),
            },
            validation_issues=issues,
            output_contract={
                "required_fields": [
                    "part_type",
                    "confidence",
                    "summary",
                    "coordinate_system",
                    "dimension_source",
                    "base_features",
                    "additive_features",
                    "subtractive_features",
                    "planar_modeling_semantics",
                    "revolve_modeling_semantics",
                    "preferred_modeling_path",
                    "key_dimensions",
                    "uncertainties",
                    "warnings",
                ],
                "dimension_policy": "不得把未裁决尺寸或候选尺寸提升为 key_dimensions",
            },
            generate=generator,
            correction_goal=_semantic_reconstruction_correction_goal(part_semantics),
            evidence_refs=[{
                "id": "auto_validation",
                "kind": "validator",
                "summary": f"自动校验失败: {'; '.join(str(e) for e in (validation_errors or [])[:3])}",
            }] if is_auto else [],
            round_index=round_index,
            max_rounds=max_rounds,
            log_trigger=trigger,
            log_result=log_result,
        )
        result = StageSelfCorrectionSession().self_correct(case, file_path=file_path)
        if result.corrected_output is not None:
            return result.corrected_output
        return part_semantics

    def _request_stage_decision(self, stage: str, payload: Dict[str, Any]):
        confirmation = getattr(self, "stage_confirmation", None)
        if confirmation is None:
            confirmation = resolve_stage_confirmation(getattr(self, "config", {}))
            self.stage_confirmation = confirmation
        return request_stage_confirmation(
            confirmation,
            StageReview(stage=stage, payload=payload),
        )

    def _self_correct_modeling_generation(
        self,
        modeling_result: Dict[str, Any],
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        generator = getattr(self, "instruction_generator", None)
        if generator is None or not hasattr(generator, "generate_from_self_correction"):
            raise StageConfirmationStopped(
                StageConfirmationResult.self_correct(
                    "建模指令生成器不支持模型自纠",
                    stage="modeling_generation",
                )
            )
        case = StageSelfCorrectionCase(
            stage=STAGE_MODELING_GENERATION,
            stage_payload=modeling_result.get("_modeling_task_payload") or {},
            previous_output={
                "analysis_summary": modeling_result.get("analysis_summary", ""),
                "modeling_strategy": modeling_result.get("modeling_strategy", ""),
                "freecad_script": modeling_result.get("freecad_script", ""),
                "instructions": list(modeling_result.get("instructions") or []),
                "key_dimensions": list(modeling_result.get("key_dimensions") or []),
                "completed_features": list(modeling_result.get("completed_features") or []),
                "skipped_features": list(modeling_result.get("skipped_features") or []),
                "partial_completion_reason": modeling_result.get("partial_completion_reason", ""),
                "warnings": list(modeling_result.get("warnings") or []),
            },
            validation_issues=[
                ValidationIssue(
                    code="user_requested_modeling_self_correction",
                    message="用户在建模指令生成阶段要求模型自纠",
                    severity="warning",
                    fixable=True,
                    impact="用户认为当前建模指令可能需要复核",
                    correction_target="重新检查建模任务载荷、风险和脚本合同，输出更可靠的建模指令",
                    details=_modeling_generation_issue_details(modeling_result),
                )
            ],
            output_contract={
                "required_fields": [
                    "analysis_summary",
                    "modeling_strategy",
                    "freecad_script",
                    "instructions",
                    "key_dimensions",
                    "completed_features",
                    "skipped_features",
                    "partial_completion_reason",
                    "warnings",
                ],
                "freecad_script_contract": [
                    "必须赋值 final_shape",
                    '必须执行 Part.show(final_shape, "GeneratedModel")',
                    "必须执行 doc.recompute()",
                ],
            },
            generate=generator.generate_from_self_correction,
            correction_goal=_modeling_generation_correction_goal(modeling_result),
            log_trigger="user_requested_modeling_self_correction",
            log_result="用户触发后已重新生成建模指令",
        )
        result = StageSelfCorrectionSession().self_correct(case, file_path=file_path)
        corrected = result.corrected_output
        if isinstance(corrected, dict):
            if modeling_result.get("_modeling_task_payload") and not corrected.get("_modeling_task_payload"):
                corrected["_modeling_task_payload"] = modeling_result["_modeling_task_payload"]
            return corrected
        return modeling_result

    def _retry_modeling_generation(
        self,
        modeling_result: Dict[str, Any],
        file_path: Optional[str],
        *,
        retained_items: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = modeling_result.get("_modeling_task_payload") or {}
        generator = getattr(self, "instruction_generator", None)
        if generator is None or not hasattr(generator, "generate"):
            raise StageConfirmationStopped(
                StageConfirmationResult.retry_stage(
                    "建模指令生成器不支持重跑当前阶段",
                    stage="modeling_generation",
                )
            )
        if not payload:
            raise StageConfirmationStopped(
                StageConfirmationResult.retry_stage(
                    "缺少建模任务载荷，无法重跑建模指令生成阶段",
                    stage="modeling_generation",
                )
            )
        generate_kwargs: Dict[str, Any] = {
            "geometry_data": {},
            "view_analysis": {},
            "dimension_data": {},
            "extrude_height": 0.0,
            "modeling_task_payload": payload,
            "file_path": file_path,
        }
        if retained_items:
            payload = dict(payload)
            payload["retained_items"] = retained_items
            generate_kwargs["modeling_task_payload"] = payload
        retried = generator.generate(**generate_kwargs)
        if isinstance(retried, dict):
            retried.setdefault("_modeling_task_payload", payload)
            retried.setdefault("stage_retry_applied", True)
            trigger = "user_requested_retry_with_partial" if retained_items else "user_requested_retry_stage"
            result_text = "用户触发后已带部分成果重跑建模指令生成阶段" if retained_items else "用户触发后已重跑建模指令生成阶段"
            retried.setdefault("stage_retry_log", [{
                "stage": STAGE_MODELING_GENERATION,
                "trigger": trigger,
                "result": result_text,
                "retained_items": retained_items,
            }])
            return retried
        return modeling_result

    @staticmethod
    def _should_confirm_modeling_generation(modeling_result: Dict[str, Any]) -> bool:
        if not isinstance(modeling_result, dict):
            return False
        if modeling_result.get("clarification_questions"):
            return False
        if modeling_result.get("blocked_by_clarification"):
            return False
        if modeling_result.get("blocked_by_path_contract"):
            return False
        if modeling_result.get("routed_to_planar_extrude"):
            return False
        if modeling_result.get("routed_to_revolve"):
            return False
        return "freecad_script" in modeling_result or bool(
            modeling_result.get("blocked_by_task_readiness")
        )

    def _apply_semantic_adjudication(
        self,
        policy_result: Dict[str, Any],
        *,
        file_path: Optional[str],
        preview_path: Optional[str] = None,
        clarification_response: Optional[ClarificationResponse] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        session = getattr(self, "semantic_adjudication_session", None)
        if session is None:
            session = SemanticAdjudicationSession(
                getattr(self, "semantic_adjudicator", None),
                self._request_stage_decision,
            )
            self.semantic_adjudication_session = session
        return session.apply(
            policy_result,
            file_path=file_path,
            preview_path=preview_path,
            clarification_response=clarification_response,
        )

    @staticmethod
    def _semantic_adjudication_succeeded(semantic_adjudication: Dict[str, Any]) -> bool:
        return SemanticAdjudicationView(semantic_adjudication).is_successful

    @staticmethod
    def _with_question_source(
        questions: list[Dict[str, Any]],
        source_stage: str,
    ) -> list[Dict[str, Any]]:
        return SemanticAdjudicationSession.with_question_source(questions, source_stage)

    @staticmethod
    def _clarification_stage_for_policy_result(policy_result: Dict[str, Any]) -> str:
        return SemanticAdjudicationSession.clarification_stage_for_policy_result(
            policy_result
        )

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

    def _clarification_outlet(self) -> ClarificationOutlet:
        outlet = getattr(self, "clarification_outlet", None)
        if outlet is None:
            outlet = ClarificationOutlet()
            self.clarification_outlet = outlet
        return outlet

    def _clarified_modeling_result_builder(self) -> ClarifiedModelingResultBuilder:
        builder = getattr(self, "clarified_modeling_result_builder", None)
        if builder is None:
            builder = ClarifiedModelingResultBuilder(
                clarification_outlet=self._clarification_outlet(),
                semantic_min_confidence=float(
                    getattr(self, "config", {}).get("semantic_min_confidence", 0.70)
                ),
            )
            self.clarified_modeling_result_builder = builder
        return builder

    def _reconstruction_result_builder(self) -> ReconstructionResultBuilder:
        builder = getattr(self, "reconstruction_result_builder", None)
        if builder is None:
            builder = ReconstructionResultBuilder(self._clarification_outlet())
            self.reconstruction_result_builder = builder
        return builder

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
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        routed = self._modeling_path_registry().build_routed_modeling_result(
            modeling_path_decision,
            part_semantics,
        )
        if routed is not None:
            return routed
        outlet = getattr(self, "modeling_task_outlet", None)
        if outlet is None:
            outlet = ModelingTaskOutlet(
                getattr(self, "modeling_task_builder", None) or ModelingTaskBuilder()
            )
            self.modeling_task_outlet = outlet
        return outlet.generate_instructions(
            instruction_generator=self.instruction_generator,
            modeling_path_decision=modeling_path_decision,
            part_semantics=part_semantics,
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            extrude_height=extrude_height,
            adjudicated_context=reconstruction_context,
            file_path=file_path,
            recovery_context=recovery_context,
        )

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

    def _continue_with_path_clarification(
        self,
        clarification_context: Dict[str, Any],
        clarification_answers: Dict[str, Any] | ClarificationResponse,
    ) -> Dict[str, Any]:
        clarification_response = ClarificationResponse.from_input(
            clarification_answers,
            source_stage="modeling_path",
        )
        part_semantics = PathClarificationAnswerApplier().apply(
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

        return self._reconstruction_result_builder().build(
            reconstruction_context=clarification_context["reconstruction_context"],
            policy_result=clarification_context["semantic_policy"],
            adjudicated_context=clarification_context["adjudicated_context"],
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
            base_clarification_context=self._build_clarification_context(
                geometry_data=clarification_context["geometry_data"],
                view_analysis=clarification_context["view_analysis"],
                dimension_data=clarification_context["dimension_data"],
                local_relationships=clarification_context.get("local_relationships"),
                extrude_height=clarification_context["extrude_height"],
                file_path=clarification_context.get("file_path"),
                reconstruction_context=clarification_context["reconstruction_context"],
            ),
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
        return self._clarified_modeling_result_builder().build(
            clarification_response=clarification_response,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            build_modeling_result=lambda resolved_semantics, resolved_decision: (
                self._build_modeling_result_for_decision(
                    modeling_path_decision=resolved_decision,
                    part_semantics=resolved_semantics,
                    geometry_data=clarification_context["geometry_data"],
                    view_analysis=clarification_context["view_analysis"],
                    dimension_data=clarification_context["dimension_data"],
                    extrude_height=clarification_context["extrude_height"],
                    reconstruction_context=reconstruction_context,
                    file_path=clarification_context.get("file_path"),
                    recovery_context=clarification_context,
                )
            ),
        )

    def rerun_semantic_reconstruction_from_cached_analysis(
        self,
        *,
        analysis_result: Dict[str, Any],
        geometry_data: Dict[str, Any],
        extrude_height: float,
        file_path: Optional[str] = None,
        preview_path: Optional[str] = None,
        retained_items: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """缓存命中后执行零件语义阶段重跑，并继续后续建模阶段。"""
        policy_result = analysis_result.get("semantic_policy", {}) or {}
        adjudicated_context = analysis_result.get("adjudicated_context", {}) or {}
        reconstruction_context = analysis_result.get("reconstruction_context", {}) or {}
        view_analysis = analysis_result.get("view_analysis", {}) or {}
        dimension_data = analysis_result.get("dimension_extraction", {}) or {}
        local_relationships = analysis_result.get("local_relationships")

        retained_items = retained_items or {}
        primary_context = self._build_semantic_retry_context(
            summary_context=adjudicated_context,
            part_semantics=analysis_result.get("part_semantics", {}) or {},
            policy_result=policy_result,
            retained_items=retained_items,
            trigger=(
                "user_requested_retry_with_partial"
                if retained_items
                else "user_requested_retry_stage"
            ),
        )
        compact_context = self._build_semantic_retry_context(
            summary_context=self.context_builder.build_summary(adjudicated_context),
            part_semantics=analysis_result.get("part_semantics", {}) or {},
            policy_result=policy_result,
            retained_items=retained_items,
            trigger=(
                "user_requested_retry_with_partial"
                if retained_items
                else "user_requested_retry_stage"
            ),
        )

        logger.info("缓存阶段确认触发零件语义重跑: retained_items=%s", bool(retained_items))
        part_semantics = self.semantic_generator.generate(
            primary_context,
            retry_context=compact_context,
            file_path=file_path,
        )
        if isinstance(part_semantics, dict):
            part_semantics.setdefault("stage_retry_applied", True)
            part_semantics.setdefault("stage_retry_log", [{
                "stage": "semantic_reconstruction",
                "trigger": (
                    "user_requested_retry_with_partial"
                    if retained_items
                    else "user_requested_retry_stage"
                ),
                "result": (
                    "用户触发后已带部分成果重跑零件语义重建阶段"
                    if retained_items
                    else "用户触发后已重跑零件语义重建阶段"
                ),
                "retained_items": retained_items,
            }])

        return self._finish_after_part_semantics(
            reconstruction_context=reconstruction_context,
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
            extrude_height=extrude_height,
            file_path=file_path,
        )

    def rerun_modeling_generation_from_cached_analysis(
        self,
        *,
        analysis_result: Dict[str, Any],
        file_path: Optional[str] = None,
        retained_items: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """缓存命中后执行建模指令阶段重跑。"""
        modeling_result = analysis_result.get("modeling_instructions", {}) or {}
        modeling_path_decision = analysis_result.get("modeling_path_decision", {}) or {}
        retried = self._retry_modeling_generation(
            modeling_result,
            file_path,
            retained_items=retained_items or None,
        )
        updated = dict(analysis_result)
        updated["modeling_instructions"] = self._confirm_modeling_generation(
            retried,
            modeling_path_decision,
            file_path=file_path,
        )
        return updated

    def _finish_after_part_semantics(
        self,
        *,
        reconstruction_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        geometry_data: Dict[str, Any],
        view_analysis: Dict[str, Any],
        dimension_data: Dict[str, Any],
        local_relationships: Optional[Dict[str, Any]],
        extrude_height: float,
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        """从已确定的零件语义继续完成路径选择、建模指令和结果装配。"""
        feature_detail_questions = self._build_feature_detail_clarification_questions(
            part_semantics,
            policy_result,
        )
        if feature_detail_questions:
            return self._clarification_outlet().from_feature_detail_questions(
                policy_result=policy_result,
                feature_detail_questions=feature_detail_questions,
                reconstruction_context=reconstruction_context,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
            )

        modeling_path_decision = self._choose_modeling_path(view_analysis, part_semantics)
        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = ClarifiedModelingResultBuilder.build_blocked_modeling_result(
                part_semantics
            )
        elif needs_path_clarification(modeling_path_decision):
            modeling_result = self._clarification_outlet().path_pending_result(
                modeling_path_decision
            )
        else:
            enriched_geometry = dict(geometry_data)
            if local_relationships:
                enriched_geometry["_local_relationships"] = local_relationships
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
        modeling_result = self._confirm_modeling_generation(
            modeling_result,
            modeling_path_decision,
            file_path=file_path,
        )
        return self._reconstruction_result_builder().build(
            reconstruction_context=reconstruction_context,
            policy_result=policy_result,
            adjudicated_context=adjudicated_context,
            part_semantics=part_semantics,
            modeling_path_decision=modeling_path_decision,
            modeling_result=modeling_result,
            base_clarification_context=self._build_clarification_context(
                geometry_data=geometry_data,
                view_analysis=view_analysis,
                dimension_data=dimension_data,
                local_relationships=local_relationships,
                extrude_height=extrude_height,
                file_path=file_path,
                reconstruction_context=reconstruction_context,
            ),
        )

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
        preview_path: Optional[str] = None,
        clarification_stage: str = "semantic_policy",
    ) -> Dict[str, Any]:
        context = ClarificationOutlet.build_context(
            geometry_data=geometry_data,
            view_analysis=view_analysis,
            dimension_data=dimension_data,
            local_relationships=local_relationships,
            extrude_height=extrude_height,
            file_path=file_path,
            reconstruction_context=reconstruction_context,
            clarification_stage=clarification_stage,
        )
        if preview_path:
            context["preview_path"] = preview_path
        return context


def _semantic_reconstruction_correction_goal(part_semantics: Dict[str, Any]) -> str:
    parts = ["用户要求复核并重新生成零件语义"]
    part_type = part_semantics.get("part_type", "")
    confidence = part_semantics.get("confidence")
    uncertainties = part_semantics.get("uncertainties") or []
    warnings = part_semantics.get("warnings") or []
    if part_type:
        parts.append(f"当前零件类型为「{part_type}」")
    if confidence is not None:
        parts.append(f"置信度 {confidence}")
    if uncertainties:
        parts.append(f"存在 {len(uncertainties)} 项不确定事项")
    if warnings:
        parts.append(f"存在 {len(warnings)} 项风险提示")
    parts.append("不得新增未裁决尺寸或图纸事实")
    return "；".join(parts)


def _semantic_reconstruction_issue_details(part_semantics: Dict[str, Any]) -> Dict[str, Any]:
    details: Dict[str, Any] = {}
    uncertainties = part_semantics.get("uncertainties") or []
    warnings = part_semantics.get("warnings") or []
    planar = part_semantics.get("planar_modeling_semantics") or {}
    revolve = part_semantics.get("revolve_modeling_semantics")
    if uncertainties:
        details["uncertainties"] = uncertainties[:8]
    if warnings:
        details["warnings"] = warnings[:8]
    if planar:
        planar_uncertainties = planar.get("uncertainties") or []
        if planar_uncertainties:
            details["planar_uncertainties"] = planar_uncertainties[:5]
    if revolve:
        revolve_uncertainties = revolve.get("uncertainties") or []
        if revolve_uncertainties:
            details["revolve_uncertainties"] = revolve_uncertainties[:5]
    return details


def _modeling_generation_correction_goal(modeling_result: Dict[str, Any]) -> str:
    from src.reconstruction.analysis_result import ModelingInstructionsResult
    typed = ModelingInstructionsResult.from_dict(modeling_result)
    parts = ["用户要求复核并重新生成建模指令"]
    if typed.is_blocked:
        parts.append(f"建模被阻断：{typed.blocked_reason}")
    if typed.is_partial:
        if typed.skipped_features:
            names = [f.get("name", f.get("kind", "?")) for f in typed.skipped_features[:5]]
            parts.append(f"跳过特征：{', '.join(names)}")
        if typed.partial_completion_reason:
            parts.append(f"部分完成原因：{typed.partial_completion_reason}")
    if typed.has_script:
        parts.append("当前脚本需要修正")
    else:
        parts.append("当前无脚本输出")
    parts.append("不得新增未裁决尺寸或图纸事实")
    return "；".join(parts)


def _modeling_generation_issue_details(modeling_result: Dict[str, Any]) -> Dict[str, Any]:
    from src.reconstruction.analysis_result import ModelingInstructionsResult
    typed = ModelingInstructionsResult.from_dict(modeling_result)
    details: Dict[str, Any] = {}
    if typed.skipped_features:
        details["skipped_features"] = typed.skipped_features[:8]
    if typed.partial_completion_reason:
        details["partial_completion_reason"] = typed.partial_completion_reason
    if typed.warnings:
        details["warnings"] = typed.warnings[:8]
    if typed.has_script:
        details["script_length"] = len(typed.freecad_script)
    return details


def _build_semantic_validation_issues(errors: list) -> List[ValidationIssue]:
    if not errors:
        return [ValidationIssue(
            code="semantic_validation_unknown",
            message="零件语义校验失败",
            severity="error",
            fixable=True,
            impact="零件语义结构不满足输出合同",
            correction_target="重新生成满足 schema 和尺寸权限的零件语义",
        )]
    issues = []
    for index, error in enumerate(errors[:6], start=1):
        text = str(error).strip()
        if not text:
            continue
        issues.append(ValidationIssue(
            code=f"semantic_validation_{index}",
            message=text,
            severity="error",
            fixable=True,
            impact="零件语义结构不满足输出合同",
            correction_target="修复校验失败的字段并重新生成",
            details={"original_error": text},
        ))
    return issues
