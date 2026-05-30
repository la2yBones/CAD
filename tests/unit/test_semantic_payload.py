# -*- coding: utf-8 -*-

from src.reconstruction.semantic_payload import SemanticUnderstandingPayloadBuilder


def test_semantic_understanding_payload_excludes_raw_entities_but_keeps_evidence():
    payload = SemanticUnderstandingPayloadBuilder().build({
        "drawing": {
            "entity_count": 3,
            "entity_type_count": {"LINE": 1, "CIRCLE": 1, "LWPOLYLINE": 1},
        },
        "source_entities": [
            {"type": "LINE", "start": [0, 0], "end": [10, 0], "layer": "0"},
            {"type": "CIRCLE", "center": [5, 5], "radius": 2.5},
            {
                "type": "LWPOLYLINE",
                "vertices": [[0, 0], [10, 0], [10, 5], [0, 5]],
                "closed": True,
            },
        ],
        "view_analysis": {
            "drawing_type": "single_view",
            "views": [
                {
                    "name": "main",
                    "bbox": [0, 0, 10, 5],
                    "entity_count": 3,
                    "entity_type_count": {"LINE": 1, "CIRCLE": 1},
                    "entities": [{"type": "LINE", "start": [0, 0], "end": [1, 1]}],
                }
            ],
        },
        "dimensions": [{"text": "10", "value": 10.0, "type": "线性"}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_plan": {
                "allowed_dimensions": [{"text": "10", "value": 10.0, "role": "profile_length"}]
            },
        },
    })

    assert "semantic_policy" in payload
    assert payload["geometry_evidence"]["line_summary"]["count"] == 1
    assert payload["geometry_evidence"]["circle_summary"]["radius_values"] == [2.5]
    assert payload["geometry_evidence"]["polyline_summary"]["closed_count"] == 1
    payload_text = repr(payload)
    assert "source_entities" not in payload_text
    assert "'entities'" not in payload_text
    assert "'start'" not in payload_text
    assert "'end'" not in payload_text
    assert "'center'" not in payload_text


def test_semantic_understanding_payload_uses_preserved_geometry_summary_without_raw_entities():
    payload = SemanticUnderstandingPayloadBuilder().build({
        "drawing": {
            "entity_count": 4,
            "entity_type_count": {"ARC": 4},
        },
        "geometry_summary": {
            "line_summary": {
                "count": 0,
                "orientation_count": {"horizontal": 0, "vertical": 0, "diagonal": 0},
                "length_range": [],
            },
            "circle_summary": {"count": 0, "radius_values": [], "radius_range": []},
            "arc_summary": {"count": 4, "radius_values": [1.5], "radius_range": [1.5, 1.5]},
            "polyline_summary": {"count": 0, "closed_count": 0, "vertex_counts": []},
        },
        "dimensions": [
            {
                "text": "3xφ5",
                "value": 5.0,
                "type": "直径",
                "callout": "repeated_diameter",
                "repeat_count": 3,
                "diameter_value": 5.0,
            }
        ],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_plan": {
                "construction_dimensions": [
                    {
                        "text": "R=4x1.5",
                        "value": 1.5,
                        "role": "radius",
                        "dimension_kind": "feature_count_size",
                        "repeat_count": 4,
                        "radius_value": 1.5,
                        "callout": "repeated_radius",
                    }
                ]
            },
        },
    })

    assert payload["geometry_evidence"]["arc_summary"]["count"] == 4
    assert payload["geometry_evidence"]["arc_summary"]["radius_values"] == [1.5]
    dimension = payload["dimension_evidence"]["dimensions"][0]
    assert dimension["value"] == 5.0
    assert dimension["repeat_count"] == 3
    assert dimension["diameter_value"] == 5.0


