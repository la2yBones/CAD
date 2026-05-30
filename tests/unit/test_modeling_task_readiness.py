# -*- coding: utf-8 -*-

from src.reconstruction.modeling_task import ModelingTaskReadinessChecker


def test_readiness_allows_semantic_task_with_base_body():
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "features": {"base": [{"kind": "box"}]},
        "dimensions": {},
        "recovery_hints": {},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is True
    assert result["severity"] == "ok"


def test_readiness_blocks_without_body_source():
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "features": {"additive": [{"kind": "boss"}], "subtractive": []},
        "dimensions": {"modeling_dimensions": [{"role": "diameter", "value": 20}]},
        "recovery_hints": {},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is False
    assert "body_source" in result["missing"]


def test_readiness_blocks_planar_without_depth():
    payload = {
        "object": {"selected_modeling_path": "planar_extrude"},
        "features": {
            "base": [{"kind": "profile_extrusion"}],
            "planar_modeling": {
                "profile": {"kind": "closed_profile"},
                "extrusion_direction": "Z",
                "extrusion_depth": None,
            },
        },
        "dimensions": {},
        "recovery_hints": {},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is False
    assert "extrusion_depth" in result["missing"]


def test_readiness_blocks_revolve_without_axis():
    payload = {
        "object": {"selected_modeling_path": "revolve"},
        "features": {
            "revolve_modeling": {
                "axis_point": None,
                "axis_direction": [0, 0, 1],
                "profile_points": [[1, 0, 0], [1, 0, 2]],
            },
        },
        "dimensions": {},
        "recovery_hints": {},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is False
    assert "axis_point" in result["missing"]


def test_readiness_blocks_candidate_only_dimensions():
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "features": {"base": [{"kind": "plate"}]},
        "dimensions": {
            "candidate_dimensions": [{"value": 40}],
            "unresolved_dimensions": [{"value": 60}],
        },
        "recovery_hints": {},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is False
    assert "authoritative_modeling_dimensions" in result["missing"]


def test_readiness_blocks_body_closure_warnings():
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "features": {"base": [{"kind": "plate"}]},
        "dimensions": {},
        "recovery_hints": {"warnings": ["主体厚度缺失，无法确定体量"]},
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is False
    assert "body_closure_risk" in result["missing"]
    assert result["risks"] == ["主体厚度缺失，无法确定体量"]


def test_readiness_allows_semantic_operations_with_body_risk_as_warning():
    payload = {
        "object": {"selected_modeling_path": "semantic_reconstruction"},
        "features": {
            "base": [{"kind": "revolved_cylinder"}],
            "subtractive": [{"kind": "through_hole"}],
        },
        "modeling_operations": [
            {"operation": "revolve_profile", "description": "生成外径64、长度96的主体"},
            {"operation": "subtract_feature", "description": "切除中心通孔"},
        ],
        "dimensions": {
            "modeling_dimensions": [
                {"role": "outer_diameter", "value": 64},
                {"role": "inner_diameter", "value": 32},
                {"role": "length", "value": 96},
            ]
        },
        "recovery_hints": {
            "uncertainties": ["D2尺寸40含义不明，可能为拉伸深度或台阶长度"]
        },
    }

    result = ModelingTaskReadinessChecker().check(payload)

    assert result["ready"] is True
    assert result["severity"] == "ok"
    assert result["recommended_action"] == "continue_with_warnings"
    assert "body_closure_risk" not in result["missing"]
    assert result["risks"] == ["D2尺寸40含义不明，可能为拉伸深度或台阶长度"]
