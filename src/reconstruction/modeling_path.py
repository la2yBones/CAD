#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Choose the final modeling path from contract-validated candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from .clarification_questions import clarification_question, choice_option
from .path_contracts import (
    build_planar_contract_clarification_questions,
    evaluate_planar_extrude_contract,
    evaluate_revolve_contract,
)


PLANAR_EXTRUDE = "planar_extrude"
REVOLVE = "revolve"
SEMANTIC_RECONSTRUCTION = "semantic_reconstruction"

ContractEvaluator = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
ClarificationBuilder = Callable[[Dict[str, Any]], List[Dict[str, Any]]]
ModelingResultBuilder = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class ModelingPathDecision:
    """Read-only view over a modeling-path decision dict."""

    data: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelingPathDecision":
        return cls(value)

    @property
    def modeling_path(self) -> Any:
        return self.data.get("modeling_path")

    @property
    def candidate_paths(self) -> List[Dict[str, Any]]:
        return list(self.data.get("candidate_paths", []) or [])

    @property
    def clarification_questions(self) -> List[Dict[str, Any]]:
        return list(self.data.get("clarification_questions", []) or [])

    @property
    def requires_clarification(self) -> bool:
        return bool(
            self.data.get("blocked_by_path_contract")
            or self.data.get("requires_path_preference")
        )

    @property
    def path_requiring_clarification(self) -> Any:
        for candidate in self.candidate_paths:
            if candidate.get("rejection_reasons"):
                continue
            if candidate.get("missing_fields"):
                return candidate.get("path") or self.modeling_path
        return self.modeling_path

    @property
    def missing_contract_fields(self) -> List[str]:
        missing_fields = []
        for candidate in self.candidate_paths:
            if candidate.get("rejection_reasons"):
                continue
            for field in candidate.get("missing_fields", []) or []:
                if field not in missing_fields:
                    missing_fields.append(field)
        return missing_fields


@dataclass(frozen=True)
class ModelingPathAdapter:
    """Registration record for one specialized modeling path."""

    path: str
    display_label: str
    evaluate_contract: ContractEvaluator
    build_clarification_questions: ClarificationBuilder
    build_modeling_result: ModelingResultBuilder


class ModelingPathRegistry:
    """Evaluate and route specialized modeling paths from registered adapters."""

    def __init__(self, adapters: List[ModelingPathAdapter]):
        self.adapters = list(adapters)
        self._by_path = {adapter.path: adapter for adapter in self.adapters}

    def evaluate_candidates(
        self,
        view_analysis: Dict[str, Any],
        part_semantics: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        return [
            adapter.evaluate_contract(view_analysis, part_semantics)
            for adapter in self.adapters
        ]

    def choose(
        self,
        view_analysis: Dict[str, Any],
        part_semantics: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidates = self.evaluate_candidates(view_analysis, part_semantics)
        eligible = [
            candidate for candidate in candidates
            if candidate["eligible"] and candidate.get("implemented", False)
        ]
        if len(eligible) == 1:
            return _decision(
                eligible[0]["path"],
                f"{eligible[0]['path']} 路径契约已闭合",
                candidates=candidates,
            )
        if len(eligible) > 1:
            preferred = part_semantics.get("preferred_modeling_path")
            if preferred in {candidate["path"] for candidate in eligible}:
                return _decision(
                    preferred,
                    "多条专用路径均可执行，采用大模型给出的优选路径",
                    candidates=candidates,
                )
            decision = _decision(
                SEMANTIC_RECONSTRUCTION,
                "多条专用建模路径均满足契约，但尚未给出优选路径",
                candidates=candidates,
            )
            decision["requires_path_preference"] = True
            decision["clarification_questions"] = [
                self._build_path_preference_question(eligible)
            ]
            return decision

        decision = _decision(
            SEMANTIC_RECONSTRUCTION,
            "无专用建模路径满足当前契约",
            candidates=candidates,
        )
        clarification = self._first_contract_clarification(candidates)
        if clarification:
            decision["blocked_by_path_contract"] = True
            decision["clarification_questions"] = clarification
        return decision

    def build_routed_modeling_result(
        self,
        modeling_path_decision: Dict[str, Any],
        part_semantics: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        decision = ModelingPathDecision.from_mapping(modeling_path_decision)
        adapter = self._by_path.get(decision.modeling_path)
        if not adapter:
            return None
        return adapter.build_modeling_result(part_semantics)

    def label_for_path(self, path: str) -> str:
        adapter = self._by_path.get(path)
        if not adapter:
            return path
        return adapter.display_label

    def _first_contract_clarification(
        self,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        for candidate in candidates:
            if not candidate.get("missing_fields") or candidate.get("rejection_reasons"):
                continue
            adapter = self._by_path.get(candidate.get("path"))
            if not adapter:
                continue
            questions = adapter.build_clarification_questions(candidate)
            if questions:
                return questions
        return []

    def _build_path_preference_question(
        self,
        eligible: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return clarification_question(
            question_id="select_modeling_path",
            text="系统找到多种可行建模方式，请选择更符合图纸意图的一种。",
            kind="single_choice",
            reason="不同建模方式都能执行，但生成的几何过程不同；需要用户按图纸意图选择。",
            example="板件通常选平面拉伸；轴对称零件通常选回转体。",
            options=[
                choice_option(
                    self.label_for_path(candidate["path"]),
                    candidate["path"],
                )
                for candidate in eligible
            ],
        )


def choose_modeling_path(
    view_analysis: Dict[str, Any],
    part_semantics: Dict[str, Any],
) -> Dict[str, Any]:
    """Choose a path from contract-validated candidates."""
    return default_modeling_path_registry().choose(view_analysis, part_semantics)


def default_modeling_path_registry() -> ModelingPathRegistry:
    return ModelingPathRegistry([
        ModelingPathAdapter(
            path=PLANAR_EXTRUDE,
            display_label="平面拉伸路径",
            evaluate_contract=evaluate_planar_extrude_contract,
            build_clarification_questions=build_planar_contract_clarification_questions,
            build_modeling_result=_build_planar_extrude_modeling_result,
        ),
        ModelingPathAdapter(
            path=REVOLVE,
            display_label="回转体路径",
            evaluate_contract=evaluate_revolve_contract,
            build_clarification_questions=_no_clarification_questions,
            build_modeling_result=_build_revolve_modeling_result,
        ),
    ])


def _decision(path: str, reason: str, *, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "modeling_path": path,
        "reason": reason,
        "candidate_paths": candidates,
    }


def _build_planar_extrude_modeling_result(part_semantics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "analysis_summary": part_semantics.get("summary", ""),
        "modeling_strategy": "由智能处理裁决为可平面拉伸图，转交平面拉伸执行路径",
        "freecad_script": "",
        "instructions": [],
        "key_dimensions": part_semantics.get("key_dimensions", []),
        "warnings": [],
        "routed_to_planar_extrude": True,
    }


def _build_revolve_modeling_result(part_semantics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "analysis_summary": part_semantics.get("summary", ""),
        "modeling_strategy": "由智能处理裁决为回转体路径，转交确定性回转执行器",
        "freecad_script": "",
        "instructions": [],
        "key_dimensions": part_semantics.get("key_dimensions", []),
        "warnings": [],
        "routed_to_revolve": True,
    }


def _no_clarification_questions(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    return []