def test_semantic_understanding_payload_prefers_semantic_adjudication_over_legacy_bindings():
    payload = SemanticUnderstandingPayloadBuilder().build({
        "dimensions": [{"text": "16", "value": 16.0, "type": "线性"}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_bindings": [
                {
                    "text": "16",
                    "value": 16.0,
                    "semantic_role": "profile_length",
                }
            ],
            "dimension_plan": {
                "allowed_dimensions": [
                    {"text": "16", "value": 16.0, "role": "profile_length"}
                ]
            },
            "semantic_adjudication": {
                "dimension_roles": [
                    {
                        "dimension_id": "D1",
                        "role": "extrusion_depth",
                        "evidence_ids": ["D1"],
                    }
                ],
                "view_roles": [],
                "feature_roles": [],
                "derived_dimensions": [],
                "clarification_questions": [],
                "uncertainties": [],
                "warnings": [],
            },
        },
    })

    assert payload["dimension_evidence"]["semantic_adjudication"]["dimension_roles"][0]["role"] == "extrusion_depth"
    assert "dimensions" not in payload["dimension_evidence"]
    assert "raw dimensions omitted" in payload["dimension_evidence"]["dimensions_policy"]
    assert "dimension_bindings" not in payload["dimension_evidence"]
    assert "dimension_plan" not in payload["dimension_evidence"]
    assert "dimension_bindings" not in payload["semantic_policy"]
    assert "dimension_plan" not in payload["semantic_policy"]
    assert "profile_length" not in repr(payload)


def test_semantic_understanding_payload_keeps_circle_hole_evidence_after_adjudication():
    payload = SemanticUnderstandingPayloadBuilder().build({
        "drawing": {"entity_count": 1, "entity_type_count": {"CIRCLE": 1}},
        "source_entities": [
            {"type": "CIRCLE", "center": [0, 0], "radius": 42.0},
        ],
        "semantic_policy": {
            "dimension_source": "annotation",
            "drawing_evidence_package": {
                "package_version": "drawing_evidence_package_v1",
                "dimension_candidates": [
                    {"id": "D1", "text": "21", "value": 21.0}
                ],
                "geometry_candidates": [
                    {
                        "id": "G1",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 42.0,
                        "bbox": [-42.0, -42.0, 42.0, 42.0],
                    }
                ],
            },
            "semantic_adjudication": {
                "dimension_roles": [
                    {
                        "dimension_id": "D1",
                        "role": "extrusion_depth",
                        "evidence_ids": ["D1"],
                    }
                ],
                "view_roles": [],
                "feature_roles": [],
                "derived_dimensions": [],
                "clarification_questions": [],
                "uncertainties": [],
                "warnings": [],
            },
        },
    })

    assert "radius_values" not in payload["geometry_evidence"]["circle_summary"]
    assert "radius_range" not in payload["geometry_evidence"]["circle_summary"]
    circle = payload["drawing_evidence_package"]["geometry_candidates"][0]
    assert circle["center"] == [0.0, 0.0, 0.0]
    assert circle["radius"] == 42.0
    assert circle["bbox"] == [-42.0, -42.0, 42.0, 42.0]
    policy = payload["drawing_evidence_package"]["measurement_policy"]
    assert "executable shape evidence" in policy
    assert "key dimensions" in policy


def test_semantic_understanding_payload_keeps_legacy_bindings_when_adjudication_failed():
    payload = SemanticUnderstandingPayloadBuilder().build({
        "dimensions": [{"text": "16", "value": 16.0, "type": "线性"}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_bindings": [
                {
                    "text": "16",
                    "value": 16.0,
                    "semantic_role": "profile_length",
                }
            ],
            "dimension_plan": {
                "allowed_dimensions": [
                    {"text": "16", "value": 16.0, "role": "profile_length"}
                ]
            },
            "semantic_adjudication": {
                "status": "failed",
                "dimension_roles": [],
                "warnings": ["连接失败"],
            },
        },
    })

    assert payload["dimension_evidence"]["dimension_bindings"][0]["semantic_role"] == "profile_length"
    assert payload["dimension_evidence"]["dimension_plan"]["allowed_dimensions"][0]["role"] == "profile_length"
    assert payload["semantic_policy"]["semantic_adjudication"]["status"] == "failed"
