#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段内模型自纠的数据合同。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


CONTINUE = "continue"
STOP = "stop"
RETRY_STAGE = "retry_stage"
SELF_CORRECT = "self_correct"


CORRECTED = "corrected"
CONTINUE_WITH_RISK = "continue_with_risk"
NEEDS_USER_CONFIRMATION = "needs_user_confirmation"
PENDING_RECOVERY = "pending_recovery"
FAILED = "failed"


@dataclass(frozen=True)
class ValidationIssue:
    """本地校验器产出的结构化问题。"""

    code: str
    message: str
    severity: str = "error"
    fixable: bool = True
    impact: str = ""
    correction_target: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "fixable": self.fixable,
        }
        if self.impact:
            data["impact"] = self.impact
        if self.correction_target:
            data["correction_target"] = self.correction_target
        if self.details:
            data["details"] = dict(self.details)
        return data


@dataclass(frozen=True)
class SupervisionAction:
    """阶段确认点的用户监督动作。"""

    action: str
    label: str
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "action": self.action,
            "label": self.label,
        }
        if self.description:
            data["description"] = self.description
        return data


@dataclass(frozen=True)
class SelfCorrectionRequest:
    """发送给阶段生成器的结构化自纠请求。"""

    stage: str
    round_index: int
    max_rounds: int
    stage_payload: Dict[str, Any]
    previous_output: Dict[str, Any]
    validation_issues: List[ValidationIssue]
    output_contract: Dict[str, Any]
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    correction_goal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "stage": self.stage,
            "round_index": self.round_index,
            "max_rounds": self.max_rounds,
            "stage_payload": dict(self.stage_payload),
            "previous_output": dict(self.previous_output),
            "validation_issues": [
                issue.to_dict() for issue in self.validation_issues
            ],
            "output_contract": dict(self.output_contract),
            "evidence_refs": [dict(item) for item in self.evidence_refs],
        }
        if self.correction_goal:
            data["correction_goal"] = self.correction_goal
        return data

    @property
    def is_last_round(self) -> bool:
        return self.round_index >= self.max_rounds


@dataclass(frozen=True)
class CandidateOption:
    """用户候选确认中的单个选项。"""

    id: str
    label: str
    value: Any
    evidence: List[str] = field(default_factory=list)
    risk: str = ""
    recommended: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "evidence": list(self.evidence),
            "recommended": self.recommended,
        }
        if self.risk:
            data["risk"] = self.risk
        return data


@dataclass(frozen=True)
class SelfCorrectionResult:
    """阶段内自纠会话返回给管线的结构化结果。"""

    status: str
    corrected_output: Optional[Dict[str, Any]] = None
    self_correction_log: List[Dict[str, Any]] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)
    candidate_options: List[CandidateOption] = field(default_factory=list)
    next_action: str = CONTINUE
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "status": self.status,
            "self_correction_log": [
                dict(item) for item in self.self_correction_log
            ],
            "risk_notes": list(self.risk_notes),
            "candidate_options": [
                option.to_dict() for option in self.candidate_options
            ],
            "next_action": self.next_action,
        }
        if self.corrected_output is not None:
            data["corrected_output"] = dict(self.corrected_output)
        if self.message:
            data["message"] = self.message
        return data

    @property
    def can_continue(self) -> bool:
        return self.status in {CORRECTED, CONTINUE_WITH_RISK}


@dataclass(frozen=True)
class StageSelfCorrectionCase:
    """单个阶段接入阶段内自纠会话的 Adapter。"""

    stage: str
    stage_payload: Dict[str, Any]
    previous_output: Dict[str, Any]
    validation_issues: List[ValidationIssue]
    output_contract: Dict[str, Any]
    generate: Callable[..., Any]
    correction_goal: str = ""
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    round_index: int = 1
    max_rounds: int = 2
    log_trigger: str = "user_requested_self_correction"
    log_result: str = "用户触发后已重新生成阶段结果"

    def to_request(self) -> SelfCorrectionRequest:
        return SelfCorrectionRequest(
            stage=self.stage,
            round_index=self.round_index,
            max_rounds=self.max_rounds,
            stage_payload=self.stage_payload,
            previous_output=self.previous_output,
            validation_issues=self.validation_issues,
            output_contract=self.output_contract,
            evidence_refs=self.evidence_refs,
            correction_goal=self.correction_goal,
        )


class StageSelfCorrectionSession:
    """组织单个 LLM 调用阶段内的用户触发模型自纠。"""

    def self_correct(
        self,
        case: StageSelfCorrectionCase,
        *,
        file_path: Optional[str] = None,
    ) -> SelfCorrectionResult:
        request = case.to_request()
        try:
            output = case.generate(request, file_path=file_path)
        except TypeError:
            output = case.generate(request)

        if not isinstance(output, dict):
            return SelfCorrectionResult(
                status=FAILED,
                message="模型自纠未返回结构化阶段结果",
                next_action=SELF_CORRECT,
            )

        corrected = self._attach_log(output, case, request)
        return SelfCorrectionResult(
            status=CORRECTED,
            corrected_output=corrected,
            self_correction_log=list(corrected.get("self_correction_log") or []),
            next_action=CONTINUE,
        )

    @staticmethod
    def _attach_log(
        output: Dict[str, Any],
        case: StageSelfCorrectionCase,
        request: SelfCorrectionRequest,
    ) -> Dict[str, Any]:
        updated = dict(output)
        updated.setdefault("self_correction_applied", True)
        logs = updated.get("self_correction_log") or []
        if isinstance(logs, dict):
            logs = [logs]
        if not isinstance(logs, list):
            logs = []
        if not logs:
            logs = [{
                "stage": case.stage,
                "round_index": request.round_index,
                "max_rounds": request.max_rounds,
                "trigger": case.log_trigger,
                "issues": [issue.to_dict() for issue in request.validation_issues],
                "result": case.log_result,
            }]
        updated["self_correction_log"] = logs
        return updated


DEFAULT_SUPERVISION_ACTIONS = [
    SupervisionAction(CONTINUE, "继续", "接受当前阶段报告并继续"),
    SupervisionAction(STOP, "终止", "停止当前图纸处理"),
    SupervisionAction(RETRY_STAGE, "重跑阶段", "重新运行当前阶段"),
    SupervisionAction(SELF_CORRECT, "模型自纠", "要求当前阶段进入模型自纠"),
]
