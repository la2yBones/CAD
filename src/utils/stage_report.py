#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decision summaries for stage-confirmation dialogs."""
from __future__ import annotations

import json
from typing import Any, Dict


def build_stage_report(stage: str, payload: Dict[str, Any]) -> str:
    """Build a short decision summary for a completed review stage."""
    if stage == "view_analysis":
        return build_view_stage_report(payload)
    if stage == "semantic_reconstruction":
        return build_semantic_stage_report(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def build_view_stage_report(payload: Dict[str, Any]) -> str:
    view = payload.get("view_analysis") or {}
    dimensions = payload.get("dimension_data") or {}
    policy = payload.get("semantic_policy") or {}
    questions = policy.get("clarification_questions") or []
    warnings = view.get("warnings") or []
    views = view.get("views") or []
    drawing_type = view.get("drawing_type", "unknown")
    confidence = view.get("confidence", "unknown")
    dimension_count = len(dimensions.get("dimensions") or dimensions.get("extracted_dimensions") or [])

    lines = [
        f"结论：{drawing_type}，{len(views)} 个视图，{dimension_count} 个尺寸，置信度 {confidence}",
    ]
    risk_lines = []
    if questions:
        risk_lines.append(f"继续后需要补充信息：{len(questions)} 项")
    risk_lines.extend(str(item) for item in warnings[:2])
    if risk_lines:
        lines.extend(["", "风险：", *[f"- {item}" for item in risk_lines]])
    else:
        lines.extend(["", "风险：未发现需要立即处理的问题"])
    if questions:
        lines.extend(["", "下一步：继续后进入补充信息面板"])
    else:
        lines.extend(["", "下一步：继续进入零件语义重建"])
    return "\n".join(lines)


def build_semantic_stage_report(payload: Dict[str, Any]) -> str:
    semantics = payload.get("part_semantics") or {}
    policy = payload.get("semantic_policy") or {}
    confidence = semantics.get("confidence", "unknown")
    uncertainties = semantics.get("uncertainties") or []
    warnings = semantics.get("warnings") or []
    key_dimensions = semantics.get("key_dimensions") or []
    base_features = semantics.get("base_features") or []
    additive_features = semantics.get("additive_features") or []
    subtractive_features = semantics.get("subtractive_features") or []
    lines = [
        "结论：{part_type}，置信度 {confidence}，尺寸来源 {dimension_source}".format(
            part_type=semantics.get("part_type", "unknown"),
            confidence=confidence,
            dimension_source=semantics.get("dimension_source") or policy.get("dimension_source", "unknown"),
        ),
        f"主体：基础特征 {len(base_features)} 个，增材 {len(additive_features)} 个，减材 {len(subtractive_features)} 个",
        f"关键尺寸：{len(key_dimensions)} 个",
    ]
    summary = str(semantics.get("summary") or "").strip()
    if summary:
        lines.append(f"摘要：{summary[:90]}{'...' if len(summary) > 90 else ''}")

    risk_lines = [str(item) for item in uncertainties[:2]]
    risk_lines.extend(str(item) for item in warnings[:2])
    try:
        if float(confidence) < 0.7:
            risk_lines.insert(0, "置信度较低")
    except (TypeError, ValueError):
        pass
    if risk_lines:
        lines.extend(["", "风险：", *[f"- {item}" for item in risk_lines[:4]]])
    else:
        lines.extend(["", "风险：未发现需要立即处理的问题"])
    lines.extend(["", "下一步：继续进入建模路径选择和执行"])
    return "\n".join(lines)
