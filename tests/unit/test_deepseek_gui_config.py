# -*- coding: utf-8 -*-

from src.utils.deepseek_gui_config import (
    apply_gui_deepseek_overrides,
    apply_gui_runtime_overrides,
    format_llm_token_status,
)


def test_apply_gui_deepseek_overrides_merges_stage_options():
    config = {"api": {"deepseek": {"model": "old-model"}}}
    app_config = {
        "deepseek": {
            "user_id": "local-user",
            "request_timeout_seconds": 180,
            "model": "deepseek-v4-pro",
            "view_model": "deepseek-v4-pro",
            "adjudication_model": "deepseek-v4-pro",
            "semantic_model": "deepseek-v4-pro",
            "view_thinking_enabled": False,
            "view_reasoning_effort": "max",
            "adjudication_thinking_enabled": True,
            "adjudication_reasoning_effort": "high",
            "semantic_thinking_enabled": True,
            "semantic_reasoning_effort": "high",
            "modeling_thinking_enabled": True,
            "modeling_reasoning_effort": "max",
        }
    }

    apply_gui_deepseek_overrides(config, app_config)

    deepseek = config["api"]["deepseek"]
    assert deepseek["user_id"] == "local-user"
    assert deepseek["request_timeout_seconds"] == 180
    assert deepseek["view_model"] == "deepseek-v4-pro"
    assert deepseek["semantic_adjudication_model"] == "deepseek-v4-pro"
    assert not deepseek["stage_thinking"]["view_analysis"]["enabled"]
    assert deepseek["stage_thinking"]["view_analysis"]["reasoning_effort"] == "max"
    assert deepseek["stage_thinking"]["semantic_adjudication"]["enabled"]
    assert deepseek["stage_thinking"]["semantic_adjudication"]["reasoning_effort"] == "high"
    assert deepseek["stage_thinking"]["semantic_generation"]["enabled"]
    assert deepseek["stage_thinking"]["semantic_generation"]["reasoning_effort"] == "high"
    assert deepseek["stage_thinking"]["modeling_generation"]["enabled"]
    assert deepseek["stage_thinking"]["modeling_generation"]["reasoning_effort"] == "max"


def test_apply_gui_deepseek_overrides_merges_front_stage_model_config(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-test-key")
    config = {"api": {"deepseek": {"model": "deepseek-v4-pro"}}}
    app_config = {
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "view_model": "kimi-k2.6",
            "adjudication_model": "kimi-k2.6",
            "front_stage_provider": "moonshot",
            "front_stage_base_url": "https://api.moonshot.cn/v1",
            "enable_multimodal_front_stage_input": True,
            "semantic_adjudication_max_images": 2,
        }
    }

    apply_gui_deepseek_overrides(config, app_config)

    deepseek = config["api"]["deepseek"]
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert deepseek["view_model"] == "kimi-k2.6"
    assert deepseek["semantic_adjudication_model"] == "kimi-k2.6"
    assert deepseek["front_stage_provider"] == "moonshot"
    assert deepseek["front_stage_base_url"] == "https://api.moonshot.cn/v1"
    assert deepseek["front_stage_api_key"] == "moonshot-test-key"
    assert deepseek["enable_multimodal_front_stage_input"] is True
    assert deepseek["semantic_adjudication_max_images"] == 2


def test_apply_gui_runtime_overrides_merges_cache_and_deepseek_config():
    config = {}
    app_config = {
        "cache": {
            "dir": ".cache/custom-analysis",
            "default_ttl_days": 3,
        },
        "deepseek": {
            "user_id": "gui-user",
            "request_timeout_seconds": "120",
        },
    }

    apply_gui_runtime_overrides(config, app_config)

    assert config["cache"]["cache_dir"] == ".cache/custom-analysis"
    assert config["cache"]["default_ttl"] == 3 * 86400
    assert config["cache_dir"] == ".cache/custom-analysis"
    assert config["cache_ttl"] == 3 * 86400
    assert config["api"]["deepseek"]["user_id"] == "gui-user"
    assert config["api"]["deepseek"]["request_timeout_seconds"] == 120


def test_apply_gui_runtime_overrides_uses_safe_cache_ttl_default():
    config = {}

    apply_gui_runtime_overrides(config, {"cache": {"default_ttl_days": "not-a-number"}})

    assert config["cache"]["default_ttl"] == 7 * 86400
    assert config["cache_ttl"] == 7 * 86400


def test_apply_gui_deepseek_overrides_normalizes_unsupported_reasoning_effort():
    config = {}
    app_config = {
        "deepseek": {
            "view_reasoning_effort": "medium",
            "adjudication_reasoning_effort": "low",
            "semantic_reasoning_effort": "medium",
            "modeling_reasoning_effort": "low",
        }
    }

    apply_gui_deepseek_overrides(config, app_config)

    stage_thinking = config["api"]["deepseek"]["stage_thinking"]
    assert stage_thinking["view_analysis"]["reasoning_effort"] == "high"
    assert stage_thinking["semantic_adjudication"]["reasoning_effort"] == "high"
    assert stage_thinking["semantic_generation"]["reasoning_effort"] == "high"
    assert stage_thinking["modeling_generation"]["reasoning_effort"] == "max"


def test_format_llm_token_status_includes_cache_without_reasoning():
    text = format_llm_token_status({
        "call_count": 3,
        "prompt_tokens": 1000,
        "completion_tokens": 250,
        "total_tokens": 1250,
        "prompt_cache_hit_tokens": 600,
        "prompt_cache_hit_rate": 0.75,
        "cost_cny": 0.0123,
    })

    assert "Tokens: 1,250" in text
    assert "缓存命中: 600/75%" in text
    assert "费用: ¥0.0123" in text
    assert "推理" not in text
