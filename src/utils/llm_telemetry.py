#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 调用遥测存储和辅助工具。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


class LLMTelemetryStore:
    """Append-only JSONL store for large-model request/response metrics."""

    def __init__(self, telemetry_dir: str = ".cache/llm_telemetry", max_detail_chars: Optional[int] = None):
        self.telemetry_dir = Path(telemetry_dir)
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.telemetry_dir / "llm_calls.jsonl"
        self.max_detail_chars = max_detail_chars

    def start_call(
        self,
        *,
        stage: str,
        model: str,
        provider: str,
        request: Dict[str, Any],
        file_path: Optional[str] = None,
    ) -> "LLMCallSpan":
        return LLMCallSpan(
            store=self,
            stage=stage,
            model=model,
            provider=provider,
            request=request,
            file_path=file_path,
        )

    def append(self, record: Dict[str, Any]) -> None:
        record = self._truncate_record(record)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = deque(f, maxlen=max(1, limit))
        except Exception as e:
            logger.warning(f"读取LLM调用记录失败: {e}")
            return []

        records: List[Dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def _truncate_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not self.max_detail_chars:
            return record
        raw = json.dumps(record, ensure_ascii=False)
        if len(raw) <= self.max_detail_chars:
            return record

        compact = dict(record)
        compact["truncated"] = True
        compact["request"] = self._truncate_value(compact.get("request"))
        compact["response"] = self._truncate_value(compact.get("response"))
        compact["error"] = self._truncate_value(compact.get("error"))
        return compact

    def _truncate_value(self, value: Any) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= self.max_detail_chars // 2:
            return value
        return {
            "_truncated": True,
            "preview": text[: self.max_detail_chars // 2],
            "original_chars": len(text),
        }


class LLMCallSpan:
    """Context-like object that records one LLM call when finished."""

    def __init__(
        self,
        *,
        store: LLMTelemetryStore,
        stage: str,
        model: str,
        provider: str,
        request: Dict[str, Any],
        file_path: Optional[str],
    ):
        self.store = store
        self.stage = stage
        self.model = model
        self.provider = provider
        self.request = request
        self.file_path = file_path
        self.call_id = str(uuid.uuid4())
        self.started_at = time.perf_counter()
        self.started_iso = datetime.now(timezone.utc).isoformat()

    def finish(self, response: Any = None, error: Optional[BaseException] = None) -> Dict[str, Any]:
        duration = max(time.perf_counter() - self.started_at, 0.000001)
        response_dict = _to_plain_data(response)
        usage = _extract_usage(response_dict, response)
        completion_tokens = usage.get("completion_tokens") or 0
        token_rate = completion_tokens / duration if completion_tokens else 0.0

        record = {
            "call_id": self.call_id,
            "timestamp": self.started_iso,
            "stage": self.stage,
            "provider": self.provider,
            "model": self.model,
            "file_path": self.file_path,
            "status": "error" if error else "ok",
            "duration_seconds": round(duration, 4),
            "tokens": usage,
            "token_rate_completion_per_second": round(token_rate, 4),
            "request": self.request,
            "response": response_dict,
            "error": str(error) if error else None,
        }
        self.store.append(record)
        return record


def default_llm_telemetry_store(config: Optional[Dict[str, Any]] = None) -> LLMTelemetryStore:
    config = config or {}
    telemetry_dir = (
        config.get("llm_telemetry_dir")
        or config.get("telemetry_dir")
        or ".cache/llm_telemetry"
    )
    return LLMTelemetryStore(str(telemetry_dir))


def summarize_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    records = list(records)
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    total_duration = 0.0
    by_stage: Dict[str, Dict[str, Any]] = {}

    for record in records:
        tokens = record.get("tokens") or {}
        prompt = int(tokens.get("prompt_tokens") or 0)
        completion = int(tokens.get("completion_tokens") or 0)
        total = int(tokens.get("total_tokens") or prompt + completion)
        duration = float(record.get("duration_seconds") or 0.0)
        stage = str(record.get("stage") or "unknown")

        total_prompt += prompt
        total_completion += completion
        total_tokens += total
        total_duration += duration

        item = by_stage.setdefault(stage, {
            "count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_seconds": 0.0,
        })
        item["count"] += 1
        item["prompt_tokens"] += prompt
        item["completion_tokens"] += completion
        item["total_tokens"] += total
        item["duration_seconds"] = round(item["duration_seconds"] + duration, 4)

    return {
        "call_count": len(records),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "duration_seconds": round(total_duration, 4),
        "completion_tokens_per_second": round(total_completion / total_duration, 4) if total_duration else 0.0,
        "by_stage": by_stage,
    }


def _to_plain_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def _extract_usage(response_dict: Any, response_obj: Any) -> Dict[str, int]:
    usage: Any = None
    if isinstance(response_dict, dict):
        usage = response_dict.get("usage")
    if usage is None and response_obj is not None:
        usage = getattr(response_obj, "usage", None)

    usage_dict = _to_plain_data(usage) if usage is not None else {}
    if not isinstance(usage_dict, dict):
        usage_dict = {}

    prompt_tokens = int(usage_dict.get("prompt_tokens") or 0)
    completion_tokens = int(usage_dict.get("completion_tokens") or 0)
    total_tokens = int(usage_dict.get("total_tokens") or prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
