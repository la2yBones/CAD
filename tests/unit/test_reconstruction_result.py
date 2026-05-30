# -*- coding: utf-8 -*-

from src.reconstruction.reconstruction_result import ReconstructionResultBuilder


def test_reconstruction_result_builder_keeps_completed_result_shape():
    result = ReconstructionResultBuilder().build(
        reconstruction_context={"context_version": "reconstruction_context_v1"},
        policy_result={"dimension_source": "annotation"},
        adjudicated_context={"context_version": "adjudicated_context_v1"},
        part_semantics={"part_type": "block"},
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
        modeling_result={"freecad_script": "pass"},
        base_clarification_context={"geometry_data": {"entities": []}},
    )

    assert result == {
        "reconstruction_context": {"context_version": "reconstruction_context_v1"},
        "semantic_policy": {"dimension_source": "annotation"},
        "adjudicated_context": {"context_version": "adjudicated_context_v1"},
        "part_semantics": {"part_type": "block"},
        "modeling_path_decision": {"modeling_path": "semantic_reconstruction"},
        "modeling_instructions": {"freecad_script": "pass"},
    }


def test_reconstruction_result_builder_attaches_path_clarification_context():
    result = ReconstructionResultBuilder().build(
        reconstruction_context={"context_version": "reconstruction_context_v1"},
        policy_result={"dimension_source": "geometry"},
        adjudicated_context={"context_version": "adjudicated_context_v1"},
        part_semantics={"part_type": "profile"},
        modeling_path_decision={
            "modeling_path": "semantic_reconstruction",
            "blocked_by_path_contract": True,
        },
        modeling_result={
            "blocked_by_path_contract": True,
            "clarification_questions": [{"id": "provide_extrusion_depth"}],
        },
        base_clarification_context={
            "geometry_data": {"entities": []},
            "clarification_stage": "semantic_policy",
        },
    )

    context = result["clarification_context"]
    assert context["clarification_stage"] == "modeling_path"
    assert context["semantic_policy"] == {"dimension_source": "geometry"}
    assert context["adjudicated_context"] == {
        "context_version": "adjudicated_context_v1"
    }
    assert context["part_semantics"] == {"part_type": "profile"}
    assert context["modeling_path_decision"] == {
        "modeling_path": "semantic_reconstruction",
        "blocked_by_path_contract": True,
    }
