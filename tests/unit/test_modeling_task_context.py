# -*- coding: utf-8 -*-

from src.reconstruction.modeling_task import ModelingTaskContextBuilder


def test_modeling_task_context_builds_constraints_contract():
    constraints = ModelingTaskContextBuilder().build_constraints(
        semantic_policy={
            "feature_constraints": {"hidden_lines_alone_are_insufficient": True},
            "assumptions": ["裸线性尺寸不得进入 key_dimensions"],
        },
        modeling_path_decision={
            "modeling_path": "semantic_reconstruction",
            "reason": "无专用路径满足当前契约",
            "fallback_from_path_clarification": True,
        },
    )

    assert constraints["feature_constraints"]["hidden_lines_alone_are_insufficient"] is True
    assert constraints["assumptions"] == ["裸线性尺寸不得进入 key_dimensions"]
    assert constraints["modeling_path_decision"]["modeling_path"] == "semantic_reconstruction"
    assert constraints["modeling_path_decision"]["fallback_from_path_clarification"] is True
    assert constraints["partial_modeling_policy"]["complete_main_body_first"] is True
    assert "raw geometry entities" in constraints["forbidden_inputs"]


def test_modeling_task_context_builds_recovery_hints_with_precedence():
    hints = ModelingTaskContextBuilder().build_recovery_hints(
        semantics={
            "user_modeling_hint": "语义提示",
            "user_modeling_hint_policy": "semantic_policy",
            "path_clarification_fallback": {"missing_fields": ["depth"]},
            "uncertainties": ["凸台高度不确定"],
            "warnings": ["圆角跳过"],
        },
        reconstruction_context={
            "user_modeling_hint": "用户在澄清窗口补充",
            "user_modeling_hint_policy": "drawing_facts_override_user_hint",
        },
        semantic_policy={
            "user_modeling_hint": "策略提示",
            "user_modeling_hint_policy": "policy",
        },
        recovery_context={"skipped_features": [{"name": "fillet"}]},
    )

    assert hints["user_modeling_hint"] == "用户在澄清窗口补充"
    assert hints["user_modeling_hint_policy"] == "drawing_facts_override_user_hint"
    assert hints["path_clarification_fallback"] == {"missing_fields": ["depth"]}
    assert hints["uncertainties"] == ["凸台高度不确定"]
    assert hints["warnings"] == ["圆角跳过"]
    assert hints["previous_partial_result"]["skipped_features"][0]["name"] == "fillet"


def test_modeling_task_context_defaults_user_hint_policy():
    hints = ModelingTaskContextBuilder().build_recovery_hints(
        semantics={},
        reconstruction_context={},
        semantic_policy={},
        recovery_context=None,
    )

    assert hints["user_modeling_hint"] == ""
    assert hints["user_modeling_hint_policy"] == "drawing_facts_override_user_hint"
    assert hints["previous_partial_result"] == {}


def test_modeling_task_context_summarizes_script_quality_recovery_without_full_script():
    hints = ModelingTaskContextBuilder().build_recovery_hints(
        semantics={},
        reconstruction_context={},
        semantic_policy={},
        recovery_context={
            "script_quality_recovery": True,
            "script_validation_errors": ["缺少 final_shape 赋值"],
            "script_failure_error": "AI脚本未通过可执行性校验",
            "failed_freecad_script": "bad script should not be sent",
            "self_correction_request": {
                "stage": "modeling_generation",
                "previous_output": {"script_length": 42},
                "validation_issues": [{"code": "script_quality_1"}],
            },
            "self_correction_result": {
                "status": "pending_recovery",
                "next_action": "self_correct",
            },
            "previous_modeling_instructions": {
                "analysis_summary": "上一版尝试建模主体",
                "freecad_script": "bad script should not be sent",
                "warnings": ["脚本缺少 final_shape"],
            },
        },
    )

    recovery = hints["previous_partial_result"]
    assert recovery["script_quality_recovery"] is True
    assert recovery["script_validation_errors"] == ["缺少 final_shape 赋值"]
    assert recovery["self_correction_request"]["stage"] == "modeling_generation"
    assert recovery["self_correction_result"]["next_action"] == "self_correct"
    assert "script_recovery_policy" in recovery
    assert recovery["previous_modeling_instruction_summary"]["analysis_summary"] == "上一版尝试建模主体"
    assert "failed_freecad_script" not in recovery
    assert "freecad_script" not in repr(recovery)
    assert "bad script should not be sent" not in repr(recovery)
