#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for standardized view analysis validation."""

from src.intelligent_analyzer.view_schema import (
    ViewAnalysisValidator,
    build_standard_view_analysis,
)
from src.intelligent_analyzer.view_analyzer import EngineeringViewAnalyzer


def test_standard_view_analysis_passes_validator():
    rule_result = {
        "detection_method": "filename_two_view_split",
        "views": [
            {"name": "main", "type": "主视图", "bbox": [0, 0, 100, 50], "entity_count": 10},
            {"name": "top", "type": "俯视图", "bbox": [0, 60, 100, 90], "entity_count": 8},
        ],
        "relationships": [
            {"type": "projection", "views": ["main", "top"], "description": "主视图与俯视图长对正"}
        ],
    }

    result = build_standard_view_analysis(
        rule_result,
        drawing_type="two_view",
        confidence=0.82,
    )

    valid, errors = ViewAnalysisValidator().validate(result)

    assert valid, errors


def test_validator_rejects_low_confidence():
    result = {
        "analysis_id": "view_test",
        "timestamp": "2026-05-13T00:00:00+00:00",
        "drawing_type": "two_view",
        "views": [
            {
                "object_id": "view_1",
                "name": "main",
                "label": "主视图",
                "bbox": [0, 0, 10, 10],
                "confidence": 0.9,
            },
            {
                "object_id": "view_2",
                "name": "top",
                "label": "俯视图",
                "bbox": [0, 20, 10, 30],
                "confidence": 0.9,
            },
        ],
        "relationships": [],
        "confidence": 0.2,
        "evidence": [],
        "reason_summary": "低置信度示例",
        "warnings": [],
    }

    valid, errors = ViewAnalysisValidator(confidence_threshold=0.6).validate(result)

    assert not valid
    assert any("confidence" in error for error in errors)


def test_view_bbox_uses_outline_entities_not_cross_view_centerlines():
    analyzer = EngineeringViewAnalyzer({})
    entities = [
        {
            "type": "LINE",
            "layer": "点划线",
            "start": [50.0, -100.0, 0.0],
            "end": [50.0, 200.0, 0.0],
        },
        {
            "type": "CIRCLE",
            "layer": "轮廓线",
            "center": [50.0, 0.0, 0.0],
            "radius": 30.0,
        },
        {
            "type": "LWPOLYLINE",
            "layer": "轮廓线",
            "vertices": [
                [10.0, -20.0],
                [90.0, -20.0],
                [90.0, 20.0],
                [10.0, 20.0],
            ],
            "closed": True,
        },
    ]

    assert analyzer._compute_view_bbox(entities) == (10.0, -30.0, 90.0, 30.0)
