# -*- coding: utf-8 -*-

from src.reconstruction.dimension_permission_plan import DimensionPermissionPlan


def test_dimension_permission_plan_separates_permission_pools():
    plan = DimensionPermissionPlan.from_bindings([
        {
            "text": "90",
            "value": 90.0,
            "semantic_role": "profile_length",
            "confidence": 1.0,
        },
        {
            "text": "9+39",
            "value": 48.0,
            "semantic_role": "profile_length",
            "confidence": 0.7,
            "binding_status": "candidate",
            "source": "legacy_dimension_candidate",
        },
        {
            "text": "9",
            "value": 9.0,
            "semantic_role": "profile_length_segment",
            "confidence": 0.7,
        },
        {
            "text": "30",
            "value": 30.0,
            "semantic_role": "unresolved_linear",
            "confidence": 0.0,
        },
        {
            "text": "40",
            "value": 40.0,
            "semantic_role": "excluded_by_user",
            "confidence": 0.0,
        },
    ]).to_dict()

    assert [item["text"] for item in plan["allowed_dimensions"]] == ["90"]
    assert [item["text"] for item in plan["candidate_dimensions"]] == ["9+39"]
    assert [item["text"] for item in plan["construction_dimensions"]] == ["9"]
    assert [item["text"] for item in plan["unresolved_dimensions"]] == ["30"]
    assert [item["text"] for item in plan["excluded_dimensions"]] == ["40"]
    assert plan["allowed_dimensions"][0]["binding_status"] == "adjudicated"
    assert plan["candidate_dimensions"][0]["binding_status"] == "candidate"
    assert plan["unresolved_dimensions"][0]["binding_status"] == "unresolved"
    assert plan["excluded_dimensions"][0]["binding_status"] == "excluded"


def test_dimension_permission_plan_preserves_feature_metadata():
    plan = DimensionPermissionPlan.from_bindings([
        {
            "text": "3xφ5",
            "value": 5.0,
            "semantic_role": "diameter",
            "repeat_count": 3,
            "callout": "repeated_diameter",
        },
        {
            "text": "R=4x1.5",
            "value": 1.5,
            "semantic_role": "radius",
            "callout": "repeated_radius",
            "repeat_count": 4,
        },
    ]).to_dict()

    construction = {item["text"]: item for item in plan["construction_dimensions"]}
    assert construction["3xφ5"]["dimension_kind"] == "feature_count_size"
    assert construction["3xφ5"]["feature_kind"] == "diameter"
    assert construction["R=4x1.5"]["dimension_kind"] == "feature_count_size"
    assert construction["R=4x1.5"]["feature_kind"] == "radius"


def test_dimension_permission_plan_rules_explain_candidate_boundary():
    plan = DimensionPermissionPlan.from_bindings([]).to_dict()

    assert any("candidate_dimensions" in rule for rule in plan["rules"])
    assert any("allowed_dimensions" in rule for rule in plan["rules"])


def test_dimension_permission_plan_confirms_candidate_value():
    bindings = [
        {
            "text": "96",
            "value": 96.0,
            "semantic_role": "profile_length",
            "binding_status": "candidate",
            "confidence": 0.7,
        }
    ]

    DimensionPermissionPlan.bind_selected_value(
        bindings,
        role="profile_length",
        selected_value="96",
    )

    assert bindings[0]["semantic_role"] == "profile_length"
    assert bindings[0]["binding_status"] == "adjudicated"
    assert bindings[0]["source"] == "user_confirmed"
    assert bindings[0]["confidence"] == 1.0


def test_dimension_permission_plan_resolves_conflicting_role():
    bindings = [
        {"text": "60", "value": 60.0, "semantic_role": "profile_height"},
        {"text": "96", "value": 96.0, "semantic_role": "profile_height"},
    ]

    DimensionPermissionPlan.resolve_conflicting_role(
        bindings,
        role="profile_height",
        selected_value="96",
    )

    by_text = {item["text"]: item for item in bindings}
    assert by_text["96"]["binding_status"] == "adjudicated"
    assert by_text["96"]["source"] == "user_confirmed"
    assert by_text["60"]["semantic_role"] == "unresolved_linear"
    assert "binding_status" not in by_text["60"]


def test_dimension_permission_plan_excludes_unknown_candidate_answer():
    bindings = [
        {
            "text": "96",
            "value": 96.0,
            "semantic_role": "profile_length",
            "binding_status": "candidate",
            "confidence": 0.7,
        },
        {
            "text": "30",
            "value": 30.0,
            "semantic_role": "unresolved_linear",
            "span": {"view_name": "main", "orientation": "horizontal"},
        },
    ]

    DimensionPermissionPlan.exclude_for_question(bindings, "resolve_profile_length")

    assert [item["semantic_role"] for item in bindings] == [
        "excluded_by_user",
        "excluded_by_user",
    ]
    assert all("binding_status" not in item for item in bindings)


def test_dimension_permission_plan_applies_feature_detail_dimension_answer():
    bindings = [
        {
            "text": "40",
            "value": 40.0,
            "semantic_role": "unresolved_linear",
            "confidence": 0.0,
        }
    ]
    answer = (
        '{"action":"bind_feature_dimension","dimension_text":"40",'
        '"role":"feature_depth","feature_kind":"boss",'
        '"feature_description":"中心圆柱凸台"}'
    )

    DimensionPermissionPlan.apply_feature_detail_dimension_answer(bindings, answer)

    assert bindings[0]["semantic_role"] == "feature_depth"
    assert bindings[0]["confidence"] == 1.0
    assert bindings[0]["feature_kind"] == "boss"
    assert bindings[0]["feature_description"] == "中心圆柱凸台"
    assert bindings[0]["source"] == "user_confirmed"


def test_dimension_permission_plan_excludes_feature_detail_dimensions():
    bindings = [
        {
            "text": "40",
            "value": 40.0,
            "semantic_role": "unresolved_linear",
            "confidence": 0.0,
        },
        {
            "text": "8",
            "value": 8.0,
            "semantic_role": "unresolved_linear",
            "confidence": 0.0,
        },
    ]

    DimensionPermissionPlan.apply_feature_detail_dimension_answer(
        bindings,
        {
            "action": "exclude_feature_dimensions",
            "dimension_texts": ["40"],
            "feature_description": "凸台高度未确认",
        },
    )

    assert bindings[0]["semantic_role"] == "excluded_by_user"
    assert bindings[0]["source"] == "user_confirmed"
    assert bindings[0]["feature_description"] == "凸台高度未确认"
    assert bindings[1]["semantic_role"] == "unresolved_linear"
