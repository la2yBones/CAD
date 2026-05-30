# -*- coding: utf-8 -*-

from src.reconstruction.modeling_task import ModelingTaskBuilder


def test_modeling_task_payload_excludes_raw_context_and_entities():
    payload = ModelingTaskBuilder().build(
        part_semantics={
            "part_type": "bolt",
            "confidence": 0.91,
            "summary": "六角头螺栓",
            "base_features": [{"name": "hex_head"}],
            "key_dimensions": [{"name": "radius", "value": 15.0}],
            "path_clarification_fallback": {"missing_fields": ["radius_surface"]},
            "uncertainties": ["R15位置需保守处理"],
        },
        reconstruction_context={
            "source_entities": [{"type": "LINE"}],
            "local_geometry": {"entity_pairs": [{"a": 1, "b": 2}]},
            "view_analysis": {"views": [{"entities": [{"type": "CIRCLE"}]}]},
            "user_modeling_hint": "主体先生成，细节可以跳过。",
            "semantic_policy": {
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
                    "construction_dimensions": [
                        {
                            "text": "R15",
                            "value": 15.0,
                            "role": "radius",
                            "dimension_kind": "feature_size",
                        }
                    ],
                    "unresolved_dimensions": [
                        {"text": "24", "value": 24.0, "role": "unresolved_linear"}
                    ],
                },
            },
        },
        modeling_path_decision={
            "modeling_path": "semantic_reconstruction",
            "reason": "无专用路径满足当前契约",
        },
    )

    assert set(payload) == {
        "task_version",
        "object",
        "features",
        "modeling_operations",
        "dimensions",
        "constraints",
        "recovery_hints",
        "readiness",
    }
    payload_text = repr(payload)
    assert "source_entities" not in payload_text
    assert "entity_pairs" not in payload_text
    assert "'entities'" not in payload_text
    assert payload["object"]["part_type"] == "bolt"
    assert "dimension_roles" not in payload["dimensions"]["semantic_adjudication"]
    assert payload["dimensions"]["modeling_dimensions"][0]["dimension_id"] == "D1"
    assert payload["dimensions"]["modeling_dimensions"][0]["value"] == 15.0
    assert payload["dimensions"]["dimensions_policy"] == (
        "modeling_dimensions is the single source of truth for all "
        "dimension values; dimension_roles and derived_dimensions have "
        "been merged into modeling_dimensions with resolved values"
    )
    assert "construction_dimensions" not in payload["dimensions"]
    assert "unresolved_dimensions" not in payload["dimensions"]
    assert "key_dimensions" not in payload["features"]
    assert payload["recovery_hints"]["user_modeling_hint"] == "主体先生成，细节可以跳过。"
    assert "warnings and uncertainties explain risk only" in payload["recovery_hints"]["warning_policy"]
    assert payload["readiness"]["ready"] is True


def test_modeling_task_payload_keeps_legacy_dimension_plan_when_adjudication_failed():
    payload = ModelingTaskBuilder().build(
        part_semantics={"part_type": "bolt", "dimension_source": "annotation"},
        reconstruction_context={
            "semantic_policy": {
                "dimension_source": "annotation",
                "semantic_adjudication": {"status": "failed", "warnings": ["调用失败"]},
                "dimension_plan": {
                    "construction_dimensions": [
                        {
                            "text": "R15",
                            "value": 15.0,
                            "role": "radius",
                            "dimension_kind": "feature_size",
                        }
                    ],
                    "unresolved_dimensions": [
                        {"text": "24", "value": 24.0, "role": "unresolved_linear"}
                    ],
                    "candidate_dimensions": [
                        {
                            "text": "9+39",
                            "value": 48.0,
                            "role": "profile_length",
                            "binding_status": "candidate",
                        }
                    ],
                },
            },
        },
    )

    assert payload["dimensions"]["semantic_adjudication"]["status"] == "failed"
    assert "modeling_dimensions" not in payload["dimensions"]
    assert payload["dimensions"]["construction_dimensions"][0]["text"] == "R15"
    assert payload["dimensions"]["unresolved_dimensions"][0]["text"] == "24"
    assert payload["dimensions"]["candidate_dimensions"][0]["text"] == "9+39"


def test_modeling_task_payload_postprocesses_semantics_before_feature_export():
    payload = ModelingTaskBuilder().build(
        part_semantics={
            "part_type": "plate",
            "dimension_source": "annotation",
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "key_dimensions": [
                {"name": "extrusion_depth", "value": 16.0},
                {"name": "guessed_height", "value": 99.0},
            ],
            "warnings": ["Extrusion depth missing; a default may be assumed."],
        },
        reconstruction_context={
            "dimensions": [
                {"text": "16", "value": 16.0},
                {"text": "99", "value": 99.0},
            ],
            "semantic_policy": {
                "dimension_source": "annotation",
                "drawing_evidence_package": {
                    "dimension_candidates": [
                        {"id": "D1", "text": "16", "value": 16.0}
                    ],
                    "derived_dimension_candidates": [],
                },
                "semantic_adjudication": {
                    "status": "completed",
                    "dimension_roles": [
                        {"dimension_id": "D1", "role": "extrusion_depth"}
                    ],
                    "derived_dimensions": [],
                },
            },
        },
    )

    assert "key_dimensions" not in payload["features"]
    assert "guessed_height" not in repr(payload)
    assert "非中文风险说明" in payload["recovery_hints"]["warnings"][0]
    assert payload["dimensions"]["modeling_dimensions"][0]["value"] == 16.0
