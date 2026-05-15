#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据重建上下文生成结构化零件语义。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from src.utils.llm_telemetry import default_llm_telemetry_store

from .semantic_schema import PartSemanticsValidator

logger = logging.getLogger(__name__)


class PartSemanticGenerator:
    """在生成 CAD 脚本前，先让模型解释零件结构。"""

    SYSTEM_PROMPT = """你是机械制图和三维重建专家。
你的任务不是写 FreeCAD 脚本，而是把 reconstruction_context 解释为结构化零件语义。

原则：
- 基于输入证据做判断，不要把视图旁边的位置关系误判为真实三维附加实体。
- 对二视图/三视图，先解释为同一零件的正交投影。
- 必须先决定尺寸来源：annotation、geometry 或 unresolved，并写入 dimension_source。
- 若 dimension_source=annotation，所有 key_dimensions 只能来自 dimensions 中已有的标注值，不得混入从实体坐标反算出的图形测量值。
- 若标注尺寸与图形测量明显冲突，优先写入 uncertainties，并将 dimension_source 设为 unresolved；不得一部分用标注、一部分用几何测量继续建模。
- 如果证据不足，写入 uncertainties，不要硬猜。
- additive_features 表示需要添加的凸台、肋、轴肩等。
- subtractive_features 表示孔、槽、切除等。
- 只输出 JSON，不要输出 Markdown 或推理过程。

输出 JSON 必须包含：
{
  "part_type": "零件类型字符串",
  "confidence": 0.0,
  "summary": "简短结构摘要",
  "evidence": ["支撑主解释的证据"],
  "candidate_interpretations": [
    {
      "name": "候选解释名称",
      "confidence": 0.0,
      "summary": "候选解释摘要",
      "evidence": ["该候选的证据"]
    }
  ],
  "coordinate_system": {
    "profile_plane": "XY|XZ|YZ|unknown",
    "depth_axis": "X|Y|Z|unknown",
    "reason": "坐标约定依据"
  },
  "dimension_source": "annotation|geometry|unresolved",
  "base_features": [
    {"kind": "plate|block|cylinder|profile_extrusion|other", "description": "说明", "dimensions": {}}
  ],
  "additive_features": [
    {"kind": "boss|rib|shoulder|other", "description": "说明", "dimensions": {}, "evidence": []}
  ],
  "subtractive_features": [
    {"kind": "through_hole|blind_hole|counterbore|slot|cutout|other", "description": "说明", "dimensions": {}, "evidence": []}
  ],
  "key_dimensions": [
    {"name": "尺寸名", "value": 数值, "unit": "mm"}
  ],
  "uncertainties": ["无法确认但影响建模的事项"],
  "warnings": ["建模风险或保守假设"]
}"""


    RETRY_SYSTEM_PROMPT = """你是机械制图和三维重建专家。
你的任务是把 reconstruction_summary 解释为结构化零件语义。
这是第二次请求，上一次因输出过长被截断。请输出极简 JSON，只保留建模必需字段。
砍掉 evidence、candidate_interpretations 和长 description。
uncertainties/warnings 用短句。
必须先决定 dimension_source；若尺寸来源冲突，输出 unresolved，不得混用标注值和图形测量值。

输出 JSON 必须包含（极简版）：
{
  "part_type": "零件类型字符串",
  "confidence": 0.0,
  "summary": "一句话结构摘要",
  "coordinate_system": {"profile_plane": "XY|XZ|YZ|unknown", "depth_axis": "X|Y|Z|unknown"},
  "dimension_source": "annotation|geometry|unresolved",
  "base_features": [{"kind": "...", "description": "一句话"}],
  "additive_features": [{"kind": "...", "description": "一句话", "dimensions": {}}],
  "subtractive_features": [{"kind": "...", "description": "一句话", "dimensions": {}}],
  "key_dimensions": [{"name": "尺寸名", "value": 数值, "unit": "mm"}],
  "uncertainties": ["短句"],
  "warnings": ["短句"]
}"""
    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.api_key = api_key
        self.config = config or {}
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("base_url", "https://api.deepseek.com"),
        )
        self.model = self.config.get("semantic_model") or self.config.get("model", "deepseek-v4-pro")
        self.telemetry_store = default_llm_telemetry_store(self.config)
        self.validator = PartSemanticsValidator()
        self.min_confidence = float(self.config.get("semantic_min_confidence", 0.70))

    def generate(
        self,
        reconstruction_context: Dict[str, Any],
        retry_context: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成零件语义，必要时自动重试。

        Args:
            reconstruction_context: 完整重建上下文。
            retry_context: 精简上下文，第一次被截断后用于自动重试。
        """
        result = self._generate_once(reconstruction_context, thinking=True, file_path=file_path)
        if isinstance(result, dict) and result.get("finish_reason") == "length" and retry_context:
            logger.warning(
                "语义生成响应被截断 (finish_reason=length)，使用极简 schema 重试"
            )
            result = self._generate_once(retry_context, thinking=False, file_path=file_path)
        return result

    def _generate_once(
        self,
        context: Dict[str, Any],
        thinking: bool,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """单次语义生成调用。返回语义 dict 或截断标记。"""
        use_retry = not thinking
        system_prompt = self.RETRY_SYSTEM_PROMPT if use_retry else self.SYSTEM_PROMPT
        max_tokens = int(self.config.get("semantic_max_tokens", 30000))
        temperature = 0.0 if use_retry else float(self.config.get("semantic_temperature", 0.2))

        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, indent=2)},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if thinking:
            request_payload["extra_body"] = {
                "thinking": {"type": "enabled", "reasoning_effort": "medium"}
            }

        finish_reason = ""
        call_span = self.telemetry_store.start_call(
            stage="semantic_reconstruction",
            model=self.model,
            provider="deepseek",
            request=request_payload,
            file_path=file_path,
        )
        response = None
        try:
            response = self.client.chat.completions.create(**request_payload)
            content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason or ""

            if finish_reason == "length":
                error = RuntimeError("语义生成响应被截断 (finish_reason=length)")
                call_span.finish(response=response, error=error)
                logger.warning(
                    f"{error}; retry={use_retry}, content长度={len(content)}"
                )
                return {"confidence": 0.0, "finish_reason": "length",
                        "error": str(error)}

            result = self._extract_json(content)
            if use_retry:
                result.setdefault("evidence", [])
                result.setdefault("candidate_interpretations", [])
            valid, errors = self.validator.validate(result, context)
            if not valid:
                raise ValueError("; ".join(errors))
            call_span.finish(response=response)
            logger.info(
                f"零件语义生成成功 (retry={use_retry}, finish_reason={finish_reason})"
            )
            return result
        except Exception as error:
            call_span.finish(response=response, error=error)
            logger.error(f"零件语义生成失败: {error}")
            if finish_reason == "length":
                return {"confidence": 0.0, "finish_reason": "length",
                        "error": str(error)}
            return self._fallback_semantics(str(error))

    def _fallback_semantics(self, error: str) -> Dict[str, Any]:
        return {
            "part_type": "unknown",
            "confidence": 0.0,
            "summary": "",
            "evidence": [],
            "candidate_interpretations": [],
            "coordinate_system": {
                "profile_plane": "unknown",
                "depth_axis": "unknown",
                "reason": "",
            },
            "dimension_source": "unresolved",
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "key_dimensions": [],
            "uncertainties": ["语义生成失败"],
            "warnings": [error],
        }

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
            content = content.removeprefix("json").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
            raise
