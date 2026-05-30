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
        non_empty_details = [d for d in self.details if d]
        if non_empty_details:
            lines.extend(f"依据：{item}" for item in non_empty_details[:4])
        if self.risks:
            lines.append("风险：" + "；".join(self.risks[:3]))
        else:
            lines.append("风险：未发现需要立即处理的问题")
        lines.append(f"下一步：{self.next_step}")
        return "\n".join(lines)


def build_stage_report(stage: str, payload: Dict[str, Any]) -> str:
    """Build a short decision summary for a completed review stage."""
    if stage == "view_analysis":
        return build_view_stage_summary(payload).render()
    if stage == "semantic_adjudication":
        return build_semantic_adjudication_stage_summary(payload).render()
    if stage == "semantic_reconstruction":
        return build_semantic_stage_summary(payload).render()
    if stage == "modeling_generation":
        return build_modeling_generation_stage_summary(payload).render()
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


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
    self_logs = _collect_stage_logs(payload, "self_correction_log")
    retry_logs = _collect_stage_logs(payload, "stage_retry_log")
    details = []
    view_names = [
        str(view_item.get("name") or view_item.get("label") or view_item.get("object_id") or "")
        for view_item in views
        if isinstance(view_item, dict)
    ]
    if view_names:
        details.append("视图候选：" + "、".join(name for name in view_names[:4] if name))
    details.extend(_format_self_correction_logs(self_logs, limit=1))
    details.extend(_format_stage_retry_logs(retry_logs, limit=1))
    details.append(_stage_operation_hint("视图语义校正"))
    risk_lines = []
    if questions:
        risk_lines.append(f"继续后需要补充信息：{len(questions)} 项")
        risk_lines.extend(_question_risk_items(questions, limit=2))
    risk_lines.extend(_short_items(warnings, limit=1))
    if self_logs:
        risk_lines.append(f"模型自纠记录：{len(self_logs)} 轮")
    if retry_logs:
        risk_lines.append(f"阶段重跑记录：{len(retry_logs)} 次")
    next_step = "继续后进入补充信息面板" if questions else "继续进入零件语义重建"
    return StageDecisionSummary(
        conclusion=f"{drawing_type}，{len(views)} 个视图，{dimension_count} 个尺寸，置信度 {confidence}",
        details=tuple(details),
        next_step=next_step,
        risks=tuple(risk_lines),
    )


def build_semantic_stage_report(payload: Dict[str, Any]) -> str:
    return build_semantic_stage_summary(payload).render()


def build_semantic_adjudication_stage_summary(payload: Dict[str, Any]) -> StageDecisionSummary:
    from src.reconstruction.semantic_adjudication_view import SemanticAdjudicationView

    policy = payload.get("semantic_policy") or {}
    adjudication = payload.get("semantic_adjudication") or policy.get("semantic_adjudication")
    view = SemanticAdjudicationView(adjudication)
    questions = view.clarification_questions
    self_logs = _collect_stage_logs(payload, "self_correction_log")
    retry_logs = _collect_stage_logs(payload, "stage_retry_log")
    risk_lines = []
    if not view.is_successful:
        risk_lines.append("图纸语义裁决失败，继续时将回退兼容语义策略")
    if questions:
        risk_lines.append(f"继续后需要补充信息：{len(questions)} 项")
        risk_lines.extend(_question_risk_items(questions, limit=2))
    risk_lines.extend(_short_items(view.uncertainties, limit=1))
    risk_lines.extend(_short_items(view.warnings, limit=1))
    if self_logs:
        risk_lines.append(f"模型自纠记录：{len(self_logs)} 轮")
    if retry_logs:
        risk_lines.append(f"阶段重跑记录：{len(retry_logs)} 次")
    next_step = "继续后进入补充信息面板" if questions else "继续进入零件语义生成"
    details = [
        f"视图角色 {len(view.to_dict().get('view_roles', []))} 个，尺寸角色 {len(view.confirmed_dimensions)} 个",
        f"特征角色 {len(view.confirmed_features)} 个，派生尺寸 {len(view.derived_dimensions)} 个",
    ]
    details.extend(_format_self_correction_logs(self_logs, limit=1))
    details.extend(_format_stage_retry_logs(retry_logs, limit=1))
    details.append(_stage_operation_hint("图纸语义裁决"))

    return StageDecisionSummary(
        conclusion=f"图纸语义裁决，置信度 {view.confidence:g}，追问 {len(questions)} 项",
        details=tuple(details),
        risks=tuple(risk_lines),
        next_step=next_step,
    )


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
    self_logs = _collect_stage_logs(payload, "self_correction_log")
    retry_logs = _collect_stage_logs(payload, "stage_retry_log")

    risk_lines = _short_items(uncertainties, limit=1)
    risk_lines.extend(_short_items(warnings, limit=1))
    if self_logs:
        risk_lines.append(f"模型自纠记录：{len(self_logs)} 轮")
    if retry_logs:
        risk_lines.append(f"阶段重跑记录：{len(retry_logs)} 次")
    try:
        if float(confidence) < 0.7:
            risk_lines.insert(0, "置信度较低")
    except (TypeError, ValueError):
        pass
    next_step = "继续进入建模路径选择和执行"
    if _has_missing_body_dimension(uncertainties) or _has_missing_body_dimension(warnings):
        next_step = "继续后进入建模前澄清，补充主体厚度或拉伸深度"
    details = [
        f"主体特征 {len(base_features)} 个，增材 {len(additive_features)} 个，减材 {len(subtractive_features)} 个",
        f"关键尺寸 {len(key_dimensions)} 个",
    ]
    details.extend(_format_self_correction_logs(self_logs, limit=1))
    details.extend(_format_stage_retry_logs(retry_logs, limit=1))
    details.append(_stage_operation_hint("零件语义重建"))

    return StageDecisionSummary(
        conclusion="{part_type}，置信度 {confidence}，尺寸来源 {dimension_source}".format(
            part_type=semantics.get("part_type", "unknown"),
            confidence=confidence,
            dimension_source=semantics.get("dimension_source") or policy.get("dimension_source", "unknown"),
        ),
        details=tuple(details),
        risks=tuple(risk_lines),
        next_step=next_step,
    )


