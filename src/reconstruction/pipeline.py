#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义重建管道，与图纸分析编排层解耦。"""

from typing import Any, Dict, Optional

from .context import ReconstructionContextBuilder
from .semantics import PartSemanticGenerator
from .instruction_generator import FreeCADInstructionGenerator


class SemanticReconstructionPipeline:
    """构建重建上下文、零件语义和可执行建模指令。"""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_builder = ReconstructionContextBuilder()
        self.semantic_generator = PartSemanticGenerator(api_key, self.config)
        self.instruction_generator = FreeCADInstructionGenerator(api_key, self.config)

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
        summary_context = self.context_builder.build_summary(reconstruction_context)
        part_semantics = self.semantic_generator.generate(
            reconstruction_context,
            retry_context=summary_context,
            file_path=file_path,
        )

        if not self._is_semantic_confidence_sufficient(part_semantics):
            modeling_result = self._build_blocked_modeling_result(part_semantics)
        else:
            modeling_result = self.instruction_generator.generate(
                enriched_geometry if local_relationships else geometry_data,
                view_analysis,
                dimension_data,
                extrude_height,
                reconstruction_context=reconstruction_context,
                part_semantics=part_semantics,
                file_path=file_path,
            )

        return {
            "reconstruction_context": reconstruction_context,
            "part_semantics": part_semantics,
            "modeling_instructions": modeling_result,
        }

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
