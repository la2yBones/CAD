# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.reconstruction.modeling_task import ModelingTaskOutlet


def test_modeling_task_outlet_builds_payload_without_raw_context():
    payload = ModelingTaskOutlet().build_payload(
        part_semantics={
            "part_type": "plate",
            "confidence": 0.9,
            "summary": "base plate",
            "base_features": [{"kind": "plate"}],
            "key_dimensions": [{"name": "unsafe", "value": 99.0}],
        },
        adjudicated_context={
            "source_entities": [{"type": "LINE"}],
            "semantic_policy": {
                "dimension_source": "annotation",
                "semantic_adjudication": {
                    "status": "completed",
                    "dimension_roles": [],
                    "derived_dimensions": [],
                },
            },
        },
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
    )

    payload_text = repr(payload)
    assert "source_entities" not in payload_text
    assert "key_dimensions" not in payload["features"]
    assert payload["object"]["selected_modeling_path"] == "semantic_reconstruction"


def test_modeling_task_outlet_passes_payload_to_instruction_generator():
    calls = []

    def generate(*args, **kwargs):
        calls.append((args, kwargs))
        return {"freecad_script": "pass"}

    result = ModelingTaskOutlet().generate_instructions(
        instruction_generator=SimpleNamespace(generate=generate),
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
        part_semantics={
            "part_type": "plate",
            "confidence": 0.9,
            "base_features": [{"kind": "plate"}],
        },
        geometry_data={"entities": []},
        view_analysis={"views": []},
        dimension_data={"dimensions": []},
        extrude_height=10.0,
        adjudicated_context={"semantic_policy": {"dimension_source": "geometry"}},
        file_path="plate.dxf",
    )

    assert result["freecad_script"] == "pass"
    assert result["_modeling_task_payload"]["task_version"] == "modeling_task_v1"
    kwargs = calls[0][1]
    assert kwargs["file_path"] == "plate.dxf"
    assert kwargs["modeling_task_payload"]["task_version"] == "modeling_task_v1"
    assert kwargs["modeling_task_payload"]["object"]["part_type"] == "plate"
    assert kwargs["modeling_task_payload"]["readiness"]["ready"] is True


def test_modeling_task_outlet_blocks_instruction_generation_when_task_not_ready():
    calls = []

    def generate(*args, **kwargs):
        calls.append((args, kwargs))
        return {"freecad_script": "pass"}

    result = ModelingTaskOutlet().generate_instructions(
        instruction_generator=SimpleNamespace(generate=generate),
        modeling_path_decision={"modeling_path": "semantic_reconstruction"},
        part_semantics={"part_type": "unknown", "confidence": 0.9},
        geometry_data={"entities": []},
        view_analysis={"views": []},
        dimension_data={"dimensions": []},
        extrude_height=10.0,
        adjudicated_context={"semantic_policy": {"dimension_source": "geometry"}},
        file_path="unknown.dxf",
    )

    assert calls == []
    assert result["freecad_script"] == ""
    assert result["blocked_by_task_readiness"] is True
    assert "body_source" in result["task_readiness"]["missing"]
