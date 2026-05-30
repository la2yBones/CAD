# -*- coding: utf-8 -*-

from src.reconstruction.clarification import ClarificationOutlet


def _policy_result():
    return {
        "dimension_source": "annotation",
        "clarification_questions": [
            {"id": "resolve_profile_length", "source_stage": "semantic_adjudication"}
        ],
    }


def test_clarification_outlet_builds_policy_pending_result_with_context():
    result = ClarificationOutlet().from_policy_questions(
        policy_result=_policy_result(),
        reconstruction_context={"context_version": "reconstruction_context_v1"},
        adjudicated_context={"context_version": "adjudicated_context_v1"},
        geometry_data={"entities": []},
        view_analysis={"views": []},
        dimension_data={"dimensions": []},
        local_relationships=None,
        extrude_height=10.0,
        file_path="part.dxf",
    )

    assert result["modeling_instructions"]["blocked_by_clarification"] is True
    assert result["part_semantics"]["dimension_source"] == "annotation"
    assert (
        result["clarification_context"]["clarification_stage"]
        == "semantic_adjudication"
    )
    assert result["clarification_context"]["file_path"] == "part.dxf"


def test_clarification_outlet_builds_feature_detail_pending_result():
    result = ClarificationOutlet().from_feature_detail_questions(
        policy_result={**_policy_result(), "clarification_questions": []},
        feature_detail_questions=[{"id": "user_modeling_hint", "kind": "text"}],
        reconstruction_context={"context_version": "reconstruction_context_v1"},
        adjudicated_context={"context_version": "adjudicated_context_v1"},
        part_semantics={"part_type": "flange", "confidence": 0.7},
        geometry_data={"entities": []},
        view_analysis={"views": []},
        dimension_data={"dimensions": []},
        local_relationships=None,
        extrude_height=10.0,
        file_path=None,
    )

    assert result["semantic_policy"]["clarification_questions"] == [
        {"id": "user_modeling_hint", "kind": "text"}
    ]
    assert result["modeling_instructions"]["clarification_questions"] == [
        {"id": "user_modeling_hint", "kind": "text"}
    ]
    assert result["part_semantics"]["part_type"] == "flange"


def test_clarification_outlet_keeps_existing_clarification_context_copy():
    context = {
        "clarification_stage": "semantic_policy",
        "geometry_data": {"entities": []},
        "view_analysis": {"views": []},
        "dimension_data": {"dimensions": []},
        "local_relationships": None,
        "extrude_height": 8.0,
        "file_path": "cached.dxf",
        "reconstruction_context": {},
    }

    result = ClarificationOutlet().from_policy_questions(
        policy_result=_policy_result(),
        reconstruction_context={},
        adjudicated_context={},
        geometry_data={"ignored": True},
        view_analysis={"ignored": True},
        dimension_data={"ignored": True},
        local_relationships=None,
        extrude_height=10.0,
        file_path="ignored.dxf",
        clarification_context=context,
    )

    assert result["clarification_context"] == context
    assert result["clarification_context"] is not context


def test_clarification_outlet_builds_path_pending_result():
    result = ClarificationOutlet().path_pending_result(
        {"clarification_questions": [{"id": "provide_extrusion_depth"}]}
    )

    assert result["blocked_by_clarification"] is True
    assert result["blocked_by_path_contract"] is True
    assert result["clarification_questions"] == [{"id": "provide_extrusion_depth"}]


def test_clarification_outlet_builds_path_payload_without_mutating_base_context():
    base_context = {"geometry_data": {"entities": []}}

    payload = ClarificationOutlet().path_payload(
        modeling_result={"blocked_by_path_contract": True},
        base_context=base_context,
        policy_result={"dimension_source": "annotation"},
        adjudicated_context={"context_version": "v1"},
        part_semantics={"part_type": "profile"},
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
    )

    context = payload["clarification_context"]
    assert context["clarification_stage"] == "modeling_path"
    assert context["semantic_policy"] == {"dimension_source": "annotation"}
    assert context["adjudicated_context"] == {"context_version": "v1"}
    assert context["part_semantics"] == {"part_type": "profile"}
    assert context["modeling_path_decision"] == {
        "modeling_path": "semantic_reconstruction"
    }
    assert "clarification_stage" not in base_context


def test_clarification_outlet_skips_path_payload_for_non_path_result():
    assert (
        ClarificationOutlet().path_payload(
            modeling_result={},
            base_context={"geometry_data": {}},
            policy_result={},
            adjudicated_context={},
            part_semantics={},
            modeling_path_decision={},
        )
        == {}
    )
