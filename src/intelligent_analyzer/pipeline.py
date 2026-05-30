#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能处理编排。

保留 IntelligentEngineeringAnalyzer 旧类名以兼容现有调用方；
当前职责是串联智能分析子过程，并把分析结果交给语义重建内核继续处理。
"""
import logging
from typing import Callable, Dict, List, Any, Optional, Mapping
from pathlib import Path

from .view_analyzer import EngineeringViewAnalyzer
from .llm_view_analyzer import LLMViewAnalyzer
from .dimension_extractor import DimensionExtractor
from .view_decision_payload import build_view_decision_payload
from .view_schema import build_standard_view_analysis
from src.utils.stage_confirmation import (
    StageConfirmationStopped,
    StageReview,
    ensure_stage_stop_message,
    request_stage_confirmation,
    resolve_stage_confirmation,
)
from src.utils.deepseek_options import STAGE_VIEW_ANALYSIS
from src.utils.stage_self_correction import (
    StageSelfCorrectionCase,
    StageSelfCorrectionSession,
    ValidationIssue,
)
from src.reconstruction import SemanticReconstructionPipeline
from src.reconstruction.clarification_response import ClarificationResponse

logger = logging.getLogger(__name__)

class IntelligentEngineeringAnalyzer:
    """
    智能处理编排器（保留旧类名）。

    负责组织视图初判、尺寸提取、视图语义校正和本地几何证据，
    再把结果交给语义重建内核；它不直接持有建模路径判定规则。
    """

    ANALYSIS_VERSION = "llm_view_classifier_v8_semantic_policy"

    def __init__(self, api_key: str, config: Optional[Dict] = None,
                 enable_cache: bool = True,
                 cache_dir: Optional[str] = None,
                 cache_ttl: Optional[int] = None):
        """
        初始化分析器

        参数:
            api_key: DeepSeek API密钥
            config: 配置字典
            enable_cache: 是否启用缓存
            cache_dir: 缓存目录
            cache_ttl: 缓存过期时间（秒）
        """
        self.api_key = api_key
        self.config = config or {}

        self.view_analyzer = EngineeringViewAnalyzer(config)
        self.llm_view_analyzer = LLMViewAnalyzer(api_key, config)
        self.dimension_extractor = DimensionExtractor(config)
        self.reconstruction_pipeline = SemanticReconstructionPipeline(api_key, config)
        self.stage_confirmation = resolve_stage_confirmation(self.config)

        self.enable_cache = enable_cache
        self.cache = None

        if self.enable_cache:
            try:
                from src.utils.cache import AnalysisCache
                from src.utils.config import get_analysis_cache_settings
                cache_settings = get_analysis_cache_settings(
                    self.config,
                    cache_dir=cache_dir,
                    cache_ttl=cache_ttl,
                )
                self.cache = AnalysisCache(
                    cache_dir=cache_settings["cache_dir"],
                    default_ttl=cache_settings["default_ttl"],
                    config=config,
                )
                logger.info("缓存系统已启用")
            except Exception as e:
                logger.warning(f"缓存系统初始化失败，将不使用缓存: {e}")
                self.cache = None

    def analyze_full(self, geometry_data: Dict[str, Any],
                     extrude_height: float = 10.0,
                     file_path: Optional[str] = None,
                     preview_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行智能处理编排，返回可供后续执行消费的智能分析结果

        参数:
            geometry_data: CAD解析得到的几何数据
            extrude_height: 默认拉伸高度
            file_path: 原始图纸文件路径（用于缓存）

        返回:
            完整分析结果字典
        """
        analysis_params = {"analysis_version": self.ANALYSIS_VERSION}

        # 尝试从缓存读取
        if self.cache and file_path:
            cached = self.cache.get(file_path, analysis_params=analysis_params)
            if cached:
                if self._is_cacheable_analysis_result(cached):
                    logger.info("从缓存加载分析结果")
                    return self._confirm_cached_stages(
                        cached,
                        geometry_data=geometry_data,
                        extrude_height=extrude_height,
                        file_path=file_path,
                        preview_path=preview_path,
                    )
                logger.info("忽略不可直接执行的分析缓存，重新运行智能分析")

        logger.info("=== 开始智能工程图纸分析 ===")

        # 1. 本地规则视图初判
        logger.info("步骤1: 本地规则分析视图结构...")
        rule_view_result = self.view_analyzer.analyze_views(
            geometry_data,
            source_name=file_path
        )

        # 2. 尺寸提取
        logger.info("步骤2: 提取尺寸标注...")
        dimension_result = self.dimension_extractor.extract_dimensions(geometry_data)

        # 3. 大模型视图语义校正
        logger.info("步骤3: LLM校正视图语义...")
        view_result = self.llm_view_analyzer.refine_view_analysis(
            geometry_data=geometry_data,
            rule_result=rule_view_result,
            dimension_data=dimension_result,
            file_path=file_path,
            preview_path=preview_path,
        )

        # 4. 本地几何关系分析 (STRtree, O(n log n))
        logger.info("步骤4: 本地几何关系分析...")
        local_analysis = self._analyze_local_fallback(geometry_data)

        # 5. 构建重建上下文
        logger.info("步骤5: 进入语义重建内核...")
        reconstruction_result = None
        view_retry_used = False
        view_self_correction_used = False
        while reconstruction_result is None:
            try:
                reconstruction_result = self.reconstruction_pipeline.run(
                    geometry_data=geometry_data,
                    view_analysis=view_result,
                    dimension_data=dimension_result,
                    local_relationships=local_analysis,
                    extrude_height=extrude_height,
                    file_path=file_path,
                    preview_path=preview_path,
                )
            except StageConfirmationStopped as stopped:
                decision = getattr(stopped, "result", None)
                if (
                    decision is not None
                    and getattr(decision, "requests_retry", False)
                    and getattr(decision, "stage", None) == "view_analysis"
                    and not view_retry_used
                ):
                    logger.info("用户要求重跑视图语义校正阶段，重新调用LLM视图校正")
                    view_retry_used = True
                    view_result = self.llm_view_analyzer.refine_view_analysis(
                        geometry_data=geometry_data,
                        rule_result=rule_view_result,
                        dimension_data=dimension_result,
                        file_path=file_path,
                        preview_path=preview_path,
                    )
                    view_result = self._with_view_retry_log(view_result)
                    continue
                if (
                    decision is not None
                    and getattr(decision, "requests_self_correction", False)
                    and getattr(decision, "stage", None) == "view_analysis"
                    and not view_self_correction_used
                ):
                    logger.info("用户要求视图语义校正模型自纠，重新生成视图分析")
                    view_self_correction_used = True
                    case = self._build_view_self_correction_case(
                        geometry_data=geometry_data,
                        rule_view_result=rule_view_result,
                        view_result=view_result,
                        dimension_result=dimension_result,
                        file_path=file_path,
                        confidence_threshold=getattr(
                            self.llm_view_analyzer,
                            "confidence_threshold",
                            0.60,
                        ),
                        generate=lambda req, file_path=None: (
                            self.llm_view_analyzer.generate_from_self_correction(
                                req,
                                geometry_data=geometry_data,
                                rule_result=rule_view_result,
                                file_path=file_path,
                            )
                        ),
                    )
                    correction_result = StageSelfCorrectionSession().self_correct(
                        case,
                        file_path=file_path,
                    )
                    view_result = correction_result.corrected_output or view_result
                    view_result = self._sync_schema_self_correction_log(view_result)
                    continue
                raise

        result = {
            "view_analysis": view_result,
            "rule_view_analysis": rule_view_result,
            "dimension_extraction": dimension_result,
            "local_relationships": local_analysis,
            **reconstruction_result,
        }

        logger.info("=== 智能分析完成 ===")

        # 保存到缓存
        if self.cache and file_path and self._is_cacheable_analysis_result(result):
            self.cache.set(
                file_path,
                result,
                analysis_params=analysis_params
            )
        elif self.cache and file_path:
            logger.info("Skipping analysis cache because result has transient provider failure")

        return result

    @staticmethod
    def _with_view_retry_log(view_result: Dict[str, Any]) -> Dict[str, Any]:
        """Record that the view analysis was regenerated by a supervision action."""
        if not isinstance(view_result, dict):
            return view_result
        updated = dict(view_result)
        updated.setdefault("stage_retry_applied", True)
        updated.setdefault("stage_retry_log", [{
            "stage": "view_analysis",
            "trigger": "user_requested_retry_stage",
            "result": "用户触发后已重跑视图语义校正阶段",
        }])
        schema_result = updated.get("schema_result")
        if isinstance(schema_result, dict):
            schema_result = dict(schema_result)
            schema_result.setdefault("stage_retry_applied", True)
            schema_result.setdefault("stage_retry_log", updated["stage_retry_log"])
            updated["schema_result"] = schema_result
        return updated

    @staticmethod
    def _build_view_self_correction_case(
        *,
        geometry_data: Dict[str, Any],
        rule_view_result: Dict[str, Any],
        view_result: Dict[str, Any],
        dimension_result: Dict[str, Any],
        file_path: Optional[str],
        confidence_threshold: float,
        generate: Callable[..., Dict[str, Any]],
    ) -> StageSelfCorrectionCase:
        schema_result = view_result.get("schema_result") or view_result
        previous_output = {
            "drawing_type": schema_result.get("drawing_type"),
            "views": schema_result.get("views", []),
            "relationships": schema_result.get("relationships", []),
            "confidence": schema_result.get("confidence"),
            "reason_summary": schema_result.get("reason_summary", ""),
            "warnings": schema_result.get("warnings", []),
        }
        rule_standard = build_standard_view_analysis(
            rule_view_result,
            confidence=0.72,
            reason_summary="本地规则初判结果，作为视图模型自纠的参考",
            source="rule",
        )
        stage_payload = build_view_decision_payload(
            geometry_data=geometry_data,
            rule_result=rule_view_result,
            rule_standard=rule_standard,
            dimension_data=dimension_result,
            file_path=file_path,
            confidence_threshold=confidence_threshold,
        )
        return StageSelfCorrectionCase(
            stage=STAGE_VIEW_ANALYSIS,
            round_index=1,
            max_rounds=2,
            stage_payload=stage_payload,
            previous_output=previous_output,
            validation_issues=[
                ValidationIssue(
                    code="user_requested_view_self_correction",
                    message="用户在视图语义校正阶段要求模型自纠",
                    severity="warning",
                    fixable=True,
                    impact="用户认为当前视图识别或投影关系可能需要复核",
                    correction_target="重新检查视图划分、视图角色、投影关系和风险说明",
                )
            ],
            output_contract={
                "required_fields": [
                    "analysis_id",
                    "timestamp",
                    "drawing_type",
                    "views",
                    "relationships",
                    "confidence",
                    "evidence",
                    "reason_summary",
                    "warnings",
                ],
                "drawing_type_values": [
                    "single_view",
                    "two_view",
                    "three_view",
                    "assembly_drawing",
                    "section_view",
                    "unknown",
                ],
            },
            generate=generate,
            correction_goal="用户要求复核并重新生成视图语义校正结果；不得新增图纸事实。",
            log_trigger="user_requested_view_self_correction",
            log_result="用户触发后已重新生成视图语义校正结果",
        )

    @staticmethod
    def _sync_schema_self_correction_log(view_result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(view_result, dict):
            return view_result
        updated = dict(view_result)
        schema_result = updated.get("schema_result")
        if isinstance(schema_result, dict):
            schema_result = dict(schema_result)
            schema_result.setdefault("self_correction_applied", True)
            schema_result.setdefault(
                "self_correction_log",
                updated["self_correction_log"],
            )
            updated["schema_result"] = schema_result
        return updated

    def continue_with_clarification(
        self,
        clarification_context: Dict[str, Any],
        clarification_answers: Mapping[str, Any] | ClarificationResponse,
    ) -> Dict[str, Any]:
        """复用首次分析结果，从语义裁决阶段继续。"""
        return self.reconstruction_pipeline.continue_with_clarification(
            clarification_context,
            clarification_answers,
        )

    def _confirm_cached_stages(
        self,
        analysis_result: Dict[str, Any],
        *,
        geometry_data: Optional[Dict[str, Any]] = None,
        extrude_height: float = 10.0,
        file_path: Optional[str] = None,
        preview_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replay GUI stage confirmations when a complete analysis comes from cache."""
        confirmation = getattr(self, "stage_confirmation", None)
        if confirmation is None:
            confirmation = resolve_stage_confirmation(getattr(self, "config", {}))
            self.stage_confirmation = confirmation

        view_review = StageReview("view_analysis", {
            "view_analysis": analysis_result.get("view_analysis", {}),
            "dimension_data": analysis_result.get("dimension_extraction", {}),
            "semantic_policy": analysis_result.get("semantic_policy", {}),
        })
        view_decision = request_stage_confirmation(confirmation, view_review)
        if not view_decision.continue_processing:
            raise StageConfirmationStopped(
                ensure_stage_stop_message(view_decision, "view_analysis")
            )

        clarification_questions = (
            analysis_result.get("semantic_policy", {}) or {}
        ).get("clarification_questions", [])
        if clarification_questions:
            return

        part_semantics = analysis_result.get("part_semantics")
        if part_semantics:
            semantic_review = StageReview("semantic_reconstruction", {
                "part_semantics": part_semantics,
                "semantic_policy": analysis_result.get("semantic_policy", {}),
            })
            semantic_decision = request_stage_confirmation(confirmation, semantic_review)
            if not semantic_decision.continue_processing:
                if (
                    getattr(semantic_decision, "requests_retry", False)
                    or getattr(semantic_decision, "requests_retry_with_partial", False)
                ):
                    return self.reconstruction_pipeline.rerun_semantic_reconstruction_from_cached_analysis(
                        analysis_result=analysis_result,
                        geometry_data=geometry_data or {},
                        extrude_height=extrude_height,
                        file_path=file_path,
                        preview_path=preview_path,
                        retained_items=getattr(semantic_decision, "retained_items", {}) or {},
                    )
                raise StageConfirmationStopped(
                    ensure_stage_stop_message(
                        semantic_decision,
                        "semantic_reconstruction",
                    )
                )

        modeling_instructions = analysis_result.get("modeling_instructions") or {}
        if self._should_confirm_cached_modeling_generation(modeling_instructions):
            modeling_review = StageReview("modeling_generation", {
                "modeling_instructions": modeling_instructions,
                "modeling_path_decision": analysis_result.get("modeling_path_decision", {}),
            })
            modeling_decision = request_stage_confirmation(confirmation, modeling_review)
            if not modeling_decision.continue_processing:
                if (
                    getattr(modeling_decision, "requests_retry", False)
                    or getattr(modeling_decision, "requests_retry_with_partial", False)
                ):
                    return self.reconstruction_pipeline.rerun_modeling_generation_from_cached_analysis(
                        analysis_result=analysis_result,
                        file_path=file_path,
                        retained_items=getattr(modeling_decision, "retained_items", {}) or {},
                    )
                raise StageConfirmationStopped(
                    ensure_stage_stop_message(
                        modeling_decision,
                        "modeling_generation",
                    )
                )
        return analysis_result

    @staticmethod
    def _should_confirm_cached_modeling_generation(
        modeling_instructions: Dict[str, Any],
    ) -> bool:
        if not isinstance(modeling_instructions, dict):
            return False
        if modeling_instructions.get("clarification_questions"):
            return False
        if modeling_instructions.get("blocked_by_clarification"):
            return False
        if modeling_instructions.get("blocked_by_path_contract"):
            return False
        if modeling_instructions.get("routed_to_planar_extrude"):
            return False
        if modeling_instructions.get("routed_to_revolve"):
            return False
        return "freecad_script" in modeling_instructions or bool(
            modeling_instructions.get("blocked_by_task_readiness")
        )

    def _is_semantic_confidence_sufficient(self, part_semantics: Dict[str, Any]) -> bool:
        """兼容入口；语义置信度判断已迁入 reconstruction。"""
        if hasattr(self, "reconstruction_pipeline"):
            return self.reconstruction_pipeline._is_semantic_confidence_sufficient(part_semantics)
        confidence = float(part_semantics.get("confidence") or 0.0)
        threshold = float(self.config.get("semantic_min_confidence", 0.70))
        return confidence >= threshold

    @classmethod
    def _is_cacheable_analysis_result(cls, analysis_result: Dict[str, Any]) -> bool:
        """判断分析结果是否可缓存；只缓存完整的、可直接继续执行的结果。"""
        if cls._has_clarification_questions(analysis_result):
            logger.info("分析结果含未决澄清问题，不写入缓存")
            return False
        modeling_result = analysis_result.get("modeling_instructions", {}) or {}
        if modeling_result.get("blocked_by_task_readiness"):
            logger.info("分析结果被建模任务就绪度阻塞，不写入缓存")
            return False
        if not modeling_result.get("blocked_by_semantic_confidence"):
            return True
        part_semantics = analysis_result.get("part_semantics", {}) or {}
        warnings = list(part_semantics.get("warnings", []) or [])
        warnings.extend(modeling_result.get("warnings", []) or [])
        return not any(cls._looks_like_transient_llm_failure(item) for item in warnings)

    @staticmethod
    def _has_clarification_questions(analysis_result: Dict[str, Any]) -> bool:
        """检查分析结果是否包含未决澄清问题。"""
        semantic_policy = analysis_result.get("semantic_policy", {}) or {}
        if semantic_policy.get("clarification_questions"):
            return True
        modeling_result = analysis_result.get("modeling_instructions", {}) or {}
        if modeling_result.get("clarification_questions"):
            return True
        if modeling_result.get("blocked_by_clarification"):
            return True
        if modeling_result.get("blocked_by_path_contract"):
            return True
        if modeling_result.get("blocked_by_task_readiness"):
            return True
        return False

    @staticmethod
    def _looks_like_transient_llm_failure(message: Any) -> bool:
        text = str(message or "").lower()
        transient_markers = (
            "connection error",
            "connect error",
            "connection reset",
            "timeout",
            "timed out",
            "readtimeout",
            "api connection",
            "network",
            "temporarily unavailable",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "rate limit",
            "429",
            "502",
            "503",
            "504",
        )
        return any(marker in text for marker in transient_markers)

    def save_results(self, analysis_result: Dict[str, Any],
                     output_dir: str, base_name: str = "analysis") -> Dict[str, str]:
        """
        保存分析结果到文件

        参数:
            analysis_result: 分析结果
            output_dir: 输出目录
            base_name: 文件基名
        """
        import json

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_paths: Dict[str, str] = {}

        # 保存完整分析结果
        full_path = output_path / f"{base_name}_full.json"
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        saved_paths["analysis_full"] = str(full_path)

        # 保存FreeCAD脚本
        if "modeling_instructions" in analysis_result:
            script = analysis_result["modeling_instructions"].get("freecad_script", "")
            if script:
                script_path = output_path / f"{base_name}_freecad.py"
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script)
                saved_paths["freecad_script"] = str(script_path)
                logger.info(f"FreeCAD脚本已保存: {script_path}")

        # 保存分析报告
        report = self._generate_report(analysis_result)
        report_path = output_path / f"{base_name}_report.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        saved_paths["analysis_report"] = str(report_path)
        return saved_paths

    def _entity_to_shapely(self, entity: Dict):
        import shapely.geometry as sg

        entity_type = entity.get("type")

        if entity_type == "LINE":
            return sg.LineString([entity["start"][:2], entity["end"][:2]])
        elif entity_type == "CIRCLE":
            return sg.Point(entity["center"][:2]).buffer(entity["radius"])
        elif entity_type in ("LWPOLYLINE", "ELLIPSE", "SPLINE"):
            points = [p[:2] for p in entity.get("vertices", [])]
            if not points:
                return None
            closed = entity.get("closed", False)
            if closed and len(points) >= 3:
                return sg.Polygon(points)
            else:
                return sg.LineString(points)
        elif entity_type == "ARC":
            return None

        return None

    def _calculate_relationship(self, shape1, shape2) -> str:
        if shape1.contains(shape2) or shape2.contains(shape1):
            return "包含"
        elif shape1.intersects(shape2):
            if shape1.touches(shape2):
                return "相切"
            else:
                return "相交"
        else:
            return "相离"

    def _analyze_local_fallback(self, geometry_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            import shapely.geometry as sg
            from shapely.strtree import STRtree

            entities = geometry_data.get("entities", [])

            shapes = []
            for i, entity in enumerate(entities):
                shape = self._entity_to_shapely(entity)
                if shape:
                    shapes.append((i, shape, entity))

            if len(shapes) < 2:
                return None

            shapely_objects = [s[1] for s in shapes]
            tree = STRtree(shapely_objects)

            pairs = []
            for i in range(len(shapes)):
                idx1, shape1, _ = shapes[i]
                candidates = tree.query(shape1)
                for j in candidates:
                    if j <= i:
                        continue
                    idx2, shape2, _ = shapes[j]
                    relationship = self._calculate_relationship(shape1, shape2)
                    if relationship != "相离":
                        pairs.append({
                            "id1": idx1,
                            "id2": idx2,
                            "relationship": relationship
                        })

            return {
                "entity_pairs": pairs,
                "summary": f"本地分析: {len(entities)} 实体, {len(pairs)} 对关系",
                "method": "local_fallback"
            }

        except ImportError:
            logger.warning("Shapely 不可用，跳过本地几何分析回退")
            return None

    def _generate_report(self, analysis_result: Dict[str, Any]) -> str:
        """生成分析报告"""
        lines = []
        lines.append("="*60)
        lines.append("工程图纸智能分析报告")
        lines.append("="*60)
        lines.append("")

        # 视图分析
        view_data = analysis_result.get("view_analysis", {})
        lines.append("【视图分析】")
        views = view_data.get("views", [])
        lines.append(f"- 识别视图数: {len(views)}")
        for view in views:
            lines.append(f"  * {view.get('type', view.get('name'))}: {view.get('entity_count', 0)} 个实体")
        lines.append("")

        # 尺寸分析
        dim_data = analysis_result.get("dimension_extraction", {})
        lines.append("【尺寸提取】")
        lines.append(f"- 提取尺寸数: {dim_data.get('total', 0)}")
        classified = dim_data.get("classified", {})
        for dim_type, dims in classified.items():
            lines.append(f"  * {dim_type}: {len(dims)} 个")
        lines.append("")

        # 建模指令
        model_data = analysis_result.get("modeling_instructions", {})
        lines.append("【建模策略】")
        lines.append(model_data.get("analysis_summary", "无分析总结"))
        lines.append("")
        lines.append(model_data.get("modeling_strategy", "无建模策略"))
        lines.append("")

        lines.append("="*60)
        return "\n".join(lines)
