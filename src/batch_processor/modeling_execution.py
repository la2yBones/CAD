#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execution dispatcher for intelligent modeling paths."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from src.utils.modeling_utils import looks_like_english_sentence, normalize_feature_records
from typing import Any, Callable, Dict, List, Optional

from src.reconstruction.analysis_result import (
    IntelligentAnalysisResult,
    ModelingInstructionsResult,
    ModelingPathDecisionResult,
)
from src.reconstruction.modeling_path import PLANAR_EXTRUDE, REVOLVE
from src.utils.deepseek_options import STAGE_MODELING_GENERATION
from src.utils.stage_self_correction import (
    PENDING_RECOVERY,
    SELF_CORRECT,
    SelfCorrectionRequest,
    SelfCorrectionResult,
    ValidationIssue,
)


logger = logging.getLogger(__name__)


@dataclass
class ModelingExecutionRequest:
    result: Any
    intelligent_analysis_result: Dict[str, Any]
    geometry_data: Dict[str, Any]
    output_structure: Dict[str, Path]
    extrude_height: float
    missing_script_message: str
    script_failure_prefix: str
    completion_message: str


ExecutionHandler = Callable[[ModelingExecutionRequest], Any]


def _feature_text(record: Dict[str, Any]) -> str:
    parts = [
        record.get("name"),
        record.get("kind"),
        record.get("reason"),
        record.get("risk"),
        record.get("evidence"),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _is_speculative_skipped_feature(record: Dict[str, Any]) -> bool:
    """Treat unconfirmed optional details as warnings, not partial failures."""
    kind = str(record.get("kind") or "").strip().lower()
    name = str(record.get("name") or "").strip().lower()
    if kind not in {"fillet", "chamfer", "round", "edge_round", "edge_fillet"}:
        if not any(marker in name for marker in ("fillet", "chamfer", "round")):
            return False

    text = _feature_text(record)
    speculative_markers = (
        "not clearly",
        "unclear",
        "ambiguous",
        "speculative",
        "possible",
        "possibly",
        "if drawing requires",
        "if required",
        "optional",
        "未明确",
        "不明确",
        "尚未明确",
        "可能",
        "可能仅指",
        "若图纸要求",
        "如需",
        "可选",
    )
    hard_failure_markers = (
        "failed",
        "failure",
        "cannot",
        "error",
        "exception",
        "missing width",
        "missing height",
        "缺少宽度",
        "缺少高度",
        "执行失败",
        "建模失败",
        "api restrictions",
    )
    return any(marker in text for marker in speculative_markers) and not any(
        marker in text for marker in hard_failure_markers
    )


def _split_skipped_features(
    skipped_features: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    required: List[Dict[str, Any]] = []
    advisory: List[Dict[str, Any]] = []
    for feature in skipped_features:
        if _is_speculative_skipped_feature(feature):
            advisory.append(feature)
        else:
            required.append(feature)
    return required, advisory


def _append_advisory_warnings(
    modeling_instructions: ModelingInstructionsResult,
    advisory_features: List[Dict[str, Any]],
) -> None:
    if not advisory_features:
        return
    for feature in advisory_features:
        name = feature.get("name") or feature.get("kind") or "detail"
        reason = feature.get("reason") or feature.get("risk") or "图纸未明确确认该细节"
        if looks_like_english_sentence(str(reason)):
            reason = "图纸未明确确认该细节，已按风险提示处理"
        modeling_instructions.warnings.append(f"推测性跳过细节已作为风险提示处理：{name}: {reason}")


def _is_recoverable_script_quality_failure(run_result: Dict[str, Any]) -> bool:
    return (
        bool(run_result.get("recoverable"))
        and run_result.get("failure_stage") in ("script_readiness", "script_validation")
    )


def _is_syntax_error(run_result: Dict[str, Any]) -> bool:
    error = str(run_result.get("error") or "").lower()
    return "语法无效" in error or "syntax" in error or "indented block" in error


def _format_validation_errors(errors: Any) -> str:
    records = errors if isinstance(errors, list) else [errors]
    lines = []
    for index, error in enumerate(records[:8], start=1):
        text = str(error or "").strip()
        if text:
            lines.append(f"{index}. {text}")
    if isinstance(records, list) and len(records) > 8:
        lines.append(f"... 另有 {len(records) - 8} 项")
    return "\n".join(lines)


def _without_generic_modeler_fallback_text(message: str) -> str:
    """移除面向开发者的通用建模器兜底说明，保留真正错误原因。"""
    cleaned = str(message or "")
    replacements = (
        "；统一智能处理不会调用通用建模器兜底",
        "，统一智能处理不会调用通用建模器兜底",
        "统一智能处理不会调用通用建模器兜底",
        "; intelligent processing will not fall back to the generic modeler",
        "intelligent processing will not fall back to the generic modeler: ",
        "intelligent processing will not fall back to the generic modeler",
        "AI script execution failed; ",
    )
    for text in replacements:
        cleaned = cleaned.replace(text, "")
    return cleaned.strip(" ；;，,")


def _script_quality_validation_issues(errors: Any) -> List[ValidationIssue]:
    records = errors if isinstance(errors, list) else [errors]
    issues: List[ValidationIssue] = []
    for index, error in enumerate(records, start=1):
        text = str(error or "").strip()
        if not text:
            continue
        issues.append(
            ValidationIssue(
                code=f"script_quality_{index}",
                message=text,
                severity="error",
                fixable=True,
                impact="AI FreeCAD 脚本无法进入执行阶段",
                correction_target="重新生成满足建模约束和可执行性合同的 FreeCAD 脚本",
                details={"original_error": text},
            )
        )
    if not issues:
        issues.append(
            ValidationIssue(
                code="script_quality_unknown",
                message="脚本结构不满足执行前校验",
                severity="error",
                fixable=True,
                impact="AI FreeCAD 脚本无法进入执行阶段",
                correction_target="重新生成满足建模约束和可执行性合同的 FreeCAD 脚本",
                details={"reason": "未捕获具体校验错误"},
            )
        )
    return issues


def _script_quality_output_contract() -> Dict[str, Any]:
    return {
        "required_fields": [
            "analysis_summary",
            "modeling_strategy",
            "freecad_script",
            "instructions",
            "key_dimensions",
            "completed_features",
            "skipped_features",
            "partial_completion_reason",
            "warnings",
        ],
        "freecad_script_contract": [
            "必须赋值 final_shape",
            '必须执行 Part.show(final_shape, "GeneratedModel")',
            "必须执行 doc.recompute()",
            "Part.Face 前必须检查 Wire.isClosed()",
            "Part.Wire 内的 LineSegment/ArcOfCircle 必须先转换为 Shape/Edge",
            "Part.ArcOfCircle 只能使用 3 个位置参数",
        ],
    }


def _build_modeling_self_correction_request(
    analysis: IntelligentAnalysisResult,
    run_result: Dict[str, Any],
    ai_script_content: str,
    *,
    round_index: int = 1,
    max_rounds: int = 2,
) -> SelfCorrectionRequest:
    modeling_instructions = analysis.modeling_instructions
    validation_errors = run_result.get("validation_errors") or []
    error_summary = "; ".join(str(e) for e in validation_errors[:3]) if validation_errors else str(run_result.get("error", "脚本质量校验失败"))
    correction_goal_parts = ["修复脚本质量问题并重新输出可执行的 FreeCAD 建模指令 JSON"]
    if modeling_instructions.is_partial:
        if modeling_instructions.skipped_features:
            names = [f.get("name", f.get("kind", "?")) for f in modeling_instructions.skipped_features[:5]]
            correction_goal_parts.append(f"跳过特征：{', '.join(names)}")
        if modeling_instructions.partial_completion_reason:
            correction_goal_parts.append(f"部分完成原因：{modeling_instructions.partial_completion_reason}")
    correction_goal_parts.append(f"校验错误：{error_summary}")
    return SelfCorrectionRequest(
        stage=STAGE_MODELING_GENERATION,
        round_index=round_index,
        max_rounds=max_rounds,
        stage_payload=modeling_instructions._modeling_task_payload,
        previous_output={
            "analysis_summary": modeling_instructions.analysis_summary,
            "modeling_strategy": modeling_instructions.modeling_strategy,
            "freecad_script": ai_script_content,
            "instructions": list(modeling_instructions.instructions),
            "key_dimensions": list(modeling_instructions.key_dimensions),
            "completed_features": list(modeling_instructions.completed_features),
            "skipped_features": list(modeling_instructions.skipped_features),
            "partial_completion_reason": modeling_instructions.partial_completion_reason,
            "warnings": list(modeling_instructions.warnings),
        },
        validation_issues=_script_quality_validation_issues(
            run_result.get("validation_errors") or run_result.get("error")
        ),
        output_contract=_script_quality_output_contract(),
        evidence_refs=[
            {
                "id": "modeling_task_payload",
                "kind": "stage_payload",
                "summary": "第三阶段建模任务载荷",
            },
            {
                "id": "failed_script",
                "kind": "previous_output",
                "summary": f"执行失败的 FreeCAD 脚本 ({len(ai_script_content)} 字符)",
            },
        ],
        correction_goal="；".join(correction_goal_parts),
    )


def _build_modeling_self_correction_result(
    correction_request: SelfCorrectionRequest,
    run_result: Dict[str, Any],
    result_text: str = "当前版本先进入待恢复；后续由阶段内自纠会话消费该请求。",
) -> SelfCorrectionResult:
    return SelfCorrectionResult(
        status=PENDING_RECOVERY,
        self_correction_log=[
            {
                "stage": correction_request.stage,
                "round_index": correction_request.round_index,
                "max_rounds": correction_request.max_rounds,
                "trigger": "script_quality_validation_failed",
                "issues": [
                    issue.to_dict()
                    for issue in correction_request.validation_issues
                ],
                "result": result_text,
            }
        ],
        risk_notes=[
            "脚本未通过执行前校验，继续执行会高概率失败。",
            str(run_result.get("error") or "脚本质量校验失败"),
        ],
        next_action=SELF_CORRECT,
        message="已生成建模指令阶段的模型自纠请求。",
    )





class IntelligentModelingExecutor:
    """Execute the modeling path selected by intelligent reconstruction."""

    def __init__(
        self,
        config: Dict[str, Any],
        modeler_factory: Callable[[], Any],
        path_handlers: Optional[Dict[str, ExecutionHandler]] = None,
    ):
        self.config = config
        self._modeler_factory = modeler_factory
        if path_handlers is None:
            path_handlers = self._default_path_handlers()
        self._path_handlers = dict(path_handlers)

    def _default_path_handlers(self) -> Dict[str, ExecutionHandler]:
        return {
            PLANAR_EXTRUDE: self._execute_planar_extrude_path,
            REVOLVE: self._execute_revolve_path,
        }

    def execute(
        self,
        *,
        result: Any,
        intelligent_analysis_result: Dict[str, Any],
        geometry_data: Dict[str, Any],
        output_structure: Dict[str, Path],
        extrude_height: float,
        missing_script_message: str,
        script_failure_prefix: str,
        completion_message: str,
    ) -> Any:
        if isinstance(intelligent_analysis_result, dict):
            self._analysis = IntelligentAnalysisResult.from_dict(intelligent_analysis_result)
        else:
            self._analysis = intelligent_analysis_result

        request = ModelingExecutionRequest(
            result=result,
            intelligent_analysis_result=intelligent_analysis_result,
            geometry_data=geometry_data,
            output_structure=output_structure,
            extrude_height=extrude_height,
            missing_script_message=missing_script_message,
            script_failure_prefix=_without_generic_modeler_fallback_text(script_failure_prefix),
            completion_message=completion_message,
        )
        request.missing_script_message = _without_generic_modeler_fallback_text(
            request.missing_script_message
        )
        modeling_path_decision = self._analysis.modeling_path_decision
        modeling_path = modeling_path_decision.modeling_path
        handler = self._path_handlers.get(modeling_path)
        if handler:
            result.modeling_path = modeling_path
            logger.info(
                "Intelligent processing routed to specialized modeling path"
                f" | path: {modeling_path}"
                f" | reason: {modeling_path_decision.reason}"
            )
            return handler(request)

        return self._run_ai_script(request)

    def _execute_planar_extrude_path(self, request: ModelingExecutionRequest) -> Any:
        return self._run_planar_extrude(
            request.result,
            request.geometry_data,
            request.output_structure,
            request.extrude_height,
        )

    def _execute_revolve_path(self, request: ModelingExecutionRequest) -> Any:
        return self._run_revolve(
            request.result,
            request.output_structure,
        )

    def _run_planar_extrude(
        self,
        result: Any,
        geometry_data: Dict[str, Any],
        output_structure: Dict[str, Path],
        extrude_height: float,
    ) -> Any:
        modeler_config = {}
        if "freecad" in self.config:
            modeler_config.update(self.config.get("freecad", {}))
        modeler_config["default_extrude_height"] = extrude_height

        modeler = self._modeler_factory()(modeler_config)
        modeler.generate(geometry_data, {})

        if "model_step" in output_structure:
            export_path = str(output_structure["model_step"])
            export_success = modeler.export(export_path, "STEP")
            if export_success and Path(export_path).exists():
                result.output_paths["model_step"] = export_path
                logger.info(f"STEP model saved: {export_path}")
            else:
                logger.warning(f"STEP model may not have been saved correctly: {export_path}")

        if "model_stl" in output_structure:
            try:
                stl_path = str(output_structure["model_stl"])
                if modeler.export(stl_path, "STL") and Path(stl_path).exists():
                    result.output_paths["model_stl"] = stl_path
            except Exception as error:
                logger.warning(f"STL export failed: {error}")

        modeler.close()
        result.mark_completed()
        logger.info(f"Planar extrusion completed: {Path(result.input_file).name}")
        return result

    def _run_revolve(
        self,
        result: Any,
        output_structure: Dict[str, Path],
    ) -> Any:
        from src.model_generator.ai_script_runner import AIScriptRunner
        from src.reconstruction.revolve_executor import build_revolve_script

        candidate_paths = self._analysis.modeling_path_decision.candidate_paths
        revolve_candidate = next(
            (candidate for candidate in candidate_paths if candidate.get("path") == REVOLVE),
            None,
        )
        if not revolve_candidate or not revolve_candidate.get("semantics"):
            result.mark_failed("Revolve path execution failed: missing revolve semantics")
            return result
        script = build_revolve_script(revolve_candidate["semantics"])
        step_path = str(output_structure["model_step"]) if "model_step" in output_structure else None
        run_result = AIScriptRunner(self.config).run_script(script, step_path)
        if not run_result.get("success"):
            result.mark_failed(f"Revolve path execution failed: {run_result.get('error', 'unknown error')}")
            return result
        if run_result.get("step_path"):
            result.output_paths["model_step"] = run_result["step_path"]
        if run_result.get("fcstd_path"):
            result.output_paths["model_fcstd"] = run_result["fcstd_path"]
        result.mark_completed()
        logger.info(f"Revolve path completed: {Path(result.input_file).name}")
        return result

    def _run_ai_script(self, request: ModelingExecutionRequest) -> Any:
        result = request.result
        modeling_instructions = self._analysis.modeling_instructions
        ai_script_content = modeling_instructions.freecad_script
        if not ai_script_content:
            result.mark_failed(request.missing_script_message)
            logger.warning(result.error_message)
            return result

        logger.info("Executing AI generated FreeCAD script")
        try:
            from src.model_generator.ai_script_runner import AIScriptRunner

            runner = AIScriptRunner(self.config)
            step_path = (
                str(request.output_structure["model_step"])
                if "model_step" in request.output_structure
                else None
            )
            run_result = runner.run_script(ai_script_content, step_path)
            if not run_result.get("success"):
                if _is_recoverable_script_quality_failure(run_result):
                    corrected = self._attempt_modeling_self_correction(
                        request,
                        runner,
                        run_result,
                        ai_script_content,
                        step_path,
                    )
                    if corrected is not None:
                        return corrected
                    return self._mark_script_quality_needs_clarification(
                        request,
                        run_result,
                        ai_script_content,
                    )
                result.mark_failed(
                    f"{request.script_failure_prefix}: {run_result.get('error', 'unknown error')}"
                )
                logger.warning(result.error_message)
                return result

            return self._finalize_ai_script_success(
                request,
                run_result,
                modeling_instructions,
            )
        except Exception as error:
            result.mark_failed(
                f"AI脚本执行失败: {error}"
            )
            logger.warning(result.error_message)
            return result

    def _attempt_modeling_self_correction(
        self,
        request: ModelingExecutionRequest,
        runner: Any,
        run_result: Dict[str, Any],
        ai_script_content: str,
        step_path: Optional[str],
    ) -> Optional[Any]:
        api_config = self._deepseek_api_config()
        api_key = str(api_config.get("api_key") or "")
        if not api_key or api_key == "your-deepseek-api-key-here":
            return None

        max_rounds = 2
        current_script = ai_script_content
        current_run_result = run_result

        for round_index in range(1, max_rounds + 1):
            correction_request = _build_modeling_self_correction_request(
                self._analysis,
                current_run_result,
                current_script,
                round_index=round_index,
                max_rounds=max_rounds,
            )
            logger.info(
                "模型自纠第 %s/%s 轮 | 阶段: 建模指令生成 | 原因: %s",
                round_index,
                max_rounds,
                current_run_result.get("error", "脚本质量校验失败"),
            )
            self._notify_progress(
                "self_correction",
                f"模型自纠中 {round_index}/{max_rounds}",
            )
            try:
                from src.reconstruction.instruction_generator import FreeCADInstructionGenerator

                generator = FreeCADInstructionGenerator(api_key, api_config)
                corrected_instructions = generator.generate_from_self_correction(
                    correction_request,
                    file_path=result_file_path(request.result),
                )
                corrected_typed = ModelingInstructionsResult.from_dict(corrected_instructions)
                corrected_script = corrected_typed.freecad_script
                if not corrected_script:
                    logger.warning("模型自纠第 %s 轮未返回可执行脚本", round_index)
                    continue

                second_run = runner.run_script(corrected_script, step_path)
                if not second_run.get("success"):
                    logger.warning(
                        "模型自纠第 %s 轮后脚本仍未通过: %s",
                        round_index,
                        second_run.get("error", "unknown error"),
                    )
                    current_script = corrected_script
                    current_run_result = second_run
                    continue

                if not corrected_typed.self_correction_applied:
                    corrected_typed.self_correction_applied = True
                if not corrected_typed.self_correction_log:
                    corrected_typed.self_correction_log = (
                        _build_modeling_self_correction_result(
                            correction_request,
                            current_run_result,
                            result_text="修正后脚本执行成功",
                        )
                    )
                self._analysis.modeling_instructions = corrected_typed
                self._notify_progress("modeling", "建模中")
                return self._finalize_ai_script_success(
                    request,
                    second_run,
                    corrected_typed,
                )
            except Exception as correction_error:
                logger.warning(
                    "模型自纠第 %s 轮异常: %s",
                    round_index,
                    correction_error,
                )
                continue

        logger.warning("模型自纠 %s 轮后仍未成功", max_rounds)
        self._notify_progress("modeling", "建模中")
        return None

    def _notify_progress(self, stage: str, text: str) -> None:
        callback = self.config.get("_progress_callback") if isinstance(self.config, dict) else None
        if not callback:
            return
        try:
            callback(stage, text)
        except Exception as error:
            logger.debug(f"进度回调失败: {error}")

    def _deepseek_api_config(self) -> Dict[str, Any]:
        api_root = self.config.get("api") if isinstance(self.config, dict) else {}
        if isinstance(api_root, dict) and isinstance(api_root.get("deepseek"), dict):
            return dict(api_root.get("deepseek") or {})
        return dict(self.config or {})

    def _finalize_ai_script_success(
        self,
        request: ModelingExecutionRequest,
        run_result: Dict[str, Any],
        modeling_instructions: ModelingInstructionsResult,
    ) -> Any:
        result = request.result
        if run_result.get("step_path"):
            result.output_paths["model_step"] = run_result["step_path"]
        if run_result.get("fcstd_path"):
            result.output_paths["model_fcstd"] = run_result["fcstd_path"]
        skipped_features = normalize_feature_records(
            run_result.get("skipped_features")
            or modeling_instructions.skipped_features
        )
        skipped_features, advisory_features = _split_skipped_features(skipped_features)
        _append_advisory_warnings(modeling_instructions, advisory_features)
        completed_features = normalize_feature_records(
            run_result.get("completed_features")
            or modeling_instructions.completed_features
        )
        if skipped_features:
            result.mark_partial_completed(
                skipped_features=skipped_features,
                completed_features=completed_features,
                reason=(
                    run_result.get("partial_completion_reason")
                    or modeling_instructions.partial_completion_reason
                ),
            )
            logger.info(f"AI script completed with skipped details: {len(skipped_features)}")
        else:
            result.mark_completed()
            if advisory_features:
                logger.info(
                    "AI script completed; speculative skipped details were kept as warnings: %s",
                    len(advisory_features),
                )
        logger.info(request.completion_message)
        return result

    def _mark_script_quality_needs_clarification(
        self,
        request: ModelingExecutionRequest,
        run_result: Dict[str, Any],
        ai_script_content: str,
    ) -> Any:
        result = request.result
        validation_errors = list(run_result.get("validation_errors") or [])
        error_text = _format_validation_errors(validation_errors)
        reason = error_text or str(run_result.get("error") or "脚本结构不满足执行前校验")
        is_syntax_error = _is_syntax_error(run_result)
        if is_syntax_error:
            text = (
                "AI 生成的 FreeCAD 脚本存在语法错误，自纠未能修复。"
                "请指出需要修正的语法问题，或说明可跳过的特征以简化脚本。"
            )
            example = (
                "例如：脚本第 103 行 if 语句后缺少缩进块；"
                "或说明先保证主体外形和孔正确，圆角/倒角可跳过。"
            )
        else:
            text = (
                "AI 生成的 FreeCAD 脚本未通过执行前校验。请补充建模意图、主体优先级"
                "或可接受的简化方式，系统会基于当前图纸上下文重新生成脚本。"
            )
            example = (
                "例如：先保证主体外形、孔和凸台正确，圆角/倒角可跳过；"
                "或说明应优先使用哪一个视图作为主体轮廓。"
            )
        result.mark_needs_clarification(
            [
                {
                    "id": "script_quality_recovery_hint",
                    "kind": "text",
                    "text": text,
                    "reason": reason,
                    "required": True,
                    "example": example,
                }
            ],
            self._build_script_quality_clarification_context(
                request,
                run_result,
                ai_script_content,
            ),
        )
        result.error_message = f"{request.script_failure_prefix}: {run_result.get('error', 'unknown error')}"
        logger.warning(result.error_message)
        return result

    def _build_script_quality_clarification_context(
        self,
        request: ModelingExecutionRequest,
        run_result: Dict[str, Any],
        ai_script_content: str,
    ) -> Dict[str, Any]:
        analysis = self._analysis
        correction_request = _build_modeling_self_correction_request(
            analysis,
            run_result,
            ai_script_content,
        )
        correction_result = _build_modeling_self_correction_result(
            correction_request,
            run_result,
        )
        return {
            "geometry_data": request.geometry_data,
            "view_analysis": analysis.view_analysis,
            "dimension_data": analysis.dimension_extraction,
            "local_relationships": analysis.local_relationships,
            "extrude_height": request.extrude_height,
            "file_path": result_file_path(request.result),
            "reconstruction_context": analysis.reconstruction_context,
            "clarification_stage": "semantic_policy",
            "script_quality_recovery": True,
            "previous_modeling_instructions": analysis.modeling_instructions.to_dict(),
            "failed_freecad_script": ai_script_content,
            "script_validation_errors": list(run_result.get("validation_errors") or []),
            "script_failure_error": run_result.get("error"),
            "self_correction_request": correction_request.to_dict(),
            "self_correction_result": correction_result.to_dict(),
            "self_correction_stage": STAGE_MODELING_GENERATION,
        }


def result_file_path(result: Any) -> str:
    return str(getattr(result, "input_file", "") or "")
