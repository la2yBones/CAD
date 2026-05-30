#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于可追溯图纸证据的 LLM 语义裁决。"""
from __future__ import annotations

import json
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from src.utils.deepseek_options import (
    STAGE_SEMANTIC_ADJUDICATION,
    api_key_from_env,
    apply_stage_request_options,
    client_timeout,
    llm_provider,
)
from src.utils.llm_telemetry import default_llm_telemetry_store
from src.utils.stage_self_correction import SelfCorrectionRequest

logger = logging.getLogger(__name__)


class SemanticAdjudicationValidator:
    """在后续阶段消费语义裁决前校验交接数据。"""

    REQUIRED_LIST_FIELDS = (
        "view_roles",
        "dimension_roles",
        "feature_roles",
        "derived_dimensions",
        "clarification_questions",
        "uncertainties",
        "warnings",
    )

    def validate(
        self,
        result: Dict[str, Any],
        evidence_package: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        if not isinstance(result, dict):
            return False, ["semantic_adjudication 必须是对象"]
        confidence = result.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            errors.append("confidence 必须是 0 到 1 之间的数值")
        for field in self.REQUIRED_LIST_FIELDS:
            if field not in result:
                errors.append(f"缺少字段: {field}")
            elif not isinstance(result.get(field), list):
                errors.append(f"{field} 必须是列表")

        valid_ids = self._valid_evidence_ids(evidence_package)
        valid_by_field = self._valid_evidence_ids_by_field(evidence_package)
        id_fields = {
            "view_roles": ("view_id", "view_candidates"),
            "dimension_roles": ("dimension_id", "dimension_candidates"),
            "feature_roles": ("feature_id", "geometry_candidates"),
        }
        for result_field, (id_field, evidence_field) in id_fields.items():
            valid_for_field = valid_by_field.get(evidence_field, set())
            for item in result.get(result_field, []) or []:
                item_id = item.get(id_field)
                if item_id and str(item_id) not in valid_for_field:
                    errors.append(
                        f"{result_field}.{id_field} 引用了不存在的证据 ID: {item_id}"
                    )
        for field in ("view_roles", "dimension_roles", "feature_roles"):
            for item in result.get(field, []) or []:
                for ref in item.get("evidence_ids", []) or []:
                    if ref not in valid_ids:
                        errors.append(f"{field} 引用了不存在的证据 ID: {ref}")
        for item in result.get("derived_dimensions", []) or []:
            ref = item.get("source_derived_dimension_id")
            valid_derived_ids = valid_by_field.get("derived_dimension_candidates", set())
            if ref and str(ref) not in valid_derived_ids:
                errors.append(f"derived_dimensions 引用了不存在的证据 ID: {ref}")
            for evidence_id in item.get("evidence_ids", []) or []:
                if evidence_id not in valid_ids:
                    errors.append(
                        f"derived_dimensions.evidence_ids 引用了不存在的证据 ID: {evidence_id}"
                    )
        return not errors, errors

    @staticmethod
    def _valid_evidence_ids(evidence_package: Dict[str, Any]) -> set[str]:
        valid = set()
        for ids in SemanticAdjudicationValidator._valid_evidence_ids_by_field(
            evidence_package
        ).values():
            valid.update(ids)
        return valid

    @staticmethod
    def _valid_evidence_ids_by_field(
        evidence_package: Dict[str, Any],
    ) -> Dict[str, set[str]]:
        valid: Dict[str, set[str]] = {}
        for field in (
            "view_candidates",
            "dimension_candidates",
            "derived_dimension_candidates",
            "geometry_candidates",
            "spatial_relations",
        ):
            valid[field] = set()
            for item in evidence_package.get(field, []) or []:
                item_id = item.get("id")
                if item_id:
                    valid[field].add(str(item_id))
        return valid


class LLMSemanticAdjudicator:
    """请求模型裁决视图、尺寸和特征语义。"""

    SYSTEM_PROMPT = """你是机械制图语义裁决专家。
你的任务是基于 drawing_evidence_package 判断工程图中的视图角色、尺寸角色、特征角色、派生尺寸和是否需要追问。

关键纪律：
- drawing_evidence_package 中的 local_name_hint 只是本地弱提示，不是最终视图角色。
- 只能引用 evidence package 中存在的 V/D/DD/G/R ID。
- 可以输出最终语义角色，但必须给 evidence_ids。
- 如果需要使用派生尺寸，必须引用 derived_dimension_candidates 中的 DD ID；不得凭空写新数值。
- 如果主体外形、主要体量、方向或关键尺寸来源仍不闭合，应生成 clarification_questions。
- 不要写 FreeCAD 脚本，不要输出建模步骤，不要输出 Markdown 或推理过程。
- 所有面向用户阅读的自然语言字段必须使用中文。

输出必须是合法 JSON 对象，格式示例：
{
  "confidence": 0.0,
  "view_roles": [
    {
      "view_id": "V1",
      "role": "main|top|bottom|left|right|section|unknown",
      "confidence": 0.0,
      "evidence_ids": ["V1", "R1"],
      "reason": "中文理由",
      "overrode_local_hint": false
    }
  ],
  "dimension_roles": [
    {
      "dimension_id": "D1",
      "role": "profile_length|profile_height|extrusion_depth|thread_length|hole_diameter|radius|chamfer|construction|unresolved",
      "confidence": 0.0,
      "evidence_ids": ["D1", "V1"],
      "reason": "中文理由"
    }
  ],
  "feature_roles": [
    {
      "feature_id": "G1",
      "role": "outer_profile|axis|through_hole|blind_hole|boss|fillet|chamfer|thread|construction|unknown",
      "confidence": 0.0,
      "evidence_ids": ["G1", "D1"],
      "reason": "中文理由"
    }
  ],
  "derived_dimensions": [
    {
      "source_derived_dimension_id": "DD1",
      "role": "feature_height|overall_length|construction|unresolved",
      "value": 0.0,
      "confidence": 0.0,
      "evidence_ids": ["DD1"],
      "reason": "中文理由"
    }
  ],
  "clarification_questions": [],
  "uncertainties": [],
  "warnings": []
}"""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.base_url = (
            self.config.get("semantic_adjudication_base_url")
            or self.config.get("front_stage_base_url")
            or self.config.get("base_url", "https://api.deepseek.com")
        )
        self.model = (
            self.config.get("semantic_adjudication_model")
            or self.config.get("semantic_model")
            or self.config.get("model", "deepseek-v4-pro")
        )
        self.provider = llm_provider(
            {
                **self.config,
                "provider": (
                    self.config.get("semantic_adjudication_provider")
                    or self.config.get("front_stage_provider")
                    or self.config.get("provider")
                ),
            },
            stage=STAGE_SEMANTIC_ADJUDICATION,
            model=self.model,
            base_url=self.base_url,
        )
        self.api_key = (
            self.config.get("semantic_adjudication_api_key")
            or self.config.get("front_stage_api_key")
            or (
                api_key_from_env("MOONSHOT_API_KEY", "KIMI_API_KEY")
                if self.provider in {"moonshot", "kimi"}
                else ""
            )
            or api_key
        )
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=client_timeout(self.config),
        )
        self.enable_multimodal = bool(
            self.config.get("enable_multimodal_semantic_adjudication_input")
            or self.config.get("enable_multimodal_front_stage_input", False)
        )
        self.max_images = int(self.config.get("semantic_adjudication_max_images", 1))
        self.telemetry_store = default_llm_telemetry_store(self.config)
        self.validator = SemanticAdjudicationValidator()

    def adjudicate(
        self,
        adjudicated_context: Dict[str, Any],
        file_path: Optional[str] = None,
        preview_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        evidence_package = self._evidence_package(adjudicated_context)
        if not evidence_package:
            return self._fallback("缺少 drawing_evidence_package，跳过大模型语义裁决")

        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_message_content(
                        evidence_package,
                        adjudicated_context.get("semantic_adjudication_clarification"),
                        preview_path=preview_path,
                    ),
                },
            ],
            "max_tokens": int(self.config.get("semantic_adjudication_max_tokens", 12000)),
            "temperature": float(self.config.get("semantic_adjudication_temperature", 0.0)),
            "response_format": {"type": "json_object"},
        }
        request_payload = apply_stage_request_options(
            request_payload,
            self._stage_request_config(),
            stage=STAGE_SEMANTIC_ADJUDICATION,
            default_thinking=False,
            default_effort="high",
            legacy_thinking_keys=("semantic_adjudication_thinking",),
            legacy_effort_keys=("semantic_adjudication_reasoning_effort",),
        )

        call_span = self.telemetry_store.start_call(
            stage=STAGE_SEMANTIC_ADJUDICATION,
            model=self.model,
            provider=getattr(self, "provider", "deepseek"),
            request=request_payload,
            file_path=file_path,
        )
        response = None
        try:
            response = self.client.chat.completions.create(**request_payload)
            message = response.choices[0].message
            content = message.content or ""
            if not content:
                content = getattr(message, "reasoning_content", None) or ""
            result = self._extract_json(content)
            valid, errors = self.validator.validate(result, evidence_package)
            if not valid:
                raise ValueError("; ".join(errors))
            call_span.finish(response=response)
            logger.info("图纸语义裁决成功")
            return self._with_defaults(result)
        except Exception as error:
            call_span.finish(response=response, error=error)
            logger.error(f"图纸语义裁决失败: {error}")
            return self._fallback(str(error))

    def generate_from_self_correction(
        self,
        correction_request: SelfCorrectionRequest,
        *,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据阶段内自纠请求重新生成图纸语义裁决。"""
        evidence_package = correction_request.stage_payload.get("drawing_evidence_package")
        if not isinstance(evidence_package, dict) or not evidence_package:
            return self._fallback("模型自纠缺少 drawing_evidence_package，无法重新裁决")

        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_self_correction_user_content(
                        correction_request
                    ),
                },
            ],
            "max_tokens": int(self.config.get("semantic_adjudication_max_tokens", 12000)),
            "temperature": float(self.config.get("semantic_adjudication_temperature", 0.0)),
            "response_format": {"type": "json_object"},
        }
        request_payload = apply_stage_request_options(
            request_payload,
            self._stage_request_config(),
            stage=STAGE_SEMANTIC_ADJUDICATION,
            default_thinking=False,
            default_effort="high",
            legacy_thinking_keys=("semantic_adjudication_thinking",),
            legacy_effort_keys=("semantic_adjudication_reasoning_effort",),
        )
        call_span = self.telemetry_store.start_call(
            stage=STAGE_SEMANTIC_ADJUDICATION,
            model=self.model,
            provider=getattr(self, "provider", "deepseek"),
            request=request_payload,
            file_path=file_path,
        )
        response = None
        try:
            response = self.client.chat.completions.create(**request_payload)
            message = response.choices[0].message
            content = message.content or getattr(message, "reasoning_content", None) or ""
            result = self._extract_json(content)
            valid, errors = self.validator.validate(result, evidence_package)
            if not valid:
                raise ValueError("; ".join(errors))
            call_span.finish(response=response)
            logger.info("图纸语义裁决模型自纠成功")
            return self._with_defaults(result)
        except Exception as error:
            call_span.finish(response=response, error=error)
            logger.error(f"图纸语义裁决模型自纠失败: {error}")
            return self._fallback(str(error))

    @staticmethod
    def _evidence_package(context: Dict[str, Any]) -> Dict[str, Any]:
        semantic_policy = context.get("semantic_policy", {}) or {}
        package = semantic_policy.get("drawing_evidence_package")
        if isinstance(package, dict):
            return package
        package = context.get("drawing_evidence_package")
        return package if isinstance(package, dict) else {}

    @staticmethod
    def _build_user_content(
        evidence_package: Dict[str, Any],
        clarification: Optional[Dict[str, Any]] = None,
    ) -> str:
        parts = [
            "请基于以下 drawing_evidence_package 输出语义裁决 JSON：",
            "=== drawing_evidence_package ===",
            json.dumps(evidence_package, ensure_ascii=False, indent=2),
        ]
        if clarification:
            parts.extend([
                "=== 用户对上一次语义裁决追问的回答 ===",
                json.dumps(clarification, ensure_ascii=False, indent=2),
                "请在不覆盖图纸事实和证据 ID 约束的前提下使用这些回答更新语义裁决。",
            ])
        return "\n\n".join(parts)

    def _build_user_message_content(
        self,
        evidence_package: Dict[str, Any],
        clarification: Optional[Dict[str, Any]] = None,
        *,
        preview_path: Optional[str] = None,
    ) -> Any:
        text = self._build_user_content(evidence_package, clarification)
        if not getattr(self, "enable_multimodal", False):
            return text
        content: List[Dict[str, Any]] = []
        for image_path in self._collect_image_paths(preview_path):
            data_url = self._image_to_data_url(image_path)
            if data_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
        content.append({"type": "text", "text": text})
        return content

    def _collect_image_paths(self, preview_path: Optional[str]) -> List[str]:
        if not preview_path:
            return []
        return [preview_path][: int(getattr(self, "max_images", 1))]

    @staticmethod
    def _image_to_data_url(image_path: str) -> Optional[str]:
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            logger.warning(f"语义裁决多模态图片不存在，已跳过: {image_path}")
            return None
        mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as error:
            logger.warning(f"读取语义裁决多模态图片失败，已跳过 {image_path}: {error}")
            return None
        return f"data:{mime_type};base64,{encoded}"

    def _stage_request_config(self) -> Dict[str, Any]:
        config = dict(self.config)
        config["provider"] = getattr(
            self,
            "provider",
            llm_provider(config, stage=STAGE_SEMANTIC_ADJUDICATION, model=getattr(self, "model", "")),
        )
        return config

    @staticmethod
    def _build_self_correction_user_content(
        correction_request: SelfCorrectionRequest,
    ) -> str:
        return "\n\n".join([
            "请执行图纸语义裁决阶段的模型自纠，并只输出一个合法 JSON 对象。",
            "不要输出推理过程、Markdown 或额外解释。",
            "只能使用 self_correction_request.stage_payload.drawing_evidence_package 中的证据 ID。",
            "必须修复 validation_issues 中列出的问题；如果仍不确定，请用 clarification_questions、uncertainties 或 warnings 表达。",
            "=== self_correction_request ===",
            json.dumps(correction_request.to_dict(), ensure_ascii=False, indent=2),
        ])

    @staticmethod
    def _with_defaults(result: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(result)
        result.setdefault("status", "completed")
        result.setdefault("confidence", 0.0)
        for field in SemanticAdjudicationValidator.REQUIRED_LIST_FIELDS:
            result.setdefault(field, [])
        return result

    @staticmethod
    def _fallback(warning: str) -> Dict[str, Any]:
        return {
            "status": "failed",
            "confidence": 0.0,
            "view_roles": [],
            "dimension_roles": [],
            "feature_roles": [],
            "derived_dimensions": [],
            "clarification_questions": [],
            "uncertainties": [],
            "warnings": [warning],
        }

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any]:
        content = (content or "").strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            )
            content = content.removeprefix("json").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
            raise
