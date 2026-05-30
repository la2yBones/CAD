#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义重建产出的类型化结果 — 整条智能处理管道的核心数据契约。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ModelingInstructionsResult:
    """建模指令阶段的产出，自纠路径上最频繁访问的子结构。"""

    analysis_summary: str = ""
    modeling_strategy: str = ""
    freecad_script: str = ""
    instructions: List[Dict[str, Any]] = field(default_factory=list)
    key_dimensions: List[Dict[str, Any]] = field(default_factory=list)
    completed_features: List[Dict[str, Any]] = field(default_factory=list)
    skipped_features: List[Dict[str, Any]] = field(default_factory=list)
    partial_completion_reason: str = ""
    warnings: List[str] = field(default_factory=list)
    blocked_by_clarification: bool = False
    blocked_by_path_contract: bool = False
    blocked_by_semantic_confidence: bool = False
    blocked_by_task_readiness: bool = False
    routed_to_planar_extrude: bool = False
    routed_to_revolve: bool = False
    clarification_questions: List[Dict[str, Any]] = field(default_factory=list)
    self_correction_applied: bool = False
    self_correction_log: List[Dict[str, Any]] = field(default_factory=list)
    stage_retry_applied: bool = False
    stage_retry_log: List[Dict[str, Any]] = field(default_factory=list)
    _modeling_task_payload: Dict[str, Any] = field(default_factory=dict)
    _raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ModelingInstructionsResult":
        if data is None:
            return cls()
        return cls(
            analysis_summary=str(data.get("analysis_summary") or ""),
            modeling_strategy=str(data.get("modeling_strategy") or ""),
            freecad_script=str(data.get("freecad_script") or ""),
            instructions=list(data.get("instructions") or []),
            key_dimensions=list(data.get("key_dimensions") or []),
            completed_features=list(data.get("completed_features") or []),
            skipped_features=list(data.get("skipped_features") or []),
            partial_completion_reason=str(data.get("partial_completion_reason") or ""),
            warnings=list(data.get("warnings") or []),
            blocked_by_clarification=bool(data.get("blocked_by_clarification")),
            blocked_by_path_contract=bool(data.get("blocked_by_path_contract")),
            blocked_by_semantic_confidence=bool(data.get("blocked_by_semantic_confidence")),
            blocked_by_task_readiness=bool(data.get("blocked_by_task_readiness")),
            routed_to_planar_extrude=bool(data.get("routed_to_planar_extrude")),
            routed_to_revolve=bool(data.get("routed_to_revolve")),
            clarification_questions=list(data.get("clarification_questions") or []),
            self_correction_applied=bool(data.get("self_correction_applied")),
            self_correction_log=list(data.get("self_correction_log") or []),
            stage_retry_applied=bool(data.get("stage_retry_applied")),
            stage_retry_log=list(data.get("stage_retry_log") or []),
            _modeling_task_payload=dict(data.get("_modeling_task_payload") or {}),
            _raw=dict(data),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = dict(self._raw)
        result.update({
            "analysis_summary": self.analysis_summary,
            "modeling_strategy": self.modeling_strategy,
            "freecad_script": self.freecad_script,
            "instructions": self.instructions,
            "key_dimensions": self.key_dimensions,
            "completed_features": self.completed_features,
            "skipped_features": self.skipped_features,
            "partial_completion_reason": self.partial_completion_reason,
            "warnings": self.warnings,
            "blocked_by_clarification": self.blocked_by_clarification,
            "blocked_by_path_contract": self.blocked_by_path_contract,
            "blocked_by_semantic_confidence": self.blocked_by_semantic_confidence,
            "blocked_by_task_readiness": self.blocked_by_task_readiness,
            "routed_to_planar_extrude": self.routed_to_planar_extrude,
            "routed_to_revolve": self.routed_to_revolve,
            "clarification_questions": self.clarification_questions,
            "self_correction_applied": self.self_correction_applied,
            "self_correction_log": self.self_correction_log,
            "stage_retry_applied": self.stage_retry_applied,
            "stage_retry_log": self.stage_retry_log,
            "_modeling_task_payload": self._modeling_task_payload,
        })
        return result

    @property
    def has_script(self) -> bool:
        return bool(self.freecad_script.strip())

    @property
    def is_blocked(self) -> bool:
        return (
            self.blocked_by_clarification
            or self.blocked_by_path_contract
            or self.blocked_by_semantic_confidence
            or self.blocked_by_task_readiness
        )

    @property
    def is_partial(self) -> bool:
        return bool(self.skipped_features) or bool(self.partial_completion_reason)

    @property
    def blocked_reason(self) -> str:
        if not self.is_blocked:
            return ""
        reasons = []
        if self.blocked_by_clarification:
            reasons.append("存在未裁决的澄清问题")
        if self.blocked_by_path_contract:
            reasons.append("建模路径合同不满足")
        if self.blocked_by_semantic_confidence:
            reasons.append("语义置信度低于阈值")
        if self.blocked_by_task_readiness:
            reasons.append("建模任务就绪度不足")
        return "；".join(reasons)

    @property
    def correction_summary(self) -> str:
        parts = []
        if self.is_blocked:
            parts.append(f"建模被阻断：{self.blocked_reason}")
        if self.is_partial:
            if self.skipped_features:
                names = [f.get("name", f.get("kind", "?")) for f in self.skipped_features[:5]]
                parts.append(f"跳过特征：{', '.join(names)}")
            if self.partial_completion_reason:
                parts.append(f"部分完成原因：{self.partial_completion_reason}")
        if self.warnings:
            parts.append(f"风险提示({len(self.warnings)}项)")
        if not parts:
            if self.has_script:
                parts.append("已有脚本但用户要求复核")
            else:
                parts.append("无脚本输出")
        return "；".join(parts)


@dataclass
class ModelingPathDecisionResult:
    """建模路径裁决视图。"""

    modeling_path: str = ""
    reason: str = ""
    candidate_paths: List[str] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_questions: List[Dict[str, Any]] = field(default_factory=list)
    fallback_from_path_clarification: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ModelingPathDecisionResult":
        if data is None:
            return cls()
        return cls(
            modeling_path=str(data.get("modeling_path") or ""),
            reason=str(data.get("reason") or ""),
            candidate_paths=list(data.get("candidate_paths") or []),
            requires_clarification=bool(data.get("requires_clarification")),
            clarification_questions=list(data.get("clarification_questions") or []),
            fallback_from_path_clarification=bool(data.get("fallback_from_path_clarification")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modeling_path": self.modeling_path,
            "reason": self.reason,
            "candidate_paths": self.candidate_paths,
            "requires_clarification": self.requires_clarification,
            "clarification_questions": self.clarification_questions,
            "fallback_from_path_clarification": self.fallback_from_path_clarification,
        }


@dataclass
class IntelligentAnalysisResult:
    """智能处理编排的完整产出，整条管道的核心数据契约。"""

    view_analysis: Dict[str, Any] = field(default_factory=dict)
    rule_view_analysis: Dict[str, Any] = field(default_factory=dict)
    dimension_extraction: Dict[str, Any] = field(default_factory=dict)
    local_relationships: Optional[Dict[str, Any]] = None
    reconstruction_context: Dict[str, Any] = field(default_factory=dict)
    semantic_policy: Dict[str, Any] = field(default_factory=dict)
    adjudicated_context: Dict[str, Any] = field(default_factory=dict)
    part_semantics: Dict[str, Any] = field(default_factory=dict)
    modeling_path_decision: ModelingPathDecisionResult = field(default_factory=ModelingPathDecisionResult)
    modeling_instructions: ModelingInstructionsResult = field(default_factory=ModelingInstructionsResult)
    clarification_context: Optional[Dict[str, Any]] = None
    _cache_hit: bool = False
    _raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "IntelligentAnalysisResult":
        if data is None:
            return cls()
        return cls(
            view_analysis=dict(data.get("view_analysis") or {}),
            rule_view_analysis=dict(data.get("rule_view_analysis") or {}),
            dimension_extraction=dict(data.get("dimension_extraction") or {}),
            local_relationships=data.get("local_relationships"),
            reconstruction_context=dict(data.get("reconstruction_context") or {}),
            semantic_policy=dict(data.get("semantic_policy") or {}),
            adjudicated_context=dict(data.get("adjudicated_context") or {}),
            part_semantics=dict(data.get("part_semantics") or {}),
            modeling_path_decision=ModelingPathDecisionResult.from_dict(
                data.get("modeling_path_decision")
            ),
            modeling_instructions=ModelingInstructionsResult.from_dict(
                data.get("modeling_instructions")
            ),
            clarification_context=data.get("clarification_context"),
            _cache_hit=bool(data.get("_cache_hit")),
            _raw=dict(data),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = dict(self._raw)
        result.update({
            "view_analysis": self.view_analysis,
            "rule_view_analysis": self.rule_view_analysis,
            "dimension_extraction": self.dimension_extraction,
            "local_relationships": self.local_relationships,
            "reconstruction_context": self.reconstruction_context,
            "semantic_policy": self.semantic_policy,
            "adjudicated_context": self.adjudicated_context,
            "part_semantics": self.part_semantics,
            "modeling_path_decision": self.modeling_path_decision.to_dict(),
            "modeling_instructions": self.modeling_instructions.to_dict(),
            "clarification_context": self.clarification_context,
            "_cache_hit": self._cache_hit,
        })
        return result

    @property
    def has_script(self) -> bool:
        return self.modeling_instructions.has_script

    @property
    def is_fallback(self) -> bool:
        mi = self.modeling_instructions
        return (
            not mi.has_script
            and not mi.is_blocked
            and not mi.blocked_by_clarification
        )

    @property
    def needs_clarification(self) -> bool:
        return bool(self.modeling_instructions.blocked_by_clarification)

    @property
    def modeling_path(self) -> str:
        return self.modeling_path_decision.modeling_path
