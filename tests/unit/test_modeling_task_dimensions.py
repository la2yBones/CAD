# -*- coding: utf-8 -*-

from src.reconstruction.modeling_task import ModelingTaskDimensionsBuilder


def test_modeling_task_dimensions_use_adjudicated_modeling_dimensions_when_successful():
    payload = ModelingTaskDimensionsBuilder().build(
        semantics={"dimension_source": "annotation"},
        semantic_policy={
            "dimension_source": "annotation",
            "semantic_adjudication": {
                "dimension_roles": [
                    {
                        "dimension_id": "D1",
                        "role": "radius",
                        "evidence_ids": ["D1"],
                    }
                ]
            },
            "drawing_evidence_package": {
                "dimension_candidates": [
                    {"id": "D1", "text": "R15", "value": 15.0}
                ],
                "derived_dimension_candidates": [],
            },
            "dimension_plan": {
                "candidate_dimensions": [
                    {"text": "9+39", "value": 48.0, "role": "profile_length"}
                ],
            },
        },
    )

    assert payload["dimension_source"] == "annotation"
    assert payload["modeling_dimensions"][0]["dimension_id"] == "D1"
    assert payload["modeling_dimensions"][0]["value"] == 15.0
    assert "candidate_dimensions" not in payload


def test_modeling_task_dimensions_keep_permission_plan_when_adjudication_failed():
    payload = ModelingTaskDimensionsBuilder().build(
        semantics={"dimension_source": "annotation"},
        semantic_policy={
            "dimension_source": "annotation",
            "semantic_adjudication": {"status": "failed"},
            "dimension_plan": {
                "allowed_dimensions": [{"text": "90", "value": 90.0}],
                "construction_dimensions": [{"text": "R15", "value": 15.0}],
                "unresolved_dimensions": [{"text": "24", "value": 24.0}],
                "excluded_dimensions": [{"text": "40", "value": 40.0}],
                "candidate_dimensions": [{"text": "9+39", "value": 48.0}],
                "rules": ["candidate_dimensions 不是建模许可"],
            },
        },
    )

    assert payload["semantic_adjudication"]["status"] == "failed"
    assert "modeling_dimensions" not in payload
    assert payload["allowed_dimensions"][0]["text"] == "90"
    assert payload["construction_dimensions"][0]["text"] == "R15"
    assert payload["unresolved_dimensions"][0]["text"] == "24"
    assert payload["excluded_dimensions"][0]["text"] == "40"
    assert payload["candidate_dimensions"][0]["text"] == "9+39"
    assert payload["rules"] == ["candidate_dimensions 不是建模许可"]
