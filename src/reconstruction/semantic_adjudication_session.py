#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义裁决会话状态转换。"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional

from .clarification_response import ClarificationResponse
from .semantic_adjudication_view import SemanticAdjudicationView
from src.utils.stage_self_correction import (
    StageSelfCorrectionCase,
    StageSelfCorrectionSession,
    ValidationIssue,
)
from src.utils.stage_confirmation import (
    StageConfirmationResult,
    StageConfirmationStopped,
    ensure_stage_stop_message,
)


SEMANTIC_ADJUDICATION_STAGE = "semantic_adjudication"
SEMANTIC_POLICY_STAGE = "semantic_policy"


class SemanticAdjudicationSession:
    """执行 LLM 语义裁决并保持澄清状态局部化。"""

    def __init__(
        self,
        adjudicator: Any = None,
        confirm_stage: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.adjudicator = adjudicator
        self.confirm_stage = confirm_stage

    def apply(
        self,
        policy_result: Dict[str, Any],
        *,
        file_path: Optional[str],
        preview_path: Optional[str] = None,
        clarification_response: Optional[ClarificationResponse] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        adjudicated_context = policy_result["adjudicated_context"]
        if self.adjudicator is None:
            return policy_result, adjudicated_context

        if (
            clarification_response is not None
            and clarification_response.source_stage == SEMANTIC_ADJUDICATION_STAGE
        ):
            adjudicated_context = dict(adjudicated_context)
            adjudicated_context["semantic_adjudication_clarification"] = {
                "answers": dict(clarification_response.answers),
                "user_modeling_hint": clarification_response.user_modeling_hint,
                "conflict_policy": clarification_response.conflict_policy,
            }

        semantic_adjudication = self._call_adjudicator(
            adjudicated_context,
            file_path=file_path,
            preview_path=preview_path,
        )
        updated_policy, updated_context = self._build_updated_policy(
            policy_result,
            adjudicated_context,
            semantic_adjudication,
        )

        decision = self._confirm_adjudication(semantic_adjudication, updated_policy)
        if getattr(decision, "requests_retry", False):
            semantic_adjudication = self._call_adjudicator(
                adjudicated_context,
                file_path=file_path,
                preview_path=preview_path,
            )
            semantic_adjudication = dict(semantic_adjudication)
            semantic_adjudication.setdefault("stage_retry_applied", True)
            semantic_adjudication.setdefault("stage_retry_log", [{
                "stage": SEMANTIC_ADJUDICATION_STAGE,
                "trigger": "user_requested_retry_stage",
                "result": "用户触发后已重跑图纸语义裁决阶段",
            }])
            updated_policy, updated_context = self._build_updated_policy(
                policy_result,
                adjudicated_context,
                semantic_adjudication,
            )
            self._confirm_adjudication(semantic_adjudication, updated_policy)
        elif getattr(decision, "requests_self_correction", False):
            semantic_adjudication = self._self_correct_adjudication(
                adjudicated_context,
                semantic_adjudication,
                file_path=file_path,
            )
            updated_policy, updated_context = self._build_updated_policy(
                policy_result,
                adjudicated_context,
                semantic_adjudication,
            )
            self._confirm_adjudication(semantic_adjudication, updated_policy)
        return updated_policy, updated_context

    def _call_adjudicator(
        self,
        adjudicated_context: Dict[str, Any],
        *,
        file_path: Optional[str],
        preview_path: Optional[str],
    ) -> Dict[str, Any]:
        adjudicate = self.adjudicator.adjudicate
        try:
            parameters = inspect.signature(adjudicate).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "preview_path" in parameters:
            return adjudicate(
                adjudicated_context,
                file_path=file_path,
                preview_path=preview_path,
            )
        return adjudicate(adjudicated_context, file_path=file_path)

    def _build_updated_policy(
        self,
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        semantic_adjudication: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
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
            adjudication_questions = self.with_question_source(
                adjudication_questions,
                SEMANTIC_ADJUDICATION_STAGE,
            )
            updated_policy["clarification_questions"] = adjudication_questions
        return updated_policy, updated_context

    def _confirm_adjudication(
        self,
        semantic_adjudication: Dict[str, Any],
        updated_policy: Dict[str, Any],
    ) -> Any:
        if self.confirm_stage is None:
            return None
        decision = self.confirm_stage(SEMANTIC_ADJUDICATION_STAGE, {
            "semantic_adjudication": semantic_adjudication,
            "semantic_policy": updated_policy,
        })
        if decision is None or getattr(decision, "continue_processing", True):
            return decision
        if getattr(decision, "requests_retry", False):
            return decision
        if getattr(decision, "requests_self_correction", False):
            return decision
        raise StageConfirmationStopped(
            ensure_stage_stop_message(decision, SEMANTIC_ADJUDICATION_STAGE)
        )

    def _self_correct_adjudication(
        self,
        adjudicated_context: Dict[str, Any],
        semantic_adjudication: Dict[str, Any],
        *,
        file_path: Optional[str],
    ) -> Dict[str, Any]:
        generator = getattr(self.adjudicator, "generate_from_self_correction", None)
        if not callable(generator):
            raise StageConfirmationStopped(
                ensure_stage_stop_message(
                    StageConfirmationResult.self_correct(
                        "图纸语义裁决器不支持模型自纠",
                        stage=SEMANTIC_ADJUDICATION_STAGE,
                    ),
                    SEMANTIC_ADJUDICATION_STAGE,
                )
            )
        evidence_package = self._evidence_package(adjudicated_context)
        case = StageSelfCorrectionCase(
            stage=SEMANTIC_ADJUDICATION_STAGE,
            round_index=1,
            max_rounds=2,
            stage_payload={"drawing_evidence_package": evidence_package},
            previous_output=dict(semantic_adjudication),
            validation_issues=[
                ValidationIssue(
                    code="user_requested_semantic_adjudication_self_correction",
                    message="用户在图纸语义裁决阶段要求模型自纠",
                    severity="warning",
                    fixable=True,
                    impact="用户认为当前视图、尺寸或特征语义裁决可能需要复核",
                    correction_target="重新检查证据 ID、视图角色、尺寸角色、特征角色和追问项",
                )
            ],
            output_contract={
                "required_fields": [
                    "confidence",
                    "view_roles",
                    "dimension_roles",
                    "feature_roles",
                    "derived_dimensions",
                    "clarification_questions",
                    "uncertainties",
                    "warnings",
                ],
                "evidence_id_policy": "只能引用 drawing_evidence_package 中存在的证据 ID",
            },
            generate=generator,
            correction_goal="用户要求复核并重新生成图纸语义裁决；不得新增证据 ID 或图纸事实。",
            log_trigger="user_requested_semantic_adjudication_self_correction",
            log_result="用户触发后已重新生成图纸语义裁决",
        )
        result = StageSelfCorrectionSession().self_correct(case, file_path=file_path)
        if result.corrected_output is not None:
            return result.corrected_output
        return semantic_adjudication

    @staticmethod
    def _evidence_package(context: Dict[str, Any]) -> Dict[str, Any]:
        semantic_policy = context.get("semantic_policy", {}) or {}
        package = semantic_policy.get("drawing_evidence_package")
        if isinstance(package, dict):
            return package
        package = context.get("drawing_evidence_package")
        return package if isinstance(package, dict) else {}

    @staticmethod
    def with_question_source(
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
    def clarification_stage_for_policy_result(policy_result: Dict[str, Any]) -> str:
        questions = policy_result.get("clarification_questions", []) or []
        if questions and all(
            isinstance(question, dict)
            and question.get("source_stage") == SEMANTIC_ADJUDICATION_STAGE
            for question in questions
        ):
            return SEMANTIC_ADJUDICATION_STAGE
        return SEMANTIC_POLICY_STAGE
