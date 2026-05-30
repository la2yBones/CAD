#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared DeepSeek API option helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


REASONING_EFFORT_VALUES = {"high", "max"}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
STAGE_VIEW_ANALYSIS = "view_analysis"
STAGE_SEMANTIC_ADJUDICATION = "semantic_adjudication"
STAGE_SEMANTIC_GENERATION = "semantic_generation"
STAGE_MODELING_GENERATION = "modeling_generation"
DEEPSEEK_LLM_STAGES = (
    STAGE_VIEW_ANALYSIS,
    STAGE_SEMANTIC_ADJUDICATION,
    STAGE_SEMANTIC_GENERATION,
    STAGE_MODELING_GENERATION,
)
MOONSHOT_PROVIDERS = {"moonshot", "kimi"}


def client_timeout(config: Optional[Dict[str, Any]]) -> Optional[float]:
    config = config or {}
    value = config.get("request_timeout_seconds") or config.get("timeout")
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_common_request_options(
    payload: Dict[str, Any],
    config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return payload


def apply_stage_request_options(
    payload: Dict[str, Any],
    config: Optional[Dict[str, Any]],
    *,
    stage: str,
    default_thinking: bool,
    default_effort: str = "high",
    force_thinking: bool = False,
    legacy_thinking_keys: tuple[str, ...] = (),
    legacy_effort_keys: tuple[str, ...] = (),
) -> Dict[str, Any]:
    """Apply shared DeepSeek options and stage-specific thinking settings."""
    config = config or {}
    payload = apply_common_request_options(payload, config)
    thinking_enabled = _stage_thinking_enabled_with_legacy(
        config,
        stage,
        default=default_thinking,
        legacy_keys=legacy_thinking_keys,
    )
    thinking_enabled = bool(force_thinking) or thinking_enabled
    effective_default_effort = _stage_reasoning_effort_default(
        config,
        legacy_keys=legacy_effort_keys,
        default=default_effort,
    )
    payload["extra_body"] = thinking_extra_body(
        enabled=thinking_enabled,
        config=config,
        stage=stage,
        default_effort=effective_default_effort,
    )
    return payload


def llm_provider(
    config: Optional[Dict[str, Any]],
    *,
    stage: str = "",
    model: str = "",
    base_url: str = "",
) -> str:
    """返回阶段请求的 LLM 提供方，用于处理非标准兼容参数。"""
    config = config or {}
    provider = (
        _stage_value(config, stage, "provider")
        or config.get(f"{stage}_provider")
        or _front_stage_provider(config, stage)
        or config.get("provider")
        or ""
    )
    provider = str(provider or "").strip().lower()
    if provider:
        return provider
    model_text = str(model or "").lower()
    base_text = str(base_url or "").lower()
    if "kimi" in model_text or "moonshot" in base_text:
        return "moonshot"
    return "deepseek"


def api_key_from_env(*names: str) -> str:
    """从系统环境变量或项目 .env 读取 API Key，不打印密钥内容。"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return ""
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in names:
                return value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def thinking_extra_body(
    *,
    enabled: bool,
    config: Optional[Dict[str, Any]] = None,
    stage: str = "",
    default_effort: str = "high",
) -> Dict[str, Any]:
    config = config or {}
    if not enabled:
        return {"thinking": {"type": "disabled"}}

    provider = llm_provider(config, stage=stage)
    if provider in MOONSHOT_PROVIDERS:
        keep = (
            _stage_value(config, stage, "thinking_keep")
            or config.get("kimi_thinking_keep")
            or config.get("thinking_keep")
            or "all"
        )
        return {"thinking": {"type": "enabled", "keep": str(keep)}}

    effort = (
        _stage_value(config, stage, "reasoning_effort")
        or config.get("reasoning_effort")
        or default_effort
    )
    effort = normalize_reasoning_effort(effort, default=default_effort)
    return {"thinking": {"type": "enabled", "reasoning_effort": effort}}


def stage_thinking_enabled(
    config: Optional[Dict[str, Any]],
    stage: str,
    *,
    default: bool,
) -> bool:
    config = config or {}
    value = _stage_value(config, stage, "thinking")
    if value is None:
        value = _stage_value(config, stage, "enabled")
    if value is None:
        return default
    return bool(value)


def normalize_reasoning_effort(value: Any, *, default: str = "high") -> str:
    effort = str(value or "").strip().lower()
    if effort in REASONING_EFFORT_VALUES:
        return effort
    return default if default in REASONING_EFFORT_VALUES else "high"


def _stage_thinking_enabled_with_legacy(
    config: Dict[str, Any],
    stage: str,
    *,
    default: bool,
    legacy_keys: tuple[str, ...],
) -> bool:
    value = _stage_value(config, stage, "thinking")
    if value is None:
        value = _stage_value(config, stage, "enabled")
    if value is None:
        for key in legacy_keys:
            if key in config:
                value = config.get(key)
                break
    return default if value is None else bool(value)


def _stage_reasoning_effort_default(
    config: Dict[str, Any],
    *,
    legacy_keys: tuple[str, ...],
    default: str,
) -> str:
    for key in legacy_keys:
        if key in config:
            return normalize_reasoning_effort(config.get(key), default=default)
    return normalize_reasoning_effort(default, default="high")


def is_retryable_error(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        return int(status_code) in RETRYABLE_STATUS_CODES
    except (TypeError, ValueError):
        return False


def _stage_value(config: Dict[str, Any], stage: str, key: str) -> Any:
    stage_config = config.get("stage_thinking") or config.get("thinking_by_stage") or {}
    if not isinstance(stage_config, dict):
        return None
    value = stage_config.get(stage)
    if isinstance(value, dict):
        return value.get(key)
    if key in {"thinking", "enabled"} and isinstance(value, bool):
        return value
    return None


def _front_stage_provider(config: Dict[str, Any], stage: str) -> Any:
    if stage in {STAGE_VIEW_ANALYSIS, STAGE_SEMANTIC_ADJUDICATION}:
        return config.get("front_stage_provider")
    return None
