# -*- coding: utf-8 -*-

from src.reconstruction.clarification import (
    UNKNOWN_ANSWER,
    build_candidate_clarification_summary,
    build_conflicting_key_role_questions,
    build_candidate_role_questions,
    build_missing_multiview_axis_questions,
    clarification_option_label,
    clarification_option_value,
    is_candidate_clarification_question,
)


def test_candidate_role_questions_use_candidate_dimensions_only():
    questions = build_candidate_role_questions(
        [
            {
                "text": "96",
                "value": 96.0,
                "semantic_role": "profile_length",
                "binding_status": "candidate",
                "evidence": ["正方形外形候选"],
            },
            {
                "text": "60",
                "value": 60.0,
                "semantic_role": "profile_height",
                "binding_status": "adjudicated",
            },
        ],
        [],
    )

    assert [item["id"] for item in questions] == ["resolve_profile_length"]
    assert is_candidate_clarification_question(questions[0])
    assert questions[0]["options"][0]["label"] == "96（正方形外形候选）"
    assert questions[0]["options"][0]["value"] == "96"
    assert questions[0]["options"][1]["value"] == UNKNOWN_ANSWER


def test_candidate_role_questions_skip_existing_question_id():
    questions = build_candidate_role_questions(
        [
            {
                "text": "96",
                "value": 96.0,
                "semantic_role": "profile_length",
                "binding_status": "candidate",
            }
        ],
        [{"id": "resolve_profile_length"}],
    )

    assert questions == []


def test_conflicting_key_role_questions_ask_user_to_choose_one_value():
    questions = build_conflicting_key_role_questions([
        {"text": "90", "value": 90.0, "semantic_role": "profile_length"},
        {"text": "96", "value": 96.0, "semantic_role": "profile_length"},
    ])

    assert [item["id"] for item in questions] == ["resolve_profile_length"]
    assert "多个值" in questions[0]["text"]
    assert [option["value"] for option in questions[0]["options"]] == ["90", "96"]


def test_missing_multiview_axis_questions_ask_for_main_horizontal_total_size():
    questions = build_missing_multiview_axis_questions(
        [
            {
                "text": "30",
                "value": 30.0,
                "semantic_role": "unresolved_linear",
                "span": {"view_name": "main", "orientation": "horizontal"},
            }
        ],
        {"view_analysis": {"drawing_type": "two_view"}},
    )

    assert [item["id"] for item in questions] == ["bind_profile_length"]
    assert "请确认哪个标注值" in questions[0]["text"]
    assert [option["value"] for option in questions[0]["options"]] == ["30", UNKNOWN_ANSWER]


def test_candidate_clarification_summary_confirms_selected_value():
    questions = [{
        "id": "resolve_profile_length",
        "text": "系统只找到了轮廓总长的候选值，请确认是否采用。",
        "kind": "single_choice",
        "options": [
            {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
            {"label": "不确定 / 暂不使用这些候选", "value": UNKNOWN_ANSWER},
        ],
    }]

    summary = build_candidate_clarification_summary(
        questions,
        {"resolve_profile_length": "48"},
    )

    assert "即将提交以下候选尺寸处理结果" in summary
    assert "确认采用 48（由相邻尺寸链组合得到的候选）" in summary


def test_candidate_clarification_summary_marks_unknown_as_excluded():
    questions = [{
        "id": "resolve_profile_length",
        "text": "系统只找到了轮廓总长的候选值，请确认是否采用。",
        "kind": "single_choice",
        "options": [
            {"label": "48（由相邻尺寸链组合得到的候选）", "value": "48"},
            {"label": "不确定 / 暂不使用这些候选", "value": UNKNOWN_ANSWER},
        ],
    }]

    summary = build_candidate_clarification_summary(
        questions,
        {"resolve_profile_length": UNKNOWN_ANSWER},
    )

    assert "不采用候选值" in summary
    assert "不会把它作为建模尺寸" in summary


def test_clarification_option_helpers_accept_plain_and_mapping_options():
    assert clarification_option_label({"label": "采用 48", "value": "48"}) == "采用 48"
    assert clarification_option_value({"label": "采用 48", "value": "48"}) == "48"
    assert clarification_option_label("不确定") == "不确定"
    assert clarification_option_value("不确定") == "不确定"
