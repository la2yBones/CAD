# -*- coding: utf-8 -*-

from src.reconstruction.semantic_policy import DimensionSourceDecider


def test_dimension_source_decider_uses_annotation_when_numeric_dimensions_exist():
    decision = DimensionSourceDecider().decide(
        {
            "dimensions": [
                {"text": "30", "value": 30.0, "type": "线性"},
                {"text": "备注", "value": None, "type": "文本"},
            ],
        }
    )

    assert decision.dimension_source == "annotation"
    assert decision.annotation_dimensions == [
        {"text": "30", "value": 30.0, "type": "线性"}
    ]
    assert decision.assumptions == [
        "存在可用尺寸标注，后续语义生成仅可使用标注尺寸；图形坐标仅保留形状提示。"
    ]


def test_dimension_source_decider_uses_geometry_without_numeric_dimensions():
    decision = DimensionSourceDecider().decide(
        {
            "dimensions": [
                {"text": "备注", "value": None, "type": "文本"},
            ],
        }
    )

    assert decision.dimension_source == "geometry"
    assert decision.annotation_dimensions == []
    assert decision.assumptions == [
        "未发现可用尺寸标注，后续语义生成只能依据图形几何做保守解释。"
    ]


def test_dimension_source_decider_treats_missing_dimensions_as_geometry():
    decision = DimensionSourceDecider().decide({})

    assert decision.dimension_source == "geometry"
    assert decision.annotation_dimensions == []
