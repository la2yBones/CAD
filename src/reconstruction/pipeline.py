#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义重建管道，与图纸分析编排层解耦。"""

from typing import Any, Dict, Optional

from .context import ReconstructionContextBuilder
from .semantic_policy import SemanticPolicy
from .semantics import PartSemanticGenerator
from .instruction_generator import FreeCADInstructionGenerator
from .modeling_path import PLANAR_EXTRUDE, choose_modeling_path
from src.utils.stage_confirmation import (
    StageConfirmationStopped,
    StageReview,
    resolve_stage_confirmation,
)


class SemanticReconstructionPipeline:
    """构建重建上下文、零件语义和可执行建模指令。"""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_builder = ReconstructionContextBuilder()
        self.semantic_policy = SemanticPolicy()
        self.semantic_generator = PartSemanticGenerator(api_key, self.config)
        self.instruction_generator = FreeCADInstructionGenerator(api_key, self.config)
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
        adjudicated_context = policy_result["adjudicated_context"]
        summary_context = self.context_builder.build_summary(adjudicated_context)
        self._confirm_stage("view_analysis", {
            "view_analysis": view_analysis,
            "dimension_data": dimension_data,
            "semantic_policy": policy_result,
        })
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

        modeling_path_decision = choose_modeling_path(view_analysis, part_semantics)

        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = self._build_blocked_modeling_result(part_semantics)
        elif modeling_path_decision["modeling_path"] == PLANAR_EXTRUDE:
            modeling_result = self._build_planar_extrude_modeling_result(part_semantics)
        else:
            modeling_result = self.instruction_generator.generate(
                enriched_geometry if local_relationships else geometry_data,
                view_analysis,
                dimension_data,
                extrude_height,
                reconstruction_context=adjudicated_context,
                part_semantics=part_semantics,
                file_path=file_path,
            )

        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
            "modeling_instructions": modeling_result,
        }

    def continue_with_clarification(
        self,
        clarification_context: Dict[str, Any],
        clarification_answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """复用已完成的解析/视图/尺寸结果，从裁决阶段继续。"""
        reconstruction_context = clarification_context["reconstruction_context"]
        policy_result = self.semantic_policy.evaluate(
            reconstruction_context,
            clarification_answers=clarification_answers,
        )
        adjudicated_context = policy_result["adjudicated_context"]
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
        modeling_path_decision = choose_modeling_path(
            clarification_context["view_analysis"],
            part_semantics,
        )
        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = self._build_blocked_modeling_result(part_semantics)
        elif modeling_path_decision["modeling_path"] == PLANAR_EXTRUDE:
            modeling_result = self._build_planar_extrude_modeling_result(part_semantics)
        else:
            modeling_result = self.instruction_generator.generate(
                clarification_context["geometry_data"],
                clarification_context["view_analysis"],
                clarification_context["dimension_data"],
                clarification_context["extrude_height"],
                reconstruction_context=adjudicated_context,
                part_semantics=part_semantics,
                file_path=clarification_context.get("file_path"),
            )
        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
            "modeling_instructions": modeling_result,
        }

    def _confirm_stage(self, stage: str, payload: Dict[str, Any]) -> None:
        """Let interactive callers review a completed LLM stage before continuing."""
        confirmation = getattr(self, "stage_confirmation", None)
        if confirmation is None:
            confirmation = resolve_stage_confirmation(getattr(self, "config", {}))
            self.stage_confirmation = confirmation
        if not confirmation.should_continue(StageReview(stage=stage, payload=payload)):
            raise StageConfirmationStopped(f"用户在 {stage} 阶段确认后停止处理")

    def _is_semantic_confidence_sufficient(self, part_semantics: Dict[str, Any]) -> bool:
        confidence = float(part_semantics.get("confidence") or 0.0)
        threshold = float(self.config.get("semantic_min_confidence", 0.70))
        return confidence >= threshold

    def _build_blocked_modeling_result(self, part_semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_summary": part_semantics.get("summary", ""),
            "modeling_strategy": "",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": part_semantics.get("key_dimensions", []),
            "warnings": [
                "零件语义置信度不足，已停止自动建模",
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
            "key_dimensions": [],
            "uncertainties": [
                "语义裁决需要用户澄清后才能继续自动建模"
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
            "warnings": ["语义裁决需要用户澄清后才能继续自动建模"],
            "blocked_by_clarification": True,
            "clarification_questions": policy_result["clarification_questions"],
        }

    def _build_planar_extrude_modeling_result(self, part_semantics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_summary": part_semantics.get("summary", ""),
            "modeling_strategy": "由智能模式裁决为可平面拉伸图，转交基础拉伸执行路径",
            "freecad_script": "",
            "instructions": [],
            "key_dimensions": part_semantics.get("key_dimensions", []),
            "warnings": [],
            "routed_to_planar_extrude": True,
        }

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
    ) -> Dict[str, Any]:
        return {
            "geometry_data": geometry_data,
            "view_analysis": view_analysis,
            "dimension_data": dimension_data,
            "local_relationships": local_relationships,
            "extrude_height": extrude_height,
            "file_path": file_path,
            "reconstruction_context": reconstruction_context,
        }
