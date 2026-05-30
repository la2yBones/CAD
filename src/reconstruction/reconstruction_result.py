#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义重建结果装配。"""
from __future__ import annotations

from typing import Any, Dict

from .clarification import ClarificationOutlet


class ReconstructionResultBuilder:
    """装配语义重建内核对外返回的结果结构。"""

    def __init__(self, clarification_outlet: ClarificationOutlet | None = None) -> None:
        self.clarification_outlet = clarification_outlet or ClarificationOutlet()

    def build(
        self,
        *,
        reconstruction_context: Dict[str, Any],
        policy_result: Dict[str, Any],
        adjudicated_context: Dict[str, Any],
        part_semantics: Dict[str, Any],
        modeling_path_decision: Dict[str, Any],
        modeling_result: Dict[str, Any],
        base_clarification_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "reconstruction_context": reconstruction_context,
            "semantic_policy": policy_result,
            "adjudicated_context": adjudicated_context,
            "part_semantics": part_semantics,
            "modeling_path_decision": modeling_path_decision,
            "modeling_instructions": modeling_result,
            **self.clarification_outlet.path_payload(
                modeling_result=modeling_result,
                base_context=base_clarification_context,
                policy_result=policy_result,
                adjudicated_context=adjudicated_context,
                part_semantics=part_semantics,
                modeling_path_decision=modeling_path_decision,
            ),
        }
