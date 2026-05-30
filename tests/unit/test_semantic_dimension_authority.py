# -*- coding: utf-8 -*-

from src.reconstruction.semantic_dimension_authority import SemanticDimensionAuthority


def test_authority_uses_successful_adjudication_over_legacy_plan():
    authority = SemanticDimensionAuthority({
        "dimensions": [{"text": "16", "value": 16.0}, {"text": "99", "value": 99.0}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_plan": {
                "allowed_dimensions": [
                    {"text": "99", "value": 99.0, "role": "extrusion_depth"}
                ],
            },
            "drawing_evidence_package": {
                "dimension_candidates": [{"id": "D1", "text": "16", "value": 16.0}],
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
    })

    assert authority.allowed_values == [16.0]
    assert authority.construction_values == []
    assert authority.unauthorized_key_values({
        "key_dimensions": [{"name": "extrusion_depth", "value": 99.0}]
    }) == [99.0]


def test_authority_falls_back_to_legacy_plan_when_adjudication_missing():
    authority = SemanticDimensionAuthority({
        "dimensions": [{"text": "9", "value": 9.0}, {"text": "39", "value": 39.0}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "dimension_plan": {
                "allowed_dimensions": [
                    {"text": "9+39", "value": 48.0, "role": "profile_length"}
                ],
                "construction_dimensions": [
                    {"text": "9", "value": 9.0, "role": "profile_length_segment"}
                ],
            },
        },
    })

    assert authority.allowed_values == [48.0]
    assert authority.construction_values == [9.0]
    assert authority.unexpected_annotation_key_values({
        "key_dimensions": [{"name": "profile_length", "value": 48.0}]
    }) == []


def test_authority_flags_misnamed_construction_dimensions():
    authority = SemanticDimensionAuthority({
        "semantic_policy": {
            "dimension_plan": {
                "allowed_dimensions": [],
                "construction_dimensions": [
                    {"text": "9", "value": 9.0, "role": "profile_length_segment"}
                ],
            },
        },
    })

    assert authority.misnamed_construction_key_dimensions({
        "key_dimensions": [{"name": "total_length", "value": 9.0}]
    }) == ["total_length=9"]


def test_authority_uses_raw_annotation_values_only_without_authoritative_plan():
    authority = SemanticDimensionAuthority({
        "dimensions": [{"text": "30", "value": 30.0}],
        "semantic_policy": {"dimension_source": "annotation"},
    })

    assert not authority.has_authoritative_values
    assert authority.unexpected_annotation_key_values({
        "key_dimensions": [
            {"name": "annotated_length", "value": 30.0},
            {"name": "measured_length", "value": 48.5},
        ]
    }) == [48.5]
