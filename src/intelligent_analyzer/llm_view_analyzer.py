#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 辅助的工程视图分析器。

本模块以现有规则分析器作为初判，再请求大模型校正装配图、二视图、三视图和剖视图等图纸语义。
"""
from __future__ import annotations

import json
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.utils.deepseek_options import (
    STAGE_VIEW_ANALYSIS,
    api_key_from_env,
    apply_stage_request_options,
    client_timeout,
    llm_provider,
)
from src.utils.llm_telemetry import default_llm_telemetry_store
from src.utils.stage_self_correction import SelfCorrectionRequest

from .view_decision_payload import build_view_decision_payload
from .view_schema import (
    ViewAnalysisValidator,
    build_standard_view_analysis,
)

logger = logging.getLogger(__name__)


class LLMViewAnalyzer:
    """使用 LLM 校验并校正本地工程视图分析。"""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.model = self.config.get("view_model") or self.config.get("model", "deepseek-chat")
        self.base_url = (
            self.config.get("view_base_url")
            or self.config.get("front_stage_base_url")
            or self.config.get("base_url", "https://api.deepseek.com")
        )
        self.provider = llm_provider(
            {
                **self.config,
                "provider": (
                    self.config.get("view_provider")
                    or self.config.get("front_stage_provider")
                    or self.config.get("provider")
                ),
            },
            stage=STAGE_VIEW_ANALYSIS,
            model=self.model,
            base_url=self.base_url,
        )
        self.api_key = (
            self.config.get("view_api_key")
            or self.config.get("front_stage_api_key")
            or (
                api_key_from_env("MOONSHOT_API_KEY", "KIMI_API_KEY")
                if self.provider in {"moonshot", "kimi"}
                else ""
            )
            or api_key
        )
        self.enabled = bool(self.config.get("enable_llm_view_analysis", True))
        self.enable_multimodal = bool(
            self.config.get("enable_multimodal_view_input")
            or self.config.get("enable_multimodal_front_stage_input", False)
        )
        self.confidence_threshold = float(self.config.get("view_confidence_threshold", 0.60))
        self.validator = ViewAnalysisValidator(self.confidence_threshold)
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=client_timeout(self.config),
        )
        self.telemetry_store = default_llm_telemetry_store(self.config)

    def refine_view_analysis(
        self,
        geometry_data: Dict[str, Any],
        rule_result: Dict[str, Any],
        dimension_data: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        preview_path: Optional[str] = None,
        media_inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """返回 LLM 校正后的视图分析，或标准化后的规则结果。"""
        rule_standard = build_standard_view_analysis(
            rule_result,
            confidence=0.72,
            reason_summary="本地规则初判结果，作为大模型校正的回退结果",
            source="rule",
        )

        if not self.enabled:
            logger.info("LLM视图校正未启用，使用本地规则结果")
            return self._merge_with_legacy(rule_standard, rule_result)

        try:
            prompt = self._build_prompt(
                geometry_data=geometry_data,
                rule_result=rule_result,
                rule_standard=rule_standard,
                dimension_data=dimension_data,
                file_path=file_path,
                preview_path=preview_path,
                media_inputs=media_inputs,
            )
            messages = self._build_messages(prompt, preview_path, media_inputs)

            logger.info("开始LLM视图语义校正")
            request_payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": int(self.config.get("view_max_tokens", 4096)),
                "temperature": float(self.config.get("view_temperature", 0.1)),
                "response_format": {"type": "json_object"},
            }
            disable_view_thinking = self.config.get("view_disable_thinking", True)
            request_payload = apply_stage_request_options(
                request_payload,
                self._stage_request_config(),
                stage=STAGE_VIEW_ANALYSIS,
                default_thinking=not bool(disable_view_thinking),
                default_effort="high",
            )
            call_span = self.telemetry_store.start_call(
                stage=STAGE_VIEW_ANALYSIS,
                model=self.model,
                provider=getattr(self, "provider", "deepseek"),
                request=request_payload,
                file_path=file_path,
            )
            try:
                response = self.client.chat.completions.create(**request_payload)
                call_span.finish(response=response)
            except Exception as call_error:
                call_span.finish(error=call_error)
                raise

            content = response.choices[0].message.content or ""
            logger.info(f"LLM视图校正响应长度: {len(content)}")
            llm_result = self._normalize_view_schema_lists(self._extract_json(content))
            llm_result.setdefault("source", "llm")

            valid, errors = self.validator.validate(llm_result, geometry_data)
            if not valid:
                logger.warning(f"LLM视图校正结果未通过校验: {'; '.join(errors)}")
                corrected = self._auto_self_correct(
                    llm_result=llm_result,
                    geometry_data=geometry_data,
                    rule_result=rule_result,
                    rule_standard=rule_standard,
                    dimension_data=dimension_data,
                    file_path=file_path,
                    validation_errors=errors,
                )
                if corrected is not None:
                    return self._merge_with_legacy(corrected, rule_result)
                logger.warning("视图语义自动自纠未成功，回退本地规则")
                rule_standard["warnings"].append("LLM视图校正校验失败，已回退本地规则")
                rule_standard["validation_errors"] = errors
                return self._merge_with_legacy(rule_standard, rule_result)

            logger.info(
                "LLM视图校正通过: "
                f"drawing_type={llm_result.get('drawing_type')}, "
                f"views={len(llm_result.get('views', []))}, "
                f"confidence={llm_result.get('confidence')}"
            )
            return self._merge_with_legacy(llm_result, rule_result)

        except Exception as e:
            logger.warning(f"LLM视图校正失败，回退本地规则: {e}")
            rule_standard["warnings"].append(f"LLM视图校正失败: {e}")
            return self._merge_with_legacy(rule_standard, rule_result)

    def _auto_self_correct(
        self,
        *,
        llm_result: Dict[str, Any],
        geometry_data: Dict[str, Any],
        rule_result: Dict[str, Any],
        rule_standard: Dict[str, Any],
        dimension_data: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        validation_errors: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        max_rounds = 2
        current_result = llm_result
        current_errors = validation_errors or []
        for round_index in range(1, max_rounds + 1):
            logger.info(
                "视图语义自动自纠第 %s/%s 轮 | 原因: %s",
                round_index,
                max_rounds,
                "; ".join(current_errors[:3]),
            )
            correction_request = SelfCorrectionRequest(
                stage="view_analysis",
                round_index=round_index,
                max_rounds=max_rounds,
                stage_payload=build_view_decision_payload(
                    geometry_data=geometry_data,
                    rule_result=rule_result,
                    rule_standard=rule_standard,
                    dimension_data=dimension_data,
                    file_path=file_path,
                    confidence_threshold=self.confidence_threshold,
                ),
                previous_output=current_result,
                validation_issues=_build_view_validation_issues(current_errors),
                output_contract={
                    "required_fields": [
                        "analysis_id", "timestamp", "drawing_type", "views",
                        "relationships", "confidence", "evidence", "reason_summary",
                        "warnings",
                    ],
                    "evidence_must_be_array": True,
                },
                correction_goal=f"修复视图语义校验失败的问题：{'; '.join(current_errors[:3])}",
            )
            try:
                corrected = self.generate_from_self_correction(
                    correction_request,
                    geometry_data=geometry_data,
                    rule_result=rule_result,
                    file_path=file_path,
                )
                valid, errors = self.validator.validate(corrected, geometry_data)
                if valid:
                    logger.info("视图语义自动自纠第 %s 轮成功", round_index)
                    corrected.setdefault("warnings", [])
                    corrected["warnings"].append(
                        f"视图语义校验失败后自动自纠成功（第{round_index}轮）"
                    )
                    return corrected
                logger.warning(
                    "视图语义自动自纠第 %s 轮后仍校验失败: %s",
                    round_index,
                    "; ".join(errors[:3]),
                )
                current_result = corrected
                current_errors = errors
            except Exception as error:
                logger.warning("视图语义自动自纠第 %s 轮异常: %s", round_index, error)
        return None

    def generate_from_self_correction(
        self,
        correction_request: SelfCorrectionRequest,
        *,
        geometry_data: Dict[str, Any],
        rule_result: Dict[str, Any],
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据阶段内自纠请求重新生成视图语义校正结果。"""
        if not self.enabled:
            rule_standard = build_standard_view_analysis(
                rule_result,
                confidence=0.72,
                reason_summary="LLM视图校正未启用，模型自纠回退本地规则结果",
                source="rule",
            )
            return self._merge_with_legacy(rule_standard, rule_result)

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": self._build_self_correction_prompt(correction_request),
            },
        ]
        request_payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(self.config.get("view_max_tokens", 4096)),
            "temperature": float(self.config.get("view_temperature", 0.1)),
            "response_format": {"type": "json_object"},
        }
        disable_view_thinking = self.config.get("view_disable_thinking", True)
        request_payload = apply_stage_request_options(
            request_payload,
            self._stage_request_config(),
            stage=STAGE_VIEW_ANALYSIS,
            default_thinking=not bool(disable_view_thinking),
            default_effort="high",
        )
        call_span = self.telemetry_store.start_call(
            stage=STAGE_VIEW_ANALYSIS,
            model=self.model,
            provider=getattr(self, "provider", "deepseek"),
            request=request_payload,
            file_path=file_path,
        )
        response = None
        try:
            response = self.client.chat.completions.create(**request_payload)
            content = response.choices[0].message.content or ""
            llm_result = self._normalize_view_schema_lists(self._extract_json(content))
            llm_result.setdefault("source", "llm_self_correction")
            valid, errors = self.validator.validate(llm_result, geometry_data)
            if not valid:
                raise ValueError("; ".join(errors))
            call_span.finish(response=response)
            return self._merge_with_legacy(llm_result, rule_result)
        except Exception as error:
            call_span.finish(response=response, error=error)
            rule_standard = build_standard_view_analysis(
                rule_result,
                confidence=0.72,
                reason_summary="视图语义模型自纠失败，回退本地规则结果",
                warnings=[f"视图语义模型自纠失败: {error}"],
                source="rule",
            )
            return self._merge_with_legacy(rule_standard, rule_result)

    def _system_prompt(self) -> str:
        return (
            "你是CAD工程图视图分析专家。你的任务是校正本地规则引擎的视图识别结果。"
            "只能输出一个JSON对象，不要输出Markdown。"
            "不要输出完整思维链，只输出reason_summary、evidence和warnings。"
            "必须遵守输入中的output_contract字段。"
            "drawing_type只能是single_view、two_view、three_view、assembly_drawing、"
            "section_view、unknown之一。"
            "装配图/总装图通常应作为assembly_drawing或single_view，不要因为零件区域分散就拆成多视图。"
            "二视图通常包含main+top或main+right。三视图通常包含main+top/right或main+bottom/right。"
        )

    def _build_prompt(
        self,
        geometry_data: Dict[str, Any],
        rule_result: Dict[str, Any],
        rule_standard: Dict[str, Any],
        dimension_data: Optional[Dict[str, Any]],
        file_path: Optional[str],
        preview_path: Optional[str],
        media_inputs: Optional[Dict[str, Any]],
    ) -> str:
        payload = build_view_decision_payload(
            geometry_data=geometry_data,
            rule_result=rule_result,
            rule_standard=rule_standard,
            dimension_data=dimension_data,
            file_path=file_path,
            confidence_threshold=self.confidence_threshold,
        )
        prompt = json.dumps(payload, ensure_ascii=False, indent=2)
        return prompt

    def _build_self_correction_prompt(
        self,
        correction_request: SelfCorrectionRequest,
    ) -> str:
        payload = correction_request.to_dict()
        return "\n\n".join([
            "请执行视图语义校正阶段的模型自纠，并只输出一个合法 JSON 对象。",
            "不要输出推理过程、Markdown 或额外解释。",
            "只能使用 self_correction_request.stage_payload 中的图纸证据和 previous_output 中的上一次输出摘要。",
            "必须逐项修复 validation_issues 中列出的问题；如果无法修复，warnings 中说明风险，但仍需输出符合 output_contract 的 JSON。",
            "=== self_correction_request ===",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ])

    def _build_messages(
        self,
        prompt: str,
        preview_path: Optional[str],
        media_inputs: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        system_message = {
            "role": "system",
            "content": self._system_prompt(),
        }

        if not self.enable_multimodal:
            return [system_message, {"role": "user", "content": prompt}]

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        image_paths = self._collect_image_paths(preview_path, media_inputs)
        for image_path in image_paths:
            data_url = self._image_to_data_url(image_path)
            if data_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })

        return [system_message, {"role": "user", "content": content}]

    def _stage_request_config(self) -> Dict[str, Any]:
        config = dict(self.config)
        config["provider"] = getattr(
            self,
            "provider",
            llm_provider(config, stage=STAGE_VIEW_ANALYSIS, model=getattr(self, "model", "")),
        )
        return config

    def _collect_image_paths(
        self,
        preview_path: Optional[str],
        media_inputs: Optional[Dict[str, Any]],
    ) -> List[str]:
        media_inputs = media_inputs or {}
        paths: List[str] = []
        if preview_path:
            paths.append(preview_path)
        paths.extend(str(p) for p in media_inputs.get("images", []) or [])
        return paths[: int(self.config.get("view_max_images", 4))]

    def _image_to_data_url(self, image_path: str) -> Optional[str]:
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            logger.warning(f"多模态图片不存在，已跳过: {image_path}")
            return None

        mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as e:
            logger.warning(f"读取多模态图片失败，已跳过 {image_path}: {e}")
            return None

        return f"data:{mime_type};base64,{encoded}"

    def _extract_json(self, content: str) -> Dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if len(lines) > 1 and lines[-1].strip() == "```":
                content = "\n".join(lines[1:-1])
            elif len(lines) > 1:
                content = "\n".join(lines[1:])
            content = content.removeprefix("json").strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start:end + 1])

        raise ValueError(f"无法从LLM视图校正响应中提取JSON，前200字符: {content[:200]}")

    def _normalize_view_schema_lists(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """把 LLM 常见的单字符串列表字段规范化，避免为可修复格式问题触发重调用。"""
        if not isinstance(result, dict):
            return result
        normalized = dict(result)
        for key in ("evidence", "warnings"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized[key] = [value]
            elif value is None:
                normalized[key] = []
        return normalized

    def _merge_with_legacy(
        self,
        standard_result: Dict[str, Any],
        rule_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """在补充 schema 输出的同时，保留旧调用方期望的兼容键。"""
        merged = dict(rule_result)
        merged["schema_result"] = standard_result
        merged["drawing_type"] = standard_result.get("drawing_type")
        merged["analysis_id"] = standard_result.get("analysis_id")
        merged["timestamp"] = standard_result.get("timestamp")
        merged["confidence"] = standard_result.get("confidence")
        merged["evidence"] = standard_result.get("evidence", [])
        merged["reason_summary"] = standard_result.get("reason_summary", "")
        merged["warnings"] = standard_result.get("warnings", [])
        merged["detection_method"] = standard_result.get(
            "source",
            rule_result.get("detection_method", "unknown")
        )

        schema_views = standard_result.get("views", [])
        if schema_views:
            legacy_by_name = {view.get("name"): view for view in rule_result.get("views", []) or []}
            legacy_views = []
            for schema_view in schema_views:
                base = dict(legacy_by_name.get(schema_view.get("name"), {}))
                base.update({
                    "object_id": schema_view.get("object_id"),
                    "name": schema_view.get("name", base.get("name", "unknown")),
                    "type": schema_view.get("label", base.get("type", "unknown")),
                    "bbox": schema_view.get("bbox", base.get("bbox")),
                    "confidence": schema_view.get("confidence"),
                    "entity_count": schema_view.get("entity_count", base.get("entity_count", 0)),
                })
                legacy_views.append(base)
            merged["views"] = legacy_views

        schema_relationships = standard_result.get("relationships", [])
        if schema_relationships:
            merged["relationships"] = [
                {
                    "object_id": rel.get("object_id"),
                    "type": rel.get("type"),
                    "views": rel.get("views", []),
                    "confidence": rel.get("confidence"),
                    "description": rel.get("evidence", ""),
                }
                for rel in schema_relationships
            ]

        return merged


def _build_view_validation_issues(errors: List[str]) -> list:
    from src.utils.stage_self_correction import ValidationIssue

    if not errors:
        return [ValidationIssue(
            code="view_validation_unknown",
            message="视图语义校验失败",
            severity="error",
            fixable=True,
            impact="视图语义结构不满足输出合同",
            correction_target="修复校验失败的字段并重新生成",
        )]
    issues = []
    for index, error in enumerate(errors[:6], start=1):
        text = str(error).strip()
        if not text:
            continue
        issues.append(ValidationIssue(
            code=f"view_validation_{index}",
            message=text,
            severity="error",
            fixable=True,
            impact="视图语义结构不满足输出合同",
            correction_target="修复校验失败的字段并重新生成",
            details={"original_error": text},
        ))
    return issues
