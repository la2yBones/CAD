#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decision summaries for stage-confirmation dialogs."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, Tuple


@dataclass(frozen=True)
class StageDecisionSummary:
    """Compact stage-review summary rendered in confirmation dialogs."""

    conclusion: str
    next_step: str
    details: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"结论：{self.conclusion}"]
        if self.details:
            lines.extend(f"依据：{item}" for item in self.details[:2])
        if self.risks:
            lines.append("风险：" + "；".join(self.risks[:2]))
        else:
            lines.append("风险：未发现需要立即处理的问题")
        lines.append(f"下一步：{self.next_step}")
        return "\n".join(lines)


def build_stage_report(stage: str, payload: Dict[str, Any]) -> str:
    """Build a short decision summary for a completed review stage."""
    if stage == "view_analysis":
        return build_view_stage_summary(payload).render()
    if stage == "semantic_reconstruction":
        return build_semantic_stage_summary(payload).render()
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def build_view_stage_report(payload: Dict[str, Any]) -> str:
    return build_view_stage_summary(payload).render()


def build_view_stage_summary(payload: Dict[str, Any]) -> StageDecisionSummary:
    view = payload.get("view_analysis") or {}
    dimensions = payload.get("dimension_data") or {}
    policy = payload.get("semantic_policy") or {}
    questions = policy.get("clarification_questions") or []
    warnings = view.get("warnings") or []
    views = view.get("views") or []
    drawing_type = view.get("drawing_type", "unknown")
    confidence = view.get("confidence", "unknown")
    dimension_count = len(dimensions.get("dimensions") or dimensions.get("extracted_dimensions") or [])
    risk_lines = []
    if questions:
        risk_lines.append(f"继续后需要补充信息：{len(questions)} 项")
    risk_lines.extend(_short_items(warnings, limit=1))
    next_step = "继续后进入补充信息面板" if questions else "继续进入零件语义重建"
    return StageDecisionSummary(
        conclusion=f"{drawing_type}，{len(views)} 个视图，{dimension_count} 个尺寸，置信度 {confidence}",
        next_step=next_step,
        risks=tuple(risk_lines),
    )


def build_semantic_stage_report(payload: Dict[str, Any]) -> str:
    return build_semantic_stage_summary(payload).render()


def build_semantic_stage_summary(payload: Dict[str, Any]) -> StageDecisionSummary:
    semantics = payload.get("part_semantics") or {}
    policy = payload.get("semantic_policy") or {}
    confidence = semantics.get("confidence", "unknown")
    uncertainties = semantics.get("uncertainties") or []
    warnings = semantics.get("warnings") or []
    key_dimensions = semantics.get("key_dimensions") or []
    base_features = semantics.get("base_features") or []
    additive_features = semantics.get("additive_features") or []
    subtractive_features = semantics.get("subtractive_features") or []

    risk_lines = _short_items(uncertainties, limit=1)
    risk_lines.extend(_short_items(warnings, limit=1))
    try:
        if float(confidence) < 0.7:
            risk_lines.insert(0, "置信度较低")
    except (TypeError, ValueError):
        pass
    next_step = "继续进入建模路径选择和执行"
    if _has_missing_body_dimension(uncertainties) or _has_missing_body_dimension(warnings):
        next_step = "继续后进入建模前澄清，补充主体厚度或拉伸深度"

    return StageDecisionSummary(
        conclusion="{part_type}，置信度 {confidence}，尺寸来源 {dimension_source}".format(
            part_type=semantics.get("part_type", "unknown"),
            confidence=confidence,
            dimension_source=semantics.get("dimension_source") or policy.get("dimension_source", "unknown"),
        ),
        details=(
            f"主体特征 {len(base_features)} 个，增材 {len(additive_features)} 个，减材 {len(subtractive_features)} 个",
            f"关键尺寸 {len(key_dimensions)} 个",
        ),
        risks=tuple(risk_lines),
        next_step=next_step,
    )


def _short_items(items: Iterable[Any], *, limit: int) -> list[str]:
    short = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        text = _localize_stage_risk_text(text)
        short.append(text[:60] + ("..." if len(text) > 60 else ""))
        if len(short) >= limit:
            break
    return short


def _localize_stage_risk_text(text: str) -> str:
    """Localize common model-emitted risk phrases before rendering UI text."""
    lower = text.lower()
    if "extrusion depth missing" in lower:
        return "主体拉伸深度缺失，需补充主体厚度或拉伸深度"
    if "modeling will require assumptions" in lower:
        subjects = []
        if "depth" in lower:
            subjects.append("缺失深度")
        if "boss" in lower:
            subjects.append("凸台")
        if subjects:
            return f"建模需要对{'、'.join(subjects)}作额外假设，需补充确认"
        return "建模需要额外假设，需补充确认"
    if "reasonable default may be assumed" in lower:
        return "存在缺失尺寸，不应直接假设默认值，需补充确认"
    return text


def _has_missing_body_dimension(items: Iterable[Any]) -> bool:
    markers = (
        "extrusion depth missing",
        "missing depth",
        "缺少拉伸深度",
        "缺失拉伸深度",
        "主体拉伸深度缺失",
        "主体深度缺失",
        "未标注的拉伸深度",
        "厚度未标注",
        "深度未标注",
    )
    for item in items:
        text = str(item or "").strip().lower()
        if any(marker in text for marker in markers):
            return True
    return False
