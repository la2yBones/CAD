# -*- coding: utf-8 -*-

from src.reconstruction.modeling_instruction_postprocessor import (
    ModelingInstructionPostprocessor,
)


def test_postprocessor_removes_unauthorized_key_dimensions():
    result = {
        "key_dimensions": [
            {"name": "extrusion_depth", "value": 16.0},
            {"name": "guessed_height", "value": 99.0},
        ],
        "warnings": [],
    }
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

    normalized = ModelingInstructionPostprocessor().normalize(result, context)

    assert normalized["key_dimensions"] == [{"name": "extrusion_depth", "value": 16.0}]
    assert "guessed_height" not in repr(normalized)
    assert "已拦截 1 个未获语义裁决许可" in normalized["warnings"][0]


def test_postprocessor_chineseizes_user_visible_metadata():
    result = {
        "warnings": ["Missing boss height; model may be incomplete."],
        "instructions": ["Create base body from annotation dimensions."],
        "skipped_features": [
            {
                "name": "boss",
                "kind": "boss",
                "reason": "Height dimension missing.",
                "risk": "Model is incomplete if boss exists.",
            }
        ],
    }

    normalized = ModelingInstructionPostprocessor().normalize(result)

    assert "非中文说明" in normalized["warnings"][0]
    assert "非中文说明" in normalized["instructions"][0]
    assert "非中文说明" in normalized["skipped_features"][0]["reason"]
    assert "Height dimension" not in repr(normalized)


def test_postprocessor_injects_circle_hole_script_repair():
    result = {
        "freecad_script": "\n".join([
            "import FreeCAD",
            "import Part",
            "doc = FreeCAD.newDocument('GeneratedModel')",
            "body = Part.makeBox(90, 60, 16, FreeCAD.Vector(-45, -30, 0))",
            "Part.show(body, 'GeneratedBody')",
            "doc.recompute()",
        ]),
        "skipped_features": [
            {
                "name": "2x直径8通孔",
                "kind": "hole",
                "reason": "缺少孔位坐标",
                "risk": "无法确定位置",
            }
        ],
        "warnings": [],
    }
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

    normalized = ModelingInstructionPostprocessor().normalize(result, context)

    assert "CAD_SYSTEM_CIRCLE_HOLE_REPAIR" in normalized["freecad_script"]
    assert "'center': [-34.0, 0.0]" in normalized["freecad_script"]
    assert "'radius': 4.0" in normalized["freecad_script"]
    assert "Part.show" in normalized["freecad_script"].split("CAD_SYSTEM_CIRCLE_HOLE_REPAIR", 1)[1]
    assert normalized["skipped_features"] == []
    assert "补充 1 个贯穿孔切除" in normalized["warnings"][0]


def test_postprocessor_keeps_only_inner_concentric_circle_for_hole_repair():
    result = {
        "freecad_script": "\n".join([
            "import FreeCAD",
            "import Part",
            "doc = FreeCAD.newDocument('GeneratedModel')",
            "body = Part.makeCylinder(32, 96)",
            "Part.show(body, 'GeneratedBody')",
            "doc.recompute()",
        ]),
        "warnings": [],
    }
    context = {
        "source_entities": [
            {"type": "CIRCLE", "layer": "轮廓线", "center": [0.0, 0.0, 0.0], "radius": 16.0},
            {"type": "CIRCLE", "layer": "轮廓线", "center": [0.0, 0.0, 0.0], "radius": 32.0},
        ],
        "semantic_policy": {
            "drawing_evidence_package": {
                "view_candidates": [
                    {
                        "id": "V1",
                        "centroid": [0.0, 0.0],
                        "entity_count": 10,
                        "entity_type_count": {"CIRCLE": 2},
                    }
                ],
                "geometry_candidates": [
                    {
                        "id": "G_inner",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 16.0,
                    },
                    {
                        "id": "G_outer",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 32.0,
                    },
                ],
            },
        },
    }

    normalized = ModelingInstructionPostprocessor().normalize(result, context)

    assert "'radius': 16.0" in normalized["freecad_script"]
    assert "'radius': 32.0" not in normalized["freecad_script"]
    assert "补充 1 个贯穿孔切除" in normalized["warnings"][0]


def test_postprocessor_skips_circle_repair_for_semantic_revolve_task():
    result = {
        "freecad_script": "\n".join([
            "import FreeCAD",
            "import Part",
            "doc = FreeCAD.newDocument('GeneratedModel')",
            "body = Part.makeCylinder(32, 96)",
            "Part.show(body, 'GeneratedBody')",
            "doc.recompute()",
        ]),
        "warnings": [],
    }
    context = {
        "semantic_policy": {
            "drawing_evidence_package": {
                "view_candidates": [{"id": "V1", "centroid": [0.0, 0.0], "entity_type_count": {"CIRCLE": 2}}],
                "geometry_candidates": [
                    {
                        "id": "G_inner",
                        "candidate_kind": "circle",
                        "source_entity_type": "CIRCLE",
                        "source_view_candidate_id": "V1",
                        "center": [0.0, 0.0, 0.0],
                        "radius": 16.0,
                    }
                ],
            },
        },
    }
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "modeling_operations": [
            {
                "operation": "revolve_profile",
                "dimensions": {"outer_diameter": 64, "length": 96},
            },
            {
                "operation": "subtract_feature",
                "dimensions": {"diameter": 32},
            },
        ],
        "features": {"subtractive": [{"kind": "through_hole", "dimensions": {"diameter": 32}}]},
    }

    normalized = ModelingInstructionPostprocessor().normalize(
        result,
        context,
        modeling_task_payload=payload,
    )

    assert "CAD_SYSTEM_CIRCLE_HOLE_REPAIR" not in normalized["freecad_script"]
    assert normalized["warnings"] == []
