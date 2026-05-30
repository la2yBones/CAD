# -*- coding: utf-8 -*-

from src.reconstruction.clarification_response import ClarificationResponse
from src.reconstruction.clarified_modeling_result import ClarifiedModelingResultBuilder


def test_clarified_modeling_result_blocks_low_confidence_semantics():
    part_semantics = {
        "confidence": 0.2,
        "summary": "unclear",
        "key_dimensions": [{"name": "width", "value": 10}],
        "warnings": ["缺少主体厚度"],
    }

    _, decision, modeling_result = ClarifiedModelingResultBuilder().build(
        clarification_response=ClarificationResponse(),
        part_semantics=part_semantics,
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
        build_modeling_result=lambda *_: {"freecad_script": "pass"},
    )

    assert decision == {"modeling_path": "semantic_reconstruction"}
    assert modeling_result["blocked_by_semantic_confidence"] is True
    assert modeling_result["key_dimensions"] == [{"name": "width", "value": 10}]


def test_clarified_modeling_result_waits_for_path_clarification_without_hint():
    part_semantics = {"confidence": 0.9}
    decision = {
        "blocked_by_path_contract": True,
        "clarification_questions": [{"id": "provide_extrusion_depth"}],
    }

    resolved_semantics, resolved_decision, modeling_result = (
        ClarifiedModelingResultBuilder().build(
            clarification_response=ClarificationResponse(),
            part_semantics=part_semantics,
            modeling_path_decision=decision,
            build_modeling_result=lambda *_: {"freecad_script": "pass"},
        )
    )

    assert resolved_semantics is part_semantics
    assert resolved_decision is decision
    assert modeling_result["blocked_by_path_contract"] is True
    assert modeling_result["clarification_questions"] == [
        {"id": "provide_extrusion_depth"}
    ]


def test_clarified_modeling_result_falls_back_to_semantic_reconstruction_with_hint():
    part_semantics = {"confidence": 0.9}
    decision = {
        "modeling_path": "planar_extrude",
        "blocked_by_path_contract": True,
        "candidate_paths": [
            {
                "path": "planar_extrude",
                "eligible": True,
                "missing_fields": ["extrusion_depth"],
            }
        ],
        "clarification_questions": [{"id": "provide_extrusion_depth"}],
    }

    resolved_semantics, resolved_decision, modeling_result = (
        ClarifiedModelingResultBuilder().build(
            clarification_response=ClarificationResponse(
                user_modeling_hint="主体先建出来。"
            ),
            part_semantics=part_semantics,
            modeling_path_decision=decision,
            build_modeling_result=lambda semantics, path_decision: {
                "semantic_path": path_decision["modeling_path"],
                "fallback": semantics["path_clarification_fallback"],
            },
        )
    )

    assert resolved_decision["modeling_path"] == "semantic_reconstruction"
    assert resolved_decision["fallback_from_path_clarification"] is True
    assert (
        resolved_semantics["path_clarification_fallback"]["missing_fields"]
        == ["extrusion_depth"]
    )
    assert modeling_result["semantic_path"] == "semantic_reconstruction"
    assert modeling_result["fallback"]["original_modeling_path"] == "planar_extrude"


def test_clarified_modeling_result_delegates_normal_modeling_result():
    resolved_semantics, resolved_decision, modeling_result = (
        ClarifiedModelingResultBuilder().build(
            clarification_response=ClarificationResponse(),
            part_semantics={"confidence": 0.9},
            modeling_path_decision={"modeling_path": "semantic_reconstruction"},
            build_modeling_result=lambda semantics, decision: {
                "confidence": semantics["confidence"],
                "path": decision["modeling_path"],
            },
        )
    )

    assert resolved_semantics == {"confidence": 0.9}
    assert resolved_decision == {"modeling_path": "semantic_reconstruction"}
    assert modeling_result == {
        "confidence": 0.9,
        "path": "semantic_reconstruction",
    }
