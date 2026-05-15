#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate structured part semantics from reconstruction context."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from src.utils.llm_telemetry import default_llm_telemetry_store

from .semantic_schema import PartSemanticsValidator

logger = logging.getLogger(__name__)


class PartSemanticGenerator:
    """Ask the model to explain the part before any CAD script is generated."""

    SYSTEM_PROMPT = """你是机械制图和三维重建专家。
你的任务不是写 FreeCAD 脚本，而是把 reconstruction_context 解释为结构化零件语义。

原则：
- 基于输入证据做判断，不要把视图旁边的位置关系误判为真实三维附加实体。
- 对二视图/三视图，先解释为同一零件的正交投影。
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

    def generate(self, reconstruction_context: Dict[str, Any]) -> Dict[str, Any]:
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(reconstruction_context, ensure_ascii=False, indent=2)},
            ],
            "max_tokens": int(self.config.get("semantic_max_tokens", 6000)),
        }
        call_span = self.telemetry_store.start_call(
            stage="semantic_reconstruction",
            model=self.model,
            provider="deepseek",
            request=request_payload,
            file_path=None,
        )
        try:
            response = self.client.chat.completions.create(**request_payload)
            call_span.finish(response=response)
            content = response.choices[0].message.content or ""
            result = self._extract_json(content)
            valid, errors = self.validator.validate(result)
            if not valid:
                raise ValueError("; ".join(errors))
            logger.info("零件语义生成成功")
            return result
        except Exception as error:
            call_span.finish(error=error)
            logger.error(f"零件语义生成失败: {error}")
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
            "base_features": [],
            "additive_features": [],
            "subtractive_features": [],
            "key_dimensions": [],
            "uncertainties": ["semantic generation failed"],
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
