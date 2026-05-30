#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单文件处理流程的结果类型和状态枚举。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Union

from src.reconstruction.analysis_result import IntelligentAnalysisResult


class PipelineStatus(str, Enum):
    """单文件处理流程的真实状态。"""

    COMPLETED = "completed"
    PARTIAL_COMPLETED = "partial_completed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    STOPPED_BY_USER = "stopped_by_user"
    STAGE_ACTION_REQUESTED = "stage_action_requested"


class CADProcessResult:
    """处理结果封装类"""

    def __init__(
        self,
        success: bool,
        input_file: str,
        mode: Optional[str] = None,
        modeling_path: Optional[str] = None,
    ):
        self.success = success
        self.status = PipelineStatus.COMPLETED if success else PipelineStatus.FAILED
        self.input_file = input_file
        self.mode = mode
        self.modeling_path = modeling_path
        self.geometry_data: Optional[Dict] = None
        self.relationships: Optional[Dict] = None
        self.intelligent_analysis: Optional[Union[Dict, IntelligentAnalysisResult]] = None
        self.clarification_questions: list[Dict[str, Any]] = []
        self.clarification_context: Optional[Dict[str, Any]] = None
        self.completed_features: list[Dict[str, Any]] = []
        self.skipped_features: list[Dict[str, Any]] = []
        self.partial_completion_reason: Optional[str] = None
        self.stage_stop_action: Optional[str] = None
        self.stage_stop_stage: Optional[str] = None
        self.output_paths: Dict[str, str] = {}
        self.error_message: Optional[str] = None
        self.entity_count: int = 0

    def mark_completed(self) -> None:
        self.success = True
        self.status = PipelineStatus.COMPLETED
        self.completed_features = []
        self.skipped_features = []
        self.partial_completion_reason = None

    def mark_partial_completed(
        self,
        *,
        skipped_features: Optional[list[Dict[str, Any]]] = None,
        completed_features: Optional[list[Dict[str, Any]]] = None,
        reason: Optional[str] = None,
    ) -> None:
        self.success = True
        self.status = PipelineStatus.PARTIAL_COMPLETED
        self.skipped_features = skipped_features or []
        self.completed_features = completed_features or []
        self.partial_completion_reason = reason or "模型主体已生成并导出，部分细节被跳过"

    def mark_failed(self, error_message: Optional[str] = None) -> None:
        self.success = False
        self.status = PipelineStatus.FAILED
        if error_message is not None:
            self.error_message = error_message

    def mark_needs_clarification(
        self,
        questions: list[Dict[str, Any]],
        clarification_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.success = False
        self.status = PipelineStatus.NEEDS_CLARIFICATION
        self.clarification_questions = questions
        self.clarification_context = clarification_context

    def mark_stopped_by_user(
        self,
        message: Optional[str] = None,
        action: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        self.success = False
        self.status = PipelineStatus.STOPPED_BY_USER
        self.error_message = message or "用户停止处理"
        self.stage_stop_action = action or "stop"
        self.stage_stop_stage = stage

    def mark_stage_action_requested(
        self,
        message: Optional[str] = None,
        action: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        self.success = False
        self.status = PipelineStatus.STAGE_ACTION_REQUESTED
        self.error_message = message or "用户在阶段确认点请求监督动作"
        self.stage_stop_action = action
        self.stage_stop_stage = stage

    @classmethod
    def from_pending_item(cls, item: Dict[str, Any]) -> "CADProcessResult":
        """从持久化的待澄清条目恢复内存中的处理结果。"""
        result = cls(
            success=False,
            input_file=str(item.get("input_file") or ""),
            modeling_path=item.get("modeling_path"),
        )
        result.mark_needs_clarification(
            list(item.get("clarification_questions") or []),
            item.get("clarification_context"),
        )
        result.output_paths.update({
            str(key): str(path)
            for key, path in (item.get("output_paths") or {}).items()
            if path
        })
        result.completed_features = list(item.get("completed_features") or [])
        result.skipped_features = list(item.get("skipped_features") or [])
        result.partial_completion_reason = item.get("partial_completion_reason")
        return result

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'status': self.status.value,
            'input_file': self.input_file,
            'mode': self.mode,
            'modeling_path': self.modeling_path,
            'entity_count': self.entity_count,
            'output_paths': self.output_paths,
            'error_message': self.error_message,
            'has_intelligent_analysis': self.intelligent_analysis is not None,
            'clarification_questions': self.clarification_questions,
            'has_clarification_context': self.clarification_context is not None,
            'completed_features': self.completed_features,
            'skipped_features': self.skipped_features,
            'partial_completion_reason': self.partial_completion_reason,
            'stage_stop_action': self.stage_stop_action,
            'stage_stop_stage': self.stage_stop_stage,
            'stage_supervision_action': self.stage_stop_action,
            'stage_supervision_stage': self.stage_stop_stage,
        }
