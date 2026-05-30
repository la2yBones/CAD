# -*- coding: utf-8 -*-

from src.reconstruction.clarification import UNKNOWN_ANSWER
from src.reconstruction.semantic_clarification_answers import (
    FEATURE_DETAIL_DIMENSION_KEY,
    SemanticClarificationAnswerApplier,
)


def test_applier_binds_selected_multiview_axis_without_mutating_input():
    bindings = [{
        "text": "90",
        "value": 90.0,
        "semantic_role": "unresolved_linear",
    }]

    resolved = SemanticClarificationAnswerApplier().apply(
        bindings,
        {"bind_profile_length": "90"},
    )

    assert bindings[0]["semantic_role"] == "unresolved_linear"
    assert resolved[0]["semantic_role"] == "profile_length"
    assert resolved[0]["source"] == "user_confirmed"
    assert resolved[0]["binding_status"] == "adjudicated"


def test_applier_excludes_unknown_candidate_answer():
    bindings = [{
        "text": "96",
        "value": 96.0,
        "semantic_role": "profile_length",
        "binding_status": "candidate",
    }]

    resolved = SemanticClarificationAnswerApplier().apply(
        bindings,
        {"resolve_profile_length": UNKNOWN_ANSWER},
    )

    assert resolved[0]["semantic_role"] == "excluded_by_user"
    assert resolved[0]["confidence"] == 0.0
    assert "已排除自动绑定" in resolved[0]["evidence"][0]


def test_applier_resolves_conflicting_candidate_role():
    bindings = [
        {"text": "90", "value": 90.0, "semantic_role": "profile_length"},
        {"text": "96", "value": 96.0, "semantic_role": "profile_length"},
    ]

    resolved = SemanticClarificationAnswerApplier().apply(
        bindings,
        {"resolve_profile_length": "96"},
    )

    by_text = {item["text"]: item for item in resolved}
    assert by_text["96"]["source"] == "user_confirmed"
    assert by_text["96"]["binding_status"] == "adjudicated"
    assert by_text["90"]["semantic_role"] == "unresolved_linear"


def test_applier_promotes_feature_detail_dimension_answer():
    bindings = [{
        "text": "40",
        "value": 40.0,
        "semantic_role": "unresolved_linear",
    }]
    answer = (
        '{"action":"bind_feature_dimension","dimension_text":"40",'
        '"role":"feature_height","feature_kind":"boss",'
        '"feature_description":"圆柱凸台"}'
    )

    resolved = SemanticClarificationAnswerApplier().apply(
        bindings,
        {FEATURE_DETAIL_DIMENSION_KEY: answer},
    )

    assert resolved[0]["semantic_role"] == "feature_height"
    assert resolved[0]["source"] == "user_confirmed"
    assert resolved[0]["feature_kind"] == "boss"
    assert resolved[0]["feature_description"] == "圆柱凸台"
