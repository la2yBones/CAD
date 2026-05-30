#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI DeepSeek configuration adapter and display helpers."""
from __future__ import annotations

from typing import Any, Dict

from .deepseek_options import (
    STAGE_MODELING_GENERATION,
    STAGE_SEMANTIC_ADJUDICATION,
    STAGE_SEMANTIC_GENERATION,
    STAGE_VIEW_ANALYSIS,
    api_key_from_env,
    llm_provider,
    normalize_reasoning_effort,
)


def apply_gui_deepseek_overrides(config: Dict[str, Any], app_config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge GUI-managed DeepSeek options into the runtime config."""
    gui_deepseek = app_config_data.get("deepseek") or {}
    if not isinstance(gui_deepseek, dict):
        return config

    deepseek = config.setdefault("api", {}).setdefault("deepseek", {})
    string_keys = ("user_id", "base_url", "model", "view_model", "semantic_model")
    for key in string_keys:
        value = str(gui_deepseek.get(key) or "").strip()
        if value:
            deepseek[key] = value
    adjudication_model = str(gui_deepseek.get("adjudication_model") or "").strip()
    if adjudication_model:
        deepseek["semantic_adjudication_model"] = adjudication_model

    front_string_keys = (
        "front_stage_provider",
        "front_stage_base_url",
        "semantic_adjudication_provider",
        "semantic_adjudication_base_url",
        "view_provider",
        "view_base_url",
    )
    for key in front_string_keys:
        value = str(gui_deepseek.get(key) or "").strip()
        if value:
            deepseek[key] = value
    if bool(gui_deepseek.get("enable_multimodal_front_stage_input", False)):
        deepseek["enable_multimodal_front_stage_input"] = True
    front_provider = llm_provider(
        deepseek,
        stage=STAGE_SEMANTIC_ADJUDICATION,
        model=str(deepseek.get("semantic_adjudication_model") or deepseek.get("view_model") or ""),
        base_url=str(deepseek.get("front_stage_base_url") or ""),
    )
    front_api_key = _front_stage_api_key_from_env()
    if front_api_key and front_provider in {"moonshot", "kimi"}:
        deepseek["front_stage_api_key"] = front_api_key
    try:
        max_images = int(gui_deepseek.get("semantic_adjudication_max_images") or 1)
        if max_images > 0:
            deepseek["semantic_adjudication_max_images"] = max_images
    except (TypeError, ValueError):
        pass

    timeout = gui_deepseek.get("request_timeout_seconds")
    try:
        timeout_value = float(timeout)
        if timeout_value > 0:
            deepseek["request_timeout_seconds"] = int(timeout_value) if timeout_value.is_integer() else timeout_value
    except (TypeError, ValueError):
        pass

    stage_thinking = deepseek.setdefault("stage_thinking", {})
    stage_thinking[STAGE_VIEW_ANALYSIS] = {
        "enabled": bool(gui_deepseek.get("view_thinking_enabled", False)),
        "reasoning_effort": normalize_gui_reasoning_effort(
            gui_deepseek.get("view_reasoning_effort"),
            "high",
        ),
    }
    stage_thinking[STAGE_SEMANTIC_ADJUDICATION] = {
        "enabled": bool(gui_deepseek.get("adjudication_thinking_enabled", False)),
        "reasoning_effort": normalize_gui_reasoning_effort(
            gui_deepseek.get("adjudication_reasoning_effort"),
            "high",
        ),
    }
    stage_thinking[STAGE_SEMANTIC_GENERATION] = {
        "enabled": bool(gui_deepseek.get("semantic_thinking_enabled", False)),
        "reasoning_effort": normalize_gui_reasoning_effort(
            gui_deepseek.get("semantic_reasoning_effort"),
            "high",
        ),
    }
    stage_thinking[STAGE_MODELING_GENERATION] = {
        "enabled": bool(gui_deepseek.get("modeling_thinking_enabled", False)),
        "reasoning_effort": normalize_gui_reasoning_effort(
            gui_deepseek.get("modeling_reasoning_effort"),
            "max",
        ),
    }
    return config


def apply_gui_runtime_overrides(config: Dict[str, Any], app_config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge GUI runtime preferences into the application config."""
    cache_config_data = app_config_data.get("cache") or {}
    if isinstance(cache_config_data, dict):
        cache_config = config.setdefault("cache", {})
        cache_dir = cache_config_data.get("dir", ".cache/analysis")
        ttl_days = cache_config_data.get("default_ttl_days", 7)
        try:
            default_ttl = int(float(ttl_days) * 86400)
        except (TypeError, ValueError):
            default_ttl = 7 * 86400
        cache_config["cache_dir"] = cache_dir
        cache_config["default_ttl"] = default_ttl
        config["cache_dir"] = cache_dir
        config["cache_ttl"] = default_ttl

    return apply_gui_deepseek_overrides(config, app_config_data)


def normalize_gui_reasoning_effort(value: Any, default: str) -> str:
    return normalize_reasoning_effort(value, default=default)


def _front_stage_api_key_from_env() -> str:
    return api_key_from_env("MOONSHOT_API_KEY", "KIMI_API_KEY")


def format_llm_token_status(summary: Dict[str, Any]) -> str:
    cache_hit = int(summary.get("prompt_cache_hit_tokens") or 0)
    cache_rate = float(summary.get("prompt_cache_hit_rate") or 0.0)
    return (
        "Tokens: {total:,} | 缓存命中: {cache_hit:,}/{cache_rate:.0%} | 费用: ¥{cost:.4f} | 调用: {calls}"
    ).format(
        total=summary.get("total_tokens", 0),
        cache_hit=cache_hit,
        cache_rate=cache_rate,
        cost=float(summary.get("cost_cny") or 0.0),
        calls=summary.get("call_count", 0),
    )
