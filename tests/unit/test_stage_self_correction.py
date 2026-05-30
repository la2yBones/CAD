#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.utils.stage_self_correction import (
    CONTINUE_WITH_RISK,
    CORRECTED,
    DEFAULT_SUPERVISION_ACTIONS,
    SELF_CORRECT,
    CandidateOption,
    SelfCorrectionRequest,
    SelfCorrectionResult,
    StageSelfCorrectionCase,
    StageSelfCorrectionSession,
    ValidationIssue,
)


def test_validation_issue_serializes_optional_fields_only_when_present():
    issue = ValidationIssue(
        code="missing_final_shape",
        message="缺少 final_shape 赋值",
        impact="脚本无法确认最终实体",
        correction_target="生成 final_shape 并展示",
    )

    assert issue.to_dict() == {
        "code": "missing_final_shape",
        "message": "缺少 final_shape 赋值",
        "severity": "error",
        "fixable": True,
        "impact": "脚本无法确认最终实体",
        "correction_target": "生成 final_shape 并展示",
    }


def test_self_correction_request_keeps_stage_contract_and_round_state():
    issue = ValidationIssue("schema_error", "缺少 views 字段")
    request = SelfCorrectionRequest(
        stage="view_analysis",
        round_index=2,
        max_rounds=2,
        stage_payload={"task": "校正视图"},
        previous_output={"drawing_type": "unknown"},
        validation_issues=[issue],
        output_contract={"required": ["views"]},
        evidence_refs=[{"id": "view_a"}],
        correction_goal="补齐视图数组",
    )

    data = request.to_dict()

    assert request.is_last_round is True
    assert data["stage"] == "view_analysis"
    assert data["validation_issues"][0]["code"] == "schema_error"
    assert data["evidence_refs"] == [{"id": "view_a"}]
    assert data["correction_goal"] == "补齐视图数组"


def test_self_correction_result_marks_corrected_and_risky_outputs_as_continuable():
    corrected = SelfCorrectionResult(
        status=CORRECTED,
        corrected_output={"freecad_script": "..."},
    )
    risky = SelfCorrectionResult(
        status=CONTINUE_WITH_RISK,
        risk_notes=["圆角被跳过"],
    )

    assert corrected.can_continue is True
    assert risky.can_continue is True
    assert risky.to_dict()["risk_notes"] == ["圆角被跳过"]


def test_candidate_options_are_serialized_for_user_confirmation():
    option = CandidateOption(
        id="use_40_as_boss_height",
        label="40 是凸台高度",
        value={"dimension": 40, "role": "boss_height"},
        evidence=["右视图凸台深度标注"],
        risk="若 40 不是凸台高度，凸台会过长",
        recommended=True,
    )
    result = SelfCorrectionResult(
        status="needs_user_confirmation",
        candidate_options=[option],
        next_action="self_correct",
        message="需要用户监督确认",
    )

    data = result.to_dict()

    assert data["candidate_options"][0]["recommended"] is True
    assert data["candidate_options"][0]["value"]["role"] == "boss_height"
    assert data["message"] == "需要用户监督确认"


def test_default_supervision_actions_include_self_correction():
    actions = [action.to_dict() for action in DEFAULT_SUPERVISION_ACTIONS]

    assert {action["action"] for action in actions} >= {"continue", "stop", "retry_stage", SELF_CORRECT}
    assert any(action["label"] == "模型自纠" for action in actions)


def test_stage_self_correction_session_builds_request_and_attaches_log():
    seen = {}

    def generate(request, file_path=None):
        seen["request"] = request
        seen["file_path"] = file_path
        return {"part_type": "flange"}

    case = StageSelfCorrectionCase(
        stage="semantic_reconstruction",
        stage_payload={"semantic_policy": {}},
        previous_output={"part_type": "plate"},
        validation_issues=[
            ValidationIssue(
                code="user_requested_semantic_reconstruction_self_correction",
                message="用户要求复核",
            )
        ],
        output_contract={"required_fields": ["part_type"]},
        generate=generate,
        correction_goal="重新生成零件语义",
        log_trigger="user_requested_semantic_reconstruction_self_correction",
        log_result="用户触发后已重新生成零件语义",
    )

    result = StageSelfCorrectionSession().self_correct(case, file_path="part.dxf")

    assert result.status == CORRECTED
    assert result.corrected_output["part_type"] == "flange"
    assert result.corrected_output["self_correction_applied"] is True
    assert result.self_correction_log[0]["stage"] == "semantic_reconstruction"
    assert result.self_correction_log[0]["trigger"] == (
        "user_requested_semantic_reconstruction_self_correction"
    )
    assert seen["request"].stage == "semantic_reconstruction"
    assert seen["request"].previous_output["part_type"] == "plate"
    assert seen["file_path"] == "part.dxf"


def test_stage_self_correction_session_reports_failed_non_dict_output():
    case = StageSelfCorrectionCase(
        stage="view_analysis",
        stage_payload={},
        previous_output={},
        validation_issues=[ValidationIssue("bad_output", "输出不是对象")],
        output_contract={},
        generate=lambda request, file_path=None: None,
    )

    result = StageSelfCorrectionSession().self_correct(case)

    assert result.status == "failed"
    assert result.corrected_output is None
