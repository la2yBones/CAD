#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""View models for pending clarification items."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.reconstruction.clarification import clarification_option_label


def pending_recovery_type(item: Optional[Dict[str, Any]]) -> str:
    """Return a short user-facing recovery type label."""
    if not item:
        return "-"
    context = item.get("clarification_context") or {}
    if context.get("script_quality_recovery"):
        return "脚本质量恢复"
    if context.get("partial_modeling_recovery") or item.get("source_status") == "partial_completed":
        return "部分建模恢复"
    if context.get("pre_modeling_recovery"):
        return "建模前澄清"
    stage = str(context.get("clarification_stage") or "")
    if stage == "modeling_path":
        return "路径澄清"
    return "语义澄清"


def pending_recovery_summary(item: Optional[Dict[str, Any]]) -> str:
    """Build a concise one-line reason for lists and logs."""
    if not item:
        return "待恢复任务"
    recovery_type = pending_recovery_type(item)
    questions = item.get("clarification_questions") or []
    return f"{recovery_type}，需要补充 {len(questions)} 项信息"


def build_pending_item_detail(item: Optional[Dict[str, Any]]) -> str:
    """Build a user-facing detail summary for one pending clarification item."""
    if not item:
        return "选中一条待恢复任务后，这里会显示需要补充的问题和上次处理结果。"

    lines = [
        f"图纸：{Path(str(item.get('input_file') or '')).name or '-'}",
        f"恢复类型：{pending_recovery_type(item)}",
        f"状态：{item.get('source_status') or item.get('status') or '-'}",
        f"建模路径：{item.get('modeling_path') or '-'}",
        f"更新时间：{item.get('updated_at') or '-'}",
    ]
    reason = str(item.get("partial_completion_reason") or "").strip()
    if reason:
        lines.extend(["", f"上次部分完成原因：{reason}"])

    questions = item.get("clarification_questions") or []
    lines.extend(["", f"需要补充：{len(questions)} 项"])
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question.get('text') or question.get('id') or '请补充信息'}")
        reason_text = str(question.get("reason") or "").strip()
        if reason_text:
            lines.append(f"   为什么问：{reason_text}")
        options = question.get("options") or []
        if options:
            lines.append("   可选项：")
            for option in options:
                lines.append(f"   - {clarification_option_label(option)}")

    skipped_features = item.get("skipped_features") or []
    if skipped_features:
        lines.extend(["", "上次跳过细节："])
        for feature in skipped_features:
            if isinstance(feature, dict):
                name = feature.get("name") or feature.get("kind") or "未命名细节"
                reason_text = feature.get("reason") or ""
                lines.append(f"- {name}: {reason_text}".rstrip(": "))
            else:
                lines.append(f"- {feature}")

    script_errors = (
        (item.get("clarification_context") or {}).get("script_validation_errors") or []
    )
    if script_errors:
        lines.extend(["", "上次脚本校验问题："])
        for index, error in enumerate(script_errors[:8], start=1):
            lines.append(f"{index}. {error}")
        if len(script_errors) > 8:
            lines.append(f"... 另有 {len(script_errors) - 8} 项")

    output_paths = item.get("output_paths") or {}
    if output_paths:
        lines.extend(["", "已有输出产物："])
        for key, value in output_paths.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)
