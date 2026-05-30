# -*- coding: utf-8 -*-

from src.reconstruction.semantic_postprocessor import PartSemanticsPostprocessor


def _minimal_semantics(**overrides):
    result = {
        "part_type": "plate",
        "confidence": 0.9,
        "summary": "",
        "evidence": [],
        "candidate_interpretations": [],
        "coordinate_system": {},
        "dimension_source": "annotation",
        "base_features": [],
        "additive_features": [],
        "subtractive_features": [],
        "planar_modeling_semantics": {
            "profile": None,
            "extrusion_direction": "unknown",
            "extrusion_depth": None,
            "cut_features": [],
            "dimension_bindings": [],
            "uncertainties": [],
        },
        "revolve_modeling_semantics": None,
        "preferred_modeling_path": None,
        "key_dimensions": [],
        "uncertainties": [],
        "warnings": [],
    }
    result.update(overrides)
    return result


def test_postprocessor_removes_key_dimensions_outside_semantic_authority():
    result = _minimal_semantics(
        key_dimensions=[
            {"name": "extrusion_depth", "value": 16.0},
            {"name": "guessed_height", "value": 99.0},
        ],
    )
    context = {
        "dimensions": [{"text": "16", "value": 16.0}, {"text": "99", "value": 99.0}],
        "semantic_policy": {
            "dimension_source": "annotation",
            "drawing_evidence_package": {
                "dimension_candidates": [{"id": "D1", "text": "16", "value": 16.0}],
                "derived_dimension_candidates": [],
            },
            "semantic_adjudication": {
                "status": "completed",
                "dimension_roles": [{"dimension_id": "D1", "role": "extrusion_depth"}],
                "derived_dimensions": [],
            },
        },
    }

    normalized = PartSemanticsPostprocessor().normalize(result, context)

    assert normalized["key_dimensions"] == [{"name": "extrusion_depth", "value": 16.0}]
    assert "已移除 1 个未获语义裁决许可的关键尺寸" in normalized["uncertainties"][-1]
    assert "guessed_height" not in repr(normalized)
    assert "未授权关键尺寸" in normalized["warnings"][-1]


def test_postprocessor_replaces_english_user_visible_warnings():
    normalized = PartSemanticsPostprocessor().normalize(
        _minimal_semantics(
            warnings=["Extrusion depth missing; a default may be assumed."],
            uncertainties=["Missing boss height dimension."],
        )
    )

    assert "非中文风险说明" in normalized["warnings"][0]
    assert "非中文风险说明" in normalized["uncertainties"][0]
    assert "Extrusion depth" not in repr(normalized)


def test_postprocessor_keeps_chinese_user_visible_warnings():
    normalized = PartSemanticsPostprocessor().normalize(
        _minimal_semantics(warnings=["凸台高度未确认，需用户补充。"])
    )

    assert normalized["warnings"] == ["凸台高度未确认，需用户补充。"]


def test_postprocessor_normalizes_incomplete_revolve_semantics():
    normalized = PartSemanticsPostprocessor().normalize({
        "preferred_modeling_path": "revolve_base_then_add_hex_head",
        "revolve_modeling_semantics": {
            "profile": "由直线和圆弧组成的半轮廓",
            "axis": "中心线",
            "angle": 360.0,
        },
        "uncertainties": [],
    })

    assert normalized["revolve_modeling_semantics"] is None
    assert normalized["preferred_modeling_path"] == "semantic_reconstruction"
    assert "回转语义缺少精确轴线" in normalized["uncertainties"][0]


def test_postprocessor_injects_outline_circle_cut_features():
    result = _minimal_semantics()
    context = {
        "source_entities": [
            {"type": "CIRCLE", "layer": "轮廓线", "center": [84.0, 100.0, 0.0], "radius": 4.0},
            {"type": "CIRCLE", "layer": "点划线", "center": [118.0, 100.0, 0.0], "radius": 24.0},
        ],
        "semantic_policy": {
            "drawing_evidence_package": {
                "view_candidates": [
                    {
                        "id": "V1",
                        "centroid": [118.0, 100.0],
                        "entity_count": 10,
                        "entity_type_count": {"CIRCLE": 2},
                    }
                ],
                "geometry_candidates": [
                    {
                        "id": "G1",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [84.0, 100.0, 0.0],
                        "radius": 4.0,
                    },
                    {
                        "id": "G2",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [118.0, 100.0, 0.0],
                        "radius": 24.0,
                    },
                ],
            },
        },
    }

    normalized = PartSemanticsPostprocessor().normalize(result, context)

    cuts = normalized["planar_modeling_semantics"]["cut_features"]
    assert len(cuts) == 1
    assert cuts[0]["kind"] == "through_hole"
    assert cuts[0]["radius"] == 4.0
    assert cuts[0]["diameter"] == 8.0
    assert cuts[0]["center_relative_to_profile"] == [-34.0, 0.0]
    assert "补全 1 个可定位圆孔" in normalized["warnings"][-1]


def test_postprocessor_keeps_inner_circle_for_concentric_outline_and_hole():
    result = _minimal_semantics()
    context = {
        "source_entities": [
            {"type": "CIRCLE", "layer": "轮廓线", "center": [0.0, 0.0, 0.0], "radius": 32.0},
            {"type": "CIRCLE", "layer": "轮廓线", "center": [0.0, 0.0, 0.0], "radius": 16.0},
        ],
        "semantic_policy": {
            "drawing_evidence_package": {
                "view_candidates": [
                    {
                        "id": "V1",
                        "centroid": [0.0, 0.0],
                        "entity_count": 2,
                        "entity_type_count": {"CIRCLE": 2},
                    }
                ],
                "geometry_candidates": [
                    {
                        "id": "G_outer",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 32.0,
                    },
                    {
                        "id": "G_inner",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 16.0,
                    },
                ],
            },
        },
    }

    normalized = PartSemanticsPostprocessor().normalize(result, context)

    cuts = normalized["planar_modeling_semantics"]["cut_features"]
    assert len(cuts) == 1
    assert cuts[0]["diameter"] == 32.0
    assert "G_inner" in cuts[0]["evidence"]
    assert "G_outer" not in repr(cuts)
    assert "补全 1 个可定位圆孔" in normalized["warnings"][-1]
