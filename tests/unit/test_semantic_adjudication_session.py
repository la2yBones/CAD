# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.reconstruction.clarification_response import ClarificationResponse
from src.reconstruction.semantic_adjudication_session import (
    SEMANTIC_ADJUDICATION_STAGE,
    SEMANTIC_POLICY_STAGE,
    SemanticAdjudicationSession,
)
from src.utils.stage_confirmation import StageConfirmationResult


def _adjudication(questions=None, status="completed"):
    return {
        "status": status,
        "confidence": 0.9,
        "view_roles": [],
        "dimension_roles": [],
        "feature_roles": [],
        "derived_dimensions": [],
        "clarification_questions": questions or [],
        "uncertainties": [],
        "warnings": [],
    }


def _policy_result(questions=None):
    return {
        "dimension_source": "annotation",
        "adjudicated_context": {
            "semantic_policy": {"drawing_evidence_package": {"package_version": "test"}}
        },
        "clarification_questions": questions or [],
    }


def test_session_replaces_legacy_questions_when_adjudication_succeeds():
    session = SemanticAdjudicationSession(
        adjudicator=SimpleNamespace(adjudicate=lambda context, file_path=None: _adjudication()),
    )

    updated_policy, updated_context = session.apply(
        _policy_result(questions=[{"id": "legacy"}]),
        file_path=None,
    )

    assert updated_policy["clarification_questions"] == []
    assert updated_context["semantic_policy"]["semantic_adjudication"]["status"] == "completed"


def test_session_preserves_legacy_questions_when_adjudication_fails():
    legacy_questions = [{"id": "legacy"}]
    session = SemanticAdjudicationSession(
        adjudicator=SimpleNamespace(
            adjudicate=lambda context, file_path=None: _adjudication(status="failed")
        ),
    )

    updated_policy, _updated_context = session.apply(
        _policy_result(questions=legacy_questions),
        file_path=None,
    )

    assert updated_policy["clarification_questions"] == legacy_questions


def test_session_tags_adjudication_questions_and_confirms_stage():
    confirmed = []
    session = SemanticAdjudicationSession(
        adjudicator=SimpleNamespace(
            adjudicate=lambda context, file_path=None: _adjudication(
                questions=[{"id": "confirm_D1_role"}]
            )
        ),
        confirm_stage=lambda stage, payload: confirmed.append((stage, payload)),
    )

    updated_policy, _updated_context = session.apply(_policy_result(), file_path="part.dxf")

    assert updated_policy["clarification_questions"][0]["source_stage"] == SEMANTIC_ADJUDICATION_STAGE
    assert confirmed[0][0] == SEMANTIC_ADJUDICATION_STAGE
    assert "semantic_adjudication" in confirmed[0][1]


def test_session_passes_semantic_adjudication_clarification_to_adjudicator():
    seen_contexts = []
    session = SemanticAdjudicationSession(
        adjudicator=SimpleNamespace(
            adjudicate=lambda context, file_path=None: seen_contexts.append(context) or _adjudication()
        ),
    )
    clarification = ClarificationResponse.from_input(
        {"confirm_D1_role": "extrusion_depth"},
        source_stage=SEMANTIC_ADJUDICATION_STAGE,
    )

    session.apply(
        _policy_result(),
        file_path=None,
        clarification_response=clarification,
    )

    assert seen_contexts[0]["semantic_adjudication_clarification"]["answers"] == {
        "confirm_D1_role": "extrusion_depth"
    }


def test_session_retries_semantic_adjudication_when_user_requests_stage_retry():
    calls = []
    confirmations = []

    def adjudicate(context, file_path=None):
        calls.append(context)
        return _adjudication()

    def confirm(stage, payload):
        confirmations.append((stage, payload))
        if len(confirmations) == 1:
            return StageConfirmationResult.retry_stage(stage=stage)
        return StageConfirmationResult.continue_()

    session = SemanticAdjudicationSession(
        adjudicator=SimpleNamespace(adjudicate=adjudicate),
        confirm_stage=confirm,
    )

    updated_policy, updated_context = session.apply(_policy_result(), file_path="part.dxf")

    assert len(calls) == 2
    assert [item[0] for item in confirmations] == [
        SEMANTIC_ADJUDICATION_STAGE,
        SEMANTIC_ADJUDICATION_STAGE,
    ]
    assert updated_policy["semantic_adjudication"]["stage_retry_applied"]
    assert (
        updated_context["semantic_policy"]["semantic_adjudication"]["stage_retry_log"][0][
            "trigger"
        ]
        == "user_requested_retry_stage"
    )


def test_session_self_corrects_semantic_adjudication_when_user_requests_it():
    confirmations = []
    correction_requests = []

    class FakeAdjudicator:
        def adjudicate(self, context, file_path=None):
            return _adjudication()

        def generate_from_self_correction(self, request, file_path=None):
            correction_requests.append(request)
            corrected = _adjudication()
            corrected["confidence"] = 0.95
            return corrected

    def confirm(stage, payload):
        confirmations.append((stage, payload))
        if len(confirmations) == 1:
            return StageConfirmationResult.self_correct(stage=stage)
        return StageConfirmationResult.continue_()

    session = SemanticAdjudicationSession(
        adjudicator=FakeAdjudicator(),
        confirm_stage=confirm,
    )

    updated_policy, updated_context = session.apply(_policy_result(), file_path="part.dxf")

    assert len(correction_requests) == 1
    assert correction_requests[0].stage == SEMANTIC_ADJUDICATION_STAGE
    assert (
        correction_requests[0].stage_payload["drawing_evidence_package"]["package_version"]
        == "test"
    )
    assert [item[0] for item in confirmations] == [
        SEMANTIC_ADJUDICATION_STAGE,
        SEMANTIC_ADJUDICATION_STAGE,
    ]
    assert updated_policy["semantic_adjudication"]["confidence"] == 0.95
    assert updated_policy["semantic_adjudication"]["self_correction_applied"]
    assert (
        updated_context["semantic_policy"]["semantic_adjudication"]["self_correction_log"][0][
            "trigger"
        ]
        == "user_requested_semantic_adjudication_self_correction"
    )


def test_clarification_stage_detects_semantic_adjudication_questions():
    assert (
        SemanticAdjudicationSession.clarification_stage_for_policy_result(
            {"clarification_questions": [{"source_stage": SEMANTIC_ADJUDICATION_STAGE}]}
        )
        == SEMANTIC_ADJUDICATION_STAGE
    )
    assert (
        SemanticAdjudicationSession.clarification_stage_for_policy_result(
            {"clarification_questions": [{"source_stage": "semantic_policy"}]}
        )
        == SEMANTIC_POLICY_STAGE
    )
