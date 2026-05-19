#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能处理编排。

保留 IntelligentEngineeringAnalyzer 旧类名以兼容现有调用方；
当前职责是串联智能分析子过程，并把分析结果交给语义重建内核继续处理。
"""
import logging
from typing import Dict, List, Any, Optional, Mapping
from pathlib import Path

from .view_analyzer import EngineeringViewAnalyzer
from .llm_view_analyzer import LLMViewAnalyzer
from .dimension_extractor import DimensionExtractor
from src.utils.stage_confirmation import (
    StageConfirmationStopped,
    StageReview,
    ensure_stage_stop_message,
    request_stage_confirmation,
    resolve_stage_confirmation,
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

        ??:
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
                cache_ttl = cache_ttl or self.config.get('cache_ttl', 3600 * 24 * 7)
                cache_dir = cache_dir or self.config.get('cache_dir', '.cache/analysis')
                self.cache = AnalysisCache(cache_dir=cache_dir, default_ttl=cache_ttl, config=config)
                logger.info("缓存系统已启用")
            except Exception as e:
                logger.warning(f"缓存系统初始化失败，将不使用缓存: {e}")
                self.cache = None

    def analyze_full(self, geometry_data: Dict[str, Any],
                     extrude_height: float = 10.0,
                     file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行智能处理编排，返回可供后续执行消费的智能分析结果

        ??:
            geometry_data: CAD解析得到的几何数据
            extrude_height: 默认拉伸高度
            file_path: 原始图纸文件路径（用于缓存）

        ??:
            完整分析结果字典
        """
        analysis_params = {"analysis_version": self.ANALYSIS_VERSION}

        # 尝试从缓存读取
        if self.cache and file_path:
            cached = self.cache.get(file_path, extrude_height, analysis_params=analysis_params)
            if cached:
                logger.info("从缓存加载分析结果")
                self._confirm_cached_stages(cached)
                return cached

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
        )

        # 4. 本地几何关系分析 (STRtree, O(n log n))
        logger.info("步骤4: 本地几何关系分析...")
        local_analysis = self._analyze_local_fallback(geometry_data)

        # 5. 构建重建上下文
        logger.info("步骤5: 进入语义重建内核...")
        reconstruction_result = self.reconstruction_pipeline.run(
            geometry_data=geometry_data,
            view_analysis=view_result,
            dimension_data=dimension_result,
            local_relationships=local_analysis,
            extrude_height=extrude_height,
            file_path=file_path,
        )

        result = {
            "view_analysis": view_result,
            "rule_view_analysis": rule_view_result,
            "dimension_extraction": dimension_result,
            "local_relationships": local_analysis,
            **reconstruction_result,
        }

        logger.info("=== 智能分析完成 ===")

        # 保存到缓存
        if self.cache and file_path:
            self.cache.set(
                file_path,
                extrude_height,
                result,
                analysis_params=analysis_params
            )

        return result

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

    def _confirm_cached_stages(self, analysis_result: Dict[str, Any]) -> None:
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
                raise StageConfirmationStopped(
                    ensure_stage_stop_message(
                        semantic_decision,
                        "semantic_reconstruction",
                    )
                )

    def _is_semantic_confidence_sufficient(self, part_semantics: Dict[str, Any]) -> bool:
        """兼容入口；语义置信度判断已迁入 reconstruction。"""
        if hasattr(self, "reconstruction_pipeline"):
            return self.reconstruction_pipeline._is_semantic_confidence_sufficient(part_semantics)
        confidence = float(part_semantics.get("confidence") or 0.0)
        threshold = float(self.config.get("semantic_min_confidence", 0.70))
        return confidence >= threshold

    def save_results(self, analysis_result: Dict[str, Any],
                     output_dir: str, base_name: str = "analysis") -> None:
        """
        保存分析结果到文件

        ??:
            analysis_result: 分析结果
            output_dir: 输出目录
            base_name: 文件基名
        """
        import json

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 保存完整分析结果
        with open(output_path / f"{base_name}_full.json", 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)

        # 保存FreeCAD脚本
        if "modeling_instructions" in analysis_result:
            script = analysis_result["modeling_instructions"].get("freecad_script", "")
            if script:
                script_path = output_path / f"{base_name}_freecad.py"
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script)
                logger.info(f"FreeCAD脚本已保存: {script_path}")

        # 保存分析报告
        report = self._generate_report(analysis_result)
        with open(output_path / f"{base_name}_report.txt", 'w', encoding='utf-8') as f:
            f.write(report)

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