def build_modeling_generation_stage_summary(payload: Dict[str, Any]) -> StageDecisionSummary:
    instructions = payload.get("modeling_instructions") or payload
    script = str(instructions.get("freecad_script") or "")
    completed = instructions.get("completed_features") or []
    skipped = instructions.get("skipped_features") or []
    warnings = instructions.get("warnings") or []
    self_logs = _self_correction_logs(instructions)
    retry_logs = _stage_retry_logs(instructions)
    details = [
        f"脚本长度 {len(script)} 字符，已完成特征 {len(completed)} 个，跳过细节 {len(skipped)} 个",
    ]
    details.extend(_format_self_correction_logs(self_logs, limit=1))
    details.extend(_format_stage_retry_logs(retry_logs, limit=1))
    details.append(_stage_operation_hint("建模指令生成"))
    risk_lines = _short_items(warnings, limit=1)
    if skipped:
        risk_lines.append(f"存在跳过细节：{len(skipped)} 项")
    if self_logs:
        risk_lines.append(f"模型自纠记录：{len(self_logs)} 轮")
    if retry_logs:
        risk_lines.append(f"阶段重跑记录：{len(retry_logs)} 次")
    next_step = "继续进入 FreeCAD 脚本执行"
    if not script:
        next_step = "无法继续执行，缺少建模脚本"

    return StageDecisionSummary(
        conclusion=(
            "建模指令已生成"
            if script
            else "建模指令未生成可执行脚本"
        ),
        details=tuple(details),
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


def _question_risk_items(items: Iterable[Any], *, limit: int) -> list[str]:
    risks = []
    for item in items:
        if isinstance(item, dict):
            text = (
                item.get("text")
                or item.get("question")
                or item.get("reason")
                or item.get("id")
                or ""
            )
            reason = item.get("reason")
            if reason and reason != text:
                text = f"{text}（原因：{reason}）" if text else str(reason)
        else:
            text = str(item)
        text = str(text or "").strip()
        if not text:
            continue
        risks.append("需补充：" + text[:80] + ("..." if len(text) > 80 else ""))
        if len(risks) >= limit:
            break
    return risks


def _self_correction_logs(instructions: Dict[str, Any]) -> list[Dict[str, Any]]:
    logs = instructions.get("self_correction_log") or []
    if isinstance(logs, dict):
        return [logs]
    if not isinstance(logs, list):
        return []
    return [item for item in logs if isinstance(item, dict)]


def _stage_retry_logs(instructions: Dict[str, Any]) -> list[Dict[str, Any]]:
    logs = instructions.get("stage_retry_log") or []
    if isinstance(logs, dict):
        return [logs]
    if not isinstance(logs, list):
        return []
    return [item for item in logs if isinstance(item, dict)]


def _collect_stage_logs(payload: Dict[str, Any], log_key: str) -> list[Dict[str, Any]]:
    logs = []
    seen_ids = set()

    def append_log(item: Any) -> None:
        if not isinstance(item, dict):
            return
        marker = id(item)
        if marker in seen_ids:
            return
        seen_ids.add(marker)
        logs.append(item)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            direct_logs = value.get(log_key)
            if isinstance(direct_logs, dict):
                append_log(direct_logs)
            elif isinstance(direct_logs, list):
                for entry in direct_logs:
                    append_log(entry)
            for nested_value in value.values():
                if nested_value is direct_logs:
                    continue
                if isinstance(nested_value, (dict, list, tuple)):
                    visit(nested_value)
            return
        if isinstance(value, (list, tuple)):
            for nested_value in value:
                visit(nested_value)

    visit(payload)
    return logs


def _stage_operation_hint(stage_label: str) -> str:
    return ""


def _format_self_correction_logs(
    logs: list[Dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    formatted = []
    for item in logs[:limit]:
        round_index = item.get("round_index", "?")
        max_rounds = item.get("max_rounds", "?")
        trigger = str(item.get("trigger") or "本地校验问题")
        result = str(item.get("result") or "已完成")
        formatted.append(
            f"模型自纠第 {round_index}/{max_rounds} 轮，原因 {trigger}，结果 {result}"
        )
    return formatted


def _format_stage_retry_logs(
    logs: list[Dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    formatted = []
    for item in logs[:limit]:
        trigger = str(item.get("trigger") or "用户请求重跑")
        result = str(item.get("result") or "已完成")
        formatted.append(f"阶段重跑，原因 {trigger}，结果 {result}")
    return formatted


def _localize_stage_risk_text(text: str) -> str:
    """Localize common model-emitted risk phrases before rendering UI text."""
    lower = text.lower()
    if "llm" in lower and "校验失败" in lower and "回退" in lower:
        return "LLM 校正结果未通过本地校验，已回退本地规则；视图角色和投影关系可能不够准确，后续阶段可能需要自纠"
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
