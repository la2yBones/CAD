#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execution dispatcher for intelligent modeling paths."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.reconstruction.modeling_path import PLANAR_EXTRUDE, REVOLVE


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


def _normalize_feature_records(value: Any) -> List[Dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return [{"name": str(value), "reason": "unspecified"}]
    records: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            records.append(item)
        else:
            records.append({"name": str(item), "reason": "unspecified"})
    return records


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
    modeling_instructions: Dict[str, Any],
    advisory_features: List[Dict[str, Any]],
) -> None:
    if not advisory_features:
        return
    warnings = modeling_instructions.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = [warnings]
        modeling_instructions["warnings"] = warnings
    for feature in advisory_features:
        name = feature.get("name") or feature.get("kind") or "detail"
        reason = feature.get("reason") or feature.get("risk") or "not confirmed by drawing"
        warnings.append(f"Speculative skipped feature treated as warning: {name}: {reason}")


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
        request = ModelingExecutionRequest(
            result=result,
            intelligent_analysis_result=intelligent_analysis_result,
            geometry_data=geometry_data,
            output_structure=output_structure,
            extrude_height=extrude_height,
            missing_script_message=missing_script_message,
            script_failure_prefix=script_failure_prefix,
            completion_message=completion_message,
        )
        modeling_path_decision = intelligent_analysis_result.get("modeling_path_decision", {}) or {}
        modeling_path = modeling_path_decision.get("modeling_path")
        handler = self._path_handlers.get(modeling_path)
        if handler:
            result.modeling_path = modeling_path
            logger.info(
                "Intelligent processing routed to specialized modeling path"
                f" | path: {modeling_path}"
                f" | reason: {modeling_path_decision.get('reason', '')}"
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
            request.intelligent_analysis_result,
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
        intelligent_analysis_result: Dict[str, Any],
        output_structure: Dict[str, Path],
    ) -> Any:
        from src.model_generator.ai_script_runner import AIScriptRunner
        from src.reconstruction.revolve_executor import build_revolve_script

        candidate_paths = (
            intelligent_analysis_result.get("modeling_path_decision", {}) or {}
        ).get("candidate_paths", [])
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
        modeling_instructions = request.intelligent_analysis_result.get("modeling_instructions", {}) or {}
        ai_script_content = modeling_instructions.get("freecad_script")
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
                result.mark_failed(
                    f"{request.script_failure_prefix}: {run_result.get('error', 'unknown error')}"
                )
                logger.warning(result.error_message)
                return result

            if run_result.get("step_path"):
                result.output_paths["model_step"] = run_result["step_path"]
            if run_result.get("fcstd_path"):
                result.output_paths["model_fcstd"] = run_result["fcstd_path"]
            skipped_features = _normalize_feature_records(
                run_result.get("skipped_features")
                or modeling_instructions.get("skipped_features")
            )
            skipped_features, advisory_features = _split_skipped_features(skipped_features)
            _append_advisory_warnings(modeling_instructions, advisory_features)
            completed_features = _normalize_feature_records(
                run_result.get("completed_features")
                or modeling_instructions.get("completed_features")
            )
            if skipped_features:
                result.mark_partial_completed(
                    skipped_features=skipped_features,
                    completed_features=completed_features,
                    reason=(
                        run_result.get("partial_completion_reason")
                        or modeling_instructions.get("partial_completion_reason")
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
        except Exception as error:
            result.mark_failed(
                "AI script execution failed; intelligent processing will not fall back "
                f"to the generic modeler: {error}"
            )
            logger.warning(result.error_message)
            return result
