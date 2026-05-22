#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据重建上下文生成结构化零件语义。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from src.utils.llm_telemetry import default_llm_telemetry_store

from .semantic_payload import SemanticUnderstandingPayloadBuilder
from .semantic_schema import PartSemanticsValidator

logger = logging.getLogger(__name__)


class PartSemanticGenerator:
    """在生成 CAD 脚本前，先让模型解释零件结构。"""

    SYSTEM_PROMPT = """你是机械制图和三维重建专家。
你的任务不是写 FreeCAD 脚本，而是把 semantic_understanding_payload 解释为结构化零件语义。

原则：
- 基于输入证据做判断，不要把视图旁边的位置关系误判为真实三维附加实体。
- 对二视图/三视图，先解释为同一零件的正交投影。
- 必须服从 semantic_policy.dimension_source，并把同一值原样写入 dimension_source；不得在语义生成阶段重新裁决尺寸来源。
- 优先使用 semantic_policy.dimension_bindings 中已经完成的尺寸语义绑定；对 unresolved_linear 不得擅自命名为总长、对边、对角、法兰直径或孔径。
- key_dimensions 只能使用 semantic_policy.dimension_plan.allowed_dimensions 中的值和角色；allowed_dimensions 可能包含由标注尺寸链组合得到的派生值，例如 9+39=48。
- semantic_policy.dimension_plan.segment_dimensions 可作为组合尺寸证据，也可作为建模构造步骤的分段尺寸；但不能单独命名为总长、深度、对边、对角、法兰直径或孔径。
- semantic_policy.dimension_plan.unresolved_dimensions 不得进入 key_dimensions；若建模需要这些值，必须写入 uncertainties。
- 若 dimension_source=annotation，key_dimensions 只能来自 dimensions 中已有标注值或 semantic_policy.dimension_plan.allowed_dimensions 中已裁决的标注派生值；不得混入从实体坐标反算出的图形测量值。
- 必须遵守 semantic_policy.feature_constraints；隐藏线、同心圆或孤立投影不能单独升级为孔、槽、切除。
- 若 dimension_plan 中存在 chamfer（如 1x45°），只能解释为外部尖角削除；不得解释为内陷槽、凹坑、孔口沉槽或向实体内部新增的负形特征。
- 若 dimension_plan 中存在 radius（如 R15），必须根据标注位置解释为圆弧/圆角特征。对六角头螺栓头部侧面的 R15，应表达为绕螺栓轴线形成的圆弧面/承面，而不是简单忽略为普通风险。
- 必须保留 semantic_policy.assumptions 施加的限制；若仍有未决事项，写入 uncertainties，不要绕过裁决继续硬猜。
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
  "planar_modeling_semantics": {
    "profile": {"kind": "profile_extrusion|plate", "description": "外轮廓摘要"} 或 null,
    "extrusion_direction": "X|Y|Z|unknown",
    "extrusion_depth": 数值或 null,
    "cut_features": [],
    "dimension_bindings": [],
    "uncertainties": []
  },
  "revolve_modeling_semantics": {
    "axis_point": [0, 0, 0],
    "axis_direction": [0, 0, 1],
    "profile_points": [[0, 0, 0], [0, 0, 0]],
    "angle_degrees": 360,
    "uncertainties": []
  } 或 null,
  "preferred_modeling_path": "planar_extrude|revolve|null",
  "key_dimensions": [
    {"name": "尺寸名", "value": 数值, "unit": "mm"}
  ],
  "uncertainties": ["无法确认但影响建模的事项"],
  "warnings": ["建模风险或保守假设"]
}"""


    RETRY_SYSTEM_PROMPT = """你是机械制图和三维重建专家。
你的任务是把精简 semantic_understanding_payload 解释为结构化零件语义。
这是第二次请求，上一次因输出过长被截断。请输出极简 JSON，只保留建模必需字段。
砍掉 evidence、candidate_interpretations 和长 description。
uncertainties/warnings 用短句。
必须服从 semantic_policy.dimension_source，并把同一值原样写入 dimension_source。
优先使用 semantic_policy.dimension_bindings 中已完成的绑定；不得重命名 unresolved_linear。
key_dimensions 只能使用 semantic_policy.dimension_plan.allowed_dimensions；allowed_dimensions 可包含由标注尺寸链组合得到的派生值。segment 尺寸可用于建模构造步骤，但不能直接命名为总长/深度等关键语义；unresolved 尺寸不能进入 key_dimensions。
必须遵守 semantic_policy.feature_constraints，不得把隐藏线、同心圆或孤立投影单独升级为孔、槽、切除。
若存在 chamfer，只能表示外部尖角削除，不得输出内陷槽/凹坑语义。
若存在 radius/R15，应保留为圆弧面或圆角语义；六角头螺栓头部 R15 表示绕轴线的圆弧面/承面。

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
  "planar_modeling_semantics": {"profile": null, "extrusion_direction": "unknown", "extrusion_depth": null, "cut_features": [], "dimension_bindings": [], "uncertainties": []},
  "revolve_modeling_semantics": null,
  "preferred_modeling_path": null,
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
        self.payload_builder = SemanticUnderstandingPayloadBuilder()
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

        user_content = self._build_user_content(context)
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
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

    def _build_user_content(self, context: Dict[str, Any]) -> str:
        builder = getattr(self, "payload_builder", None) or SemanticUnderstandingPayloadBuilder()
        payload = builder.build(context)
        parts = [
            "请根据以下 semantic_understanding_payload 生成结构化零件语义：",
            "=== semantic_understanding_payload ===",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
        hint_section = self._build_user_modeling_hint_section(context)
        if hint_section:
            parts.append(hint_section)
        return "\n\n".join(parts)

    def _build_user_modeling_hint_section(self, context: Dict[str, Any]) -> str:
        semantic_policy = context.get("semantic_policy", {}) or {}
        hint = (
            context.get("user_modeling_hint")
            or semantic_policy.get("user_modeling_hint")
            or ""
        )
        hint = str(hint).strip()
        if not hint:
            return ""
        conflict_policy = (
            context.get("user_modeling_hint_policy")
            or semantic_policy.get("user_modeling_hint_policy")
            or "drawing_facts_override_user_hint"
        )
        return "\n".join([
            "=== 用户补充建模提示使用规则 ===",
            f"用户补充提示: {hint}",
            f"冲突策略: {conflict_policy}",
            (
                "必须遵守：补充提示用于帮助解释建模意图、细节优先级和可接受的跳过范围；"
                "如果它与 CAD 解析事实、标注尺寸、semantic_policy.dimension_plan、主体方向或主体外形冲突，"
                "必须以图纸事实和已裁决语义为准。"
            ),
            (
                "如果补充提示表达了用户希望优先得到部分成果，可在 uncertainties/warnings 中记录被跳过的细节风险，"
                "但不得把主体级硬约束改写成用户自然语言。"
            ),
        ])

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
            "planar_modeling_semantics": {
                "profile": None,
                "extrusion_direction": "unknown",
                "extrusion_depth": None,
                "cut_features": [],
                "dimension_bindings": [],
                "uncertainties": ["语义生成失败"],
            },
            "revolve_modeling_semantics": None,
            "preferred_modeling_path": None,
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
