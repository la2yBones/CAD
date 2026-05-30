# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.utils.deepseek_options import (
    DEEPSEEK_LLM_STAGES,
    STAGE_SEMANTIC_ADJUDICATION,
    STAGE_SEMANTIC_GENERATION,
    STAGE_VIEW_ANALYSIS,
    apply_common_request_options,
    apply_stage_request_options,
    client_timeout,
    is_retryable_error,
    normalize_reasoning_effort,
    stage_thinking_enabled,
    thinking_extra_body,
)


def test_common_request_options_does_not_pass_user_id_to_sdk_payload():
    payload = apply_common_request_options({"model": "deepseek-v4-pro"}, {"user_id": "cad"})

    assert "user_id" not in payload


def test_client_timeout_accepts_numeric_config():
    assert client_timeout({"request_timeout_seconds": "12.5"}) == 12.5
    assert client_timeout({}) is None


def test_stage_thinking_and_reasoning_effort_are_normalized():
    config = {
            "reasoning_effort": "invalid",
            "stage_thinking": {
            STAGE_SEMANTIC_GENERATION: {
                "enabled": True,
                "reasoning_effort": "max",
            }
        },
    }

    assert stage_thinking_enabled(config, STAGE_SEMANTIC_GENERATION, default=False)
    assert thinking_extra_body(
        enabled=True,
        config=config,
        stage=STAGE_SEMANTIC_GENERATION,
    ) == {"thinking": {"type": "enabled", "reasoning_effort": "max"}}
    assert normalize_reasoning_effort("medium") == "high"


def test_deepseek_llm_stages_list_known_stage_keys():
    assert DEEPSEEK_LLM_STAGES == (
        "view_analysis",
        "semantic_adjudication",
        "semantic_generation",
        "modeling_generation",
    )


def test_apply_stage_request_options_supports_stage_thinking_without_user_id_payload():
    payload = apply_stage_request_options(
        {"model": "deepseek-v4-pro"},
        {
            "user_id": "cad",
            "stage_thinking": {
                STAGE_SEMANTIC_ADJUDICATION: {
                    "enabled": True,
                    "reasoning_effort": "max",
                }
            },
        },
        stage=STAGE_SEMANTIC_ADJUDICATION,
        default_thinking=False,
        default_effort="high",
    )

    assert "user_id" not in payload
    assert payload["extra_body"] == {
        "thinking": {"type": "enabled", "reasoning_effort": "max"}
    }


def test_apply_stage_request_options_normalizes_legacy_effort_values():
    payload = apply_stage_request_options(
        {"model": "deepseek-v4-pro"},
        {
            "semantic_adjudication_thinking": True,
            "semantic_adjudication_reasoning_effort": "medium",
        },
        stage=STAGE_SEMANTIC_ADJUDICATION,
        default_thinking=False,
        default_effort="high",
        legacy_thinking_keys=("semantic_adjudication_thinking",),
        legacy_effort_keys=("semantic_adjudication_reasoning_effort",),
    )

    assert payload["extra_body"] == {
        "thinking": {"type": "enabled", "reasoning_effort": "high"}
    }


def test_apply_stage_request_options_force_thinking_overrides_disabled_stage():
    payload = apply_stage_request_options(
        {"model": "deepseek-v4-pro"},
        {
            "stage_thinking": {
                STAGE_SEMANTIC_GENERATION: {
                    "enabled": False,
                    "reasoning_effort": "max",
                }
            },
        },
        stage=STAGE_SEMANTIC_GENERATION,
        default_thinking=False,
        default_effort="high",
        force_thinking=True,
    )

    assert payload["extra_body"] == {
        "thinking": {"type": "enabled", "reasoning_effort": "max"}
    }


def test_apply_stage_request_options_uses_moonshot_thinking_shape():
    payload = apply_stage_request_options(
        {"model": "kimi-k2.6"},
        {
            "front_stage_provider": "moonshot",
            "stage_thinking": {
                STAGE_VIEW_ANALYSIS: {
                    "enabled": True,
                }
            },
        },
        stage=STAGE_VIEW_ANALYSIS,
        default_thinking=False,
    )

    assert payload["extra_body"] == {
        "thinking": {"type": "enabled", "keep": "all"}
    }


def test_retryable_error_detects_transient_status_codes():
    assert is_retryable_error(SimpleNamespace(status_code=429))
    assert is_retryable_error(SimpleNamespace(response=SimpleNamespace(status_code=503)))
    assert not is_retryable_error(SimpleNamespace(status_code=401))
