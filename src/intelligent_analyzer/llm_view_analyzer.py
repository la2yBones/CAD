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

from src.utils.llm_telemetry import default_llm_telemetry_store

from .view_decision_payload import build_view_decision_payload
from .view_schema import (
    ViewAnalysisValidator,
    build_standard_view_analysis,
)

logger = logging.getLogger(__name__)


class LLMViewAnalyzer:
    """使用 LLM 校验并校正本地工程视图分析。"""

    def __init__(self, api_key: str, config: Optional[Dict[str, Any]] = None):
        self.api_key = api_key
        self.config = config or {}
        self.model = self.config.get("view_model") or self.config.get("model", "deepseek-chat")
        self.base_url = self.config.get("base_url", "https://api.deepseek.com")
        self.enabled = bool(self.config.get("enable_llm_view_analysis", True))
        self.enable_multimodal = bool(self.config.get("enable_multimodal_view_input", False))
        self.confidence_threshold = float(self.config.get("view_confidence_threshold", 0.60))
        self.validator = ViewAnalysisValidator(self.confidence_threshold)
        self.client = OpenAI(api_key=api_key, base_url=self.base_url)
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
            if self.config.get("view_disable_thinking", True):
                request_payload["extra_body"] = {"thinking": {"type": "disabled"}}
            call_span = self.telemetry_store.start_call(
                stage="view_analysis",
                model=self.model,
                provider="deepseek",
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
            llm_result = self._extract_json(content)
            llm_result.setdefault("source", "llm")

            valid, errors = self.validator.validate(llm_result, geometry_data)
            if not valid:
                logger.warning(f"LLM视图校正结果未通过校验，回退本地规则: {'; '.join(errors)}")
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
