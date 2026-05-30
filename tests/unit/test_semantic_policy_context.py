# -*- coding: utf-8 -*-

from src.reconstruction.semantic_policy import (
    build_adjudicated_context,
    default_feature_constraints,
)


def test_default_feature_constraints_keep_semantic_safety_rules():
    constraints = default_feature_constraints()

    assert constraints["hidden_lines_alone_are_insufficient"] is True
    assert constraints["concentric_projection_alone_is_insufficient"] is True
    assert constraints["chamfer_is_external_corner_removal"] is True
    assert constraints["chamfer_must_not_create_recess_or_slot"] is True


def test_adjudicated_context_hides_raw_geometry_when_annotation_dimensions_exist():
    context = build_adjudicated_context(
        {
            "source_entities": [{"type": "LINE"}],
            "view_analysis": {"views": [{"name": "main", "entities": [{"type": "LINE"}]}]},
        },
        dimension_source="annotation",
        dimension_bindings=[],
        dimension_plan={},
        feature_constraints=default_feature_constraints(),
        assumptions=["存在可用尺寸标注"],
        drawing_evidence_package={"package_version": "drawing_evidence_package_v1"},
    )

    assert context["context_version"] == "adjudicated_context_v1"
    assert "source_entities" not in context
    assert "entities" not in context["view_analysis"]["views"][0]
    assert context["semantic_policy"]["dimension_source"] == "annotation"


def test_adjudicated_context_keeps_geometry_without_annotation_dimensions():
    context = build_adjudicated_context(
        {
            "source_entities": [{"type": "LINE"}],
            "view_analysis": {"views": [{"name": "main", "entities": [{"type": "LINE"}]}]},
        },
        dimension_source="geometry",
        dimension_bindings=[],
        dimension_plan={},
        feature_constraints=default_feature_constraints(),
        assumptions=["未发现可用尺寸标注"],
        drawing_evidence_package={},
    )

    assert "source_entities" in context
    assert "entities" in context["view_analysis"]["views"][0]


def test_adjudicated_context_carries_user_modeling_hint():
    context = build_adjudicated_context(
        {"view_analysis": {"views": []}},
        dimension_source="geometry",
        dimension_bindings=[],
        dimension_plan={},
        feature_constraints=default_feature_constraints(),
        assumptions=[],
        drawing_evidence_package={},
        user_modeling_hint="优先生成主体。",
        user_modeling_hint_policy="drawing_facts_override_user_hint",
    )

    assert context["user_modeling_hint"] == "优先生成主体。"
    assert (
        context["semantic_policy"]["user_modeling_hint_policy"]
        == "drawing_facts_override_user_hint"
    )
