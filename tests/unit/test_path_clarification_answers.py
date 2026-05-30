# -*- coding: utf-8 -*-

from src.reconstruction.clarification_response import ClarificationResponse
from src.reconstruction.clarification import PathClarificationAnswerApplier


def test_path_clarification_answer_applier_updates_explicit_semantics():
    original = {
        "planar_modeling_semantics": {
            "extrusion_depth": None,
            "extrusion_direction": "unknown",
        },
        "preferred_modeling_path": None,
    }

    updated = PathClarificationAnswerApplier().apply(
        original,
        {
            "provide_extrusion_depth": "12.5",
            "provide_extrusion_direction": "Z",
            "select_modeling_path": "planar_extrude",
            "user_modeling_hint": "主体先拉伸，槽可以跳过。",
        },
    )

    assert original["planar_modeling_semantics"]["extrusion_depth"] is None
    assert updated["planar_modeling_semantics"]["extrusion_depth"] == 12.5
    assert updated["planar_modeling_semantics"]["extrusion_direction"] == "Z"
    assert updated["preferred_modeling_path"] == "planar_extrude"
    assert updated["user_modeling_hint"] == "主体先拉伸，槽可以跳过。"


def test_path_clarification_answer_applier_accepts_response_object():
    updated = PathClarificationAnswerApplier().apply(
        {"planar_modeling_semantics": {}},
        ClarificationResponse(
            answers={"provide_extrusion_depth": "8"},
            user_modeling_hint="先做主体。",
        ),
    )

    assert updated["planar_modeling_semantics"]["extrusion_depth"] == 8.0
    assert updated["user_modeling_hint"] == "先做主体。"
    assert updated["user_modeling_hint_policy"] == "drawing_facts_override_user_hint"
