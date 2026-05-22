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
                "allowed_dimensions": [
                    {
                        "text": "R=4x1.5",
                        "value": 1.5,
                        "role": "radius",
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
