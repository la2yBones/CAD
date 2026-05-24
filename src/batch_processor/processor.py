#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD处理器组件
封装单个图纸的完整处理流程
"""

import json
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import traceback

from src.batch_processor.modeling_execution import IntelligentModelingExecutor
from src.reconstruction.clarification_response import ClarificationResponse
from src.utils.config import get_analysis_cache_settings
from src.utils.stage_confirmation import StageConfirmationStopped

logger = logging.getLogger(__name__)


class PipelineStatus(str, Enum):
    """单文件处理流程的真实状态。"""

    COMPLETED = "completed"
    PARTIAL_COMPLETED = "partial_completed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    STOPPED_BY_USER = "stopped_by_user"


class CADProcessResult:
    """处理结果封装类"""

    def __init__(
        self,
        success: bool,
        input_file: str,
        mode: Optional[str] = None,
        modeling_path: Optional[str] = None,
    ):
        self.success = success
        self.status = PipelineStatus.COMPLETED if success else PipelineStatus.FAILED
        self.input_file = input_file
        self.mode = mode
        self.modeling_path = modeling_path
        self.geometry_data: Optional[Dict] = None
        self.relationships: Optional[Dict] = None
        self.intelligent_analysis: Optional[Dict] = None  # 智能分析结果
        self.clarification_questions: list[Dict[str, Any]] = []
        self.clarification_context: Optional[Dict[str, Any]] = None
        self.completed_features: list[Dict[str, Any]] = []
        self.skipped_features: list[Dict[str, Any]] = []
        self.partial_completion_reason: Optional[str] = None
        self.stage_stop_action: Optional[str] = None
        self.stage_stop_stage: Optional[str] = None
        self.output_paths: Dict[str, str] = {}
        self.error_message: Optional[str] = None
        self.entity_count: int = 0

    def mark_completed(self) -> None:
        self.success = True
        self.status = PipelineStatus.COMPLETED
        self.completed_features = []
        self.skipped_features = []
        self.partial_completion_reason = None

    def mark_partial_completed(
        self,
        *,
        skipped_features: Optional[list[Dict[str, Any]]] = None,
        completed_features: Optional[list[Dict[str, Any]]] = None,
        reason: Optional[str] = None,
    ) -> None:
        self.success = True
        self.status = PipelineStatus.PARTIAL_COMPLETED
        self.skipped_features = skipped_features or []
        self.completed_features = completed_features or []
        self.partial_completion_reason = reason or "模型主体已生成并导出，部分细节被跳过"

    def mark_failed(self, error_message: Optional[str] = None) -> None:
        self.success = False
        self.status = PipelineStatus.FAILED
        if error_message is not None:
            self.error_message = error_message

    def mark_needs_clarification(
        self,
        questions: list[Dict[str, Any]],
        clarification_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.success = False
        self.status = PipelineStatus.NEEDS_CLARIFICATION
        self.clarification_questions = questions
        self.clarification_context = clarification_context

    def mark_stopped_by_user(
        self,
        message: Optional[str] = None,
        action: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        self.success = False
        self.status = PipelineStatus.STOPPED_BY_USER
        self.error_message = message or "用户停止处理"
        self.stage_stop_action = action or "stop"
        self.stage_stop_stage = stage

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'status': self.status.value,
            'input_file': self.input_file,
            'mode': self.mode,
            'modeling_path': self.modeling_path,
            'entity_count': self.entity_count,
            'output_paths': self.output_paths,
            'error_message': self.error_message,
            'has_intelligent_analysis': self.intelligent_analysis is not None,
            'clarification_questions': self.clarification_questions,
            'has_clarification_context': self.clarification_context is not None,
            'completed_features': self.completed_features,
            'skipped_features': self.skipped_features,
            'partial_completion_reason': self.partial_completion_reason,
            'stage_stop_action': self.stage_stop_action,
            'stage_stop_stage': self.stage_stop_stage,
        }


class CADProcessor:
    """
    CAD图纸处理器
    封装单个图纸从解析到导出的完整流程
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化处理器

        参数:
            config: 配置字典
        """
        self.config = config or {}
        self._init_components()

    def _init_components(self):
        """初始化各个处理组件"""
        self._cad_parser = None
        self._modeler = None
        self._modeling_executor = None

    def _notify_progress_stage(self, stage: str, text: str) -> None:
        callback = self.config.get("_progress_callback")
        if not callback:
            return
        try:
            callback(stage, text)
        except Exception as error:
            logger.debug(f"进度回调失败: {error}")

    def _get_parser(self):
        """获取或创建CAD解析器"""
        if self._cad_parser is None:
            from src.cad_parser import CADParser
            self._cad_parser = CADParser
        return self._cad_parser

    def _get_modeler(self):
        """获取或创建模型生成器"""
        if self._modeler is None:
            from src.model_generator import PlanarExtrudeModeler
            self._modeler = PlanarExtrudeModeler
        return self._modeler

    def _get_modeling_executor(self):
        if getattr(self, "_modeling_executor", None) is None:
            self._modeling_executor = IntelligentModelingExecutor(
                self.config,
                self._get_modeler,
            )
        return self._modeling_executor

    def _analysis_cache_settings(self) -> Dict[str, Any]:
        return get_analysis_cache_settings(self.config)

    def _prepare_intelligent_view_context(
        self,
        geometry_data: Dict[str, Any],
        intelligent_analysis_result: Optional[Dict[str, Any]] = None,
        source_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """为统一智能处理准备可供后续语义校正使用的视图上下文。"""
        view_analysis = {}

        if intelligent_analysis_result:
            view_analysis = intelligent_analysis_result.get("view_analysis") or {}

        if not view_analysis:
            try:
                from src.intelligent_analyzer.view_analyzer import EngineeringViewAnalyzer
                view_analysis = EngineeringViewAnalyzer(self.config).analyze_views(
                    geometry_data,
                    source_name=source_name
                )
            except Exception as e:
                logger.warning(f"视图识别失败，暂按单视图处理: {e}")
                return {}

        return view_analysis

    def _is_fallback_modeling_result(self, modeling_result: Dict[str, Any]) -> bool:
        """识别 AI 建模失败后生成的本地降级脚本。"""
        if modeling_result.get("blocked_by_semantic_confidence"):
            return True
        summary = str(modeling_result.get("analysis_summary", ""))
        strategy = str(modeling_result.get("modeling_strategy", ""))
        warnings = " ".join(str(item) for item in modeling_result.get("warnings", []) or [])

        failure_text = " ".join([summary, strategy, warnings])
        hard_failure_markers = (
            "分析失败",
            "生成失败",
            "使用降级建模方法",
            "降级建模",
            "使用基础建模方法",
            "基础拉伸降级",
        )
        if any(marker in failure_text for marker in hard_failure_markers):
            return True

        script = str(modeling_result.get("freecad_script", ""))
        fallback_script_markers = (
            "_group_entities_into_contours",
            "for contour in contours",
            "GeneratedModel",
            "extrude_height =",
        )
        return sum(marker in script for marker in fallback_script_markers) >= 3

    def process_single_file(self, file_path: str, output_structure: Dict[str, Path],
                            extrude_height: float = 10.0,
                            enable_analysis: bool = True) -> CADProcessResult:
        """
        处理单个CAD文件

        参数:
            file_path: CAD文件路径
            output_structure: 输出结构字典
            extrude_height: 拉伸高度
            enable_analysis: 是否启用AI分析

        返回:
            处理结果对象
        """
        result = CADProcessResult(
            success=False,
            input_file=file_path,
            mode="basic",
            modeling_path="planar_extrude",
        )

        try:
            logger.info(f"开始处理: {Path(file_path).name}")

            # 1. 解析CAD
            parser = self._get_parser()(file_path, self.config.get("dxf_parser", {}))
            geometry_data = parser.parse()
            result.geometry_data = geometry_data
            result.entity_count = len(geometry_data.get('entities', []))
            logger.info(f"解析完成，提取到 {result.entity_count} 个实体")

            # 保存几何数据
            if 'geometry' in output_structure:
                parser.export_json(str(output_structure['geometry']))
                result.output_paths['geometry'] = str(output_structure['geometry'])

            # 尝试可视化
            if 'visualization' in output_structure:
                try:
                    parser.visualize(str(output_structure['visualization']))
                    result.output_paths['visualization'] = str(output_structure['visualization'])
                except Exception as e:
                    logger.warning(f"可视化失败: {e}")

            # 2. 统一智能分析（视图识别 + 尺寸提取 + 几何关系 + 建模指令）
            relationships = {}
            if enable_analysis:
                api_key = self.config.get("api", {}).get("deepseek", {}).get("api_key", "")
                if api_key and api_key != "your-deepseek-api-key-here":
                    try:
                        from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
                        cache_settings = self._analysis_cache_settings()
                        analyzer = IntelligentEngineeringAnalyzer(
                            api_key,
                            self.config.get("api", {}).get("deepseek", {}),
                            enable_cache=cache_settings["enabled"],
                            cache_dir=cache_settings["cache_dir"],
                            cache_ttl=cache_settings["default_ttl"]
                        )
                        intelligent_analysis_result = analyzer.analyze_full(
                            geometry_data,
                            extrude_height,
                            file_path=str(file_path)
                        )
                        result.intelligent_analysis = intelligent_analysis_result
                        relationships = intelligent_analysis_result.get("modeling_instructions", {})
                        logger.info("智能分析完成")
                    except Exception as e:
                        logger.warning(f"智能分析失败，使用纯几何建模: {e}")

            # 3. 生成3D模型
            modeler_config = {}
            if "freecad" in self.config:
                modeler_config.update(self.config.get("freecad", {}))
            modeler_config["default_extrude_height"] = extrude_height

            modeler = self._get_modeler()(modeler_config)
            modeler.generate(geometry_data, relationships)

            # 导出模型
            if 'model_step' in output_structure:
                export_path = str(output_structure['model_step'])
                export_success = modeler.export(export_path, "STEP")
                if export_success and Path(export_path).exists():
                    result.output_paths['model_step'] = export_path
                    logger.info(f"STEP模型已确认保存: {export_path}")
                else:
                    logger.warning(f"STEP模型可能未正确保存: {export_path}")

            if 'model_stl' in output_structure:
                try:
                    stl_path = str(output_structure['model_stl'])
                    if modeler.export(stl_path, "STL") and Path(stl_path).exists():
                        result.output_paths['model_stl'] = stl_path
                except Exception as e:
                    logger.warning(f"STL导出失败: {e}")

            modeler.close()

            result.mark_completed()
            logger.info(f"处理完成: {Path(file_path).name}")

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"处理失败 {file_path}: {e}")
            logger.error(traceback.format_exc())

        return result

    def process_with_intelligent_analysis(self, file_path: str, output_structure: Dict[str, Path],
                                         extrude_height: float = 10.0) -> CADProcessResult:
        """
        使用统一智能处理处理图纸。

        参数:
            file_path: CAD文件路径
            output_structure: 输出结构
            extrude_height: 拉伸高度

        返回:
            处理结果
        """
        result = CADProcessResult(
            success=False,
            input_file=file_path,
            mode="intelligent",
            modeling_path="semantic_reconstruction",
        )

        try:
            logger.info(f"开始智能分析处理: {Path(file_path).name}")

            # 1. 解析CAD
            self._notify_progress_stage("parsing", "解析中")
            parser = self._get_parser()(file_path, self.config.get("dxf_parser", {}))
            geometry_data = parser.parse()
            result.geometry_data = geometry_data
            result.entity_count = len(geometry_data.get('entities', []))
            logger.info(f"解析完成，提取到 {result.entity_count} 个实体")

            # 保存几何数据
            if 'geometry' in output_structure:
                parser.export_json(str(output_structure['geometry']))
                result.output_paths['geometry'] = str(output_structure['geometry'])

            view_analysis = self._prepare_intelligent_view_context(
                geometry_data,
                source_name=file_path
            )

            # 2. 智能分析
            api_key = self.config.get("api", {}).get("deepseek", {}).get("api_key", "")
            has_ai_script = False
            ai_script_content = None
            modeling_instructions = {}

            if api_key and api_key != "your-deepseek-api-key-here":
                try:
                    self._notify_progress_stage("ai_analysis", "AI 分析中")
                    from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
                    cache_settings = self._analysis_cache_settings()
                    analyzer = IntelligentEngineeringAnalyzer(
                        api_key,
                        self.config.get("api", {}).get("deepseek", {}),
                        enable_cache=cache_settings["enabled"],
                        cache_dir=cache_settings["cache_dir"],
                        cache_ttl=cache_settings["default_ttl"]
                    )
                    intelligent_analysis_result = analyzer.analyze_full(
                        geometry_data, 
                        extrude_height, 
                        file_path=str(file_path)
                    )
                    result.intelligent_analysis = intelligent_analysis_result

                    clarification_questions = self._collect_clarification_questions(
                        intelligent_analysis_result
                    )
                    if clarification_questions:
                        result.mark_needs_clarification(
                            clarification_questions,
                            intelligent_analysis_result.get("clarification_context"),
                        )
                        logger.info("语义裁决需要用户澄清，已暂停智能建模")
                        return result

                    # 保存分析结果
                    self._notify_progress_stage("finalizing", "保存分析结果")
                    output_dir = output_structure.get('directory', Path('.') / 'output')
                    base_name = Path(file_path).stem
                    analyzer.save_results(intelligent_analysis_result, str(output_dir), base_name)
                    
                    # 显示缓存状态
                    if intelligent_analysis_result.get('_cache_hit'):
                        logger.info("智能分析已从缓存加载")
                    else:
                        logger.info("智能分析完成并已缓存")
                    
                    # 获取AI生成的脚本
                    if 'modeling_instructions' in intelligent_analysis_result:
                        modeling_instructions = intelligent_analysis_result['modeling_instructions']
                        ai_script_content = modeling_instructions.get('freecad_script')
                        has_ai_script = bool(ai_script_content)

                    view_analysis = self._prepare_intelligent_view_context(
                        geometry_data,
                        intelligent_analysis_result,
                        source_name=file_path
                    )
                        
                except StageConfirmationStopped as stopped:
                    result.mark_stopped_by_user(
                        str(stopped),
                        action=getattr(stopped.result, "action", None),
                        stage=getattr(stopped.result, "stage", None),
                    )
                    logger.info(
                        "%s | action=%s | stage=%s",
                        result.error_message,
                        result.stage_stop_action,
                        result.stage_stop_stage,
                    )
                    return result
                except Exception as e:
                    result.error_message = f"智能分析失败，未进入建模阶段: {e}"
                    logger.warning(result.error_message)
                    logger.warning(traceback.format_exc())
                    return result
            else:
                result.error_message = "统一智能处理需要有效的 DeepSeek API Key，未进入建模阶段"
                logger.warning(result.error_message)
                return result

            if has_ai_script and self._is_fallback_modeling_result(modeling_instructions):
                result.error_message = (
                    "AI 未能生成可靠的建模脚本，当前结果属于基础拉伸降级方案；"
                    "统一智能处理不会调用通用建模器兜底"
                )
                logger.warning(result.error_message)
                return result

            if self._needs_pre_modeling_clarification(modeling_instructions):
                result.mark_needs_clarification(
                    self._build_pre_modeling_clarification_questions(modeling_instructions),
                    self._build_pre_modeling_clarification_context(
                        result.intelligent_analysis or {},
                        geometry_data=geometry_data,
                        extrude_height=extrude_height,
                        file_path=file_path,
                    ),
                )
                logger.info("建模指令表明主体实体无法生成，已转入用户澄清")
                return result

            self._notify_progress_stage("modeling", "建模中")
            modeled_result = self._execute_intelligent_modeling_path(
                result=result,
                intelligent_analysis_result=result.intelligent_analysis,
                geometry_data=geometry_data,
                output_structure=output_structure,
                extrude_height=extrude_height,
                missing_script_message="未获得可执行的 AI FreeCAD 建模脚本；统一智能处理不会调用通用建模器兜底",
                script_failure_prefix="AI脚本执行失败，统一智能处理不会调用通用建模器兜底",
                completion_message=f"智能分析处理完成: {Path(file_path).name}",
            )
            self._attach_partial_modeling_clarification(
                modeled_result,
                result.intelligent_analysis,
                geometry_data=geometry_data,
                extrude_height=extrude_height,
                file_path=file_path,
            )
            return modeled_result

        except StageConfirmationStopped as stopped:
            result.mark_stopped_by_user(
                str(stopped),
                action=getattr(stopped.result, "action", None),
                stage=getattr(stopped.result, "stage", None),
            )
            logger.info(
                "%s | action=%s | stage=%s",
                result.error_message,
                result.stage_stop_action,
                result.stage_stop_stage,
            )
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"智能分析处理失败: {e}")
            logger.error(traceback.format_exc())

        return result

    @staticmethod
    def _collect_clarification_questions(intelligent_analysis_result: Dict[str, Any]) -> list[Dict[str, Any]]:
        semantic_questions = (
            intelligent_analysis_result.get("semantic_policy", {}) or {}
        ).get("clarification_questions", [])
        path_questions = (
            intelligent_analysis_result.get("modeling_instructions", {}) or {}
        ).get("clarification_questions", [])
        return CADProcessor._deduplicate_clarification_questions(
            list(semantic_questions or []) + list(path_questions or [])
        )

    @staticmethod
    def _deduplicate_clarification_questions(questions: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        deduplicated = []
        seen_keys = set()
        for question in questions:
            if not isinstance(question, dict):
                continue

            question_id = str(question.get("id") or "").strip().lower()
            question_text = str(question.get("text") or question.get("question") or "")
            normalized_text = " ".join(question_text.split()).lower()

            keys = []
            if question_id:
                keys.append(f"id:{question_id}")
            if normalized_text:
                keys.append(f"text:{normalized_text}")

            if keys and any(key in seen_keys for key in keys):
                continue

            seen_keys.update(keys)
            deduplicated.append(question)
        return deduplicated

    @classmethod
    def _needs_pre_modeling_clarification(cls, modeling_instructions: Dict[str, Any]) -> bool:
        """Pause before FreeCAD when instructions admit the main solid cannot be built."""
        if not modeling_instructions:
            return False
        if modeling_instructions.get("completed_features"):
            return False

        skipped = modeling_instructions.get("skipped_features") or []
        if isinstance(skipped, dict):
            skipped = [skipped]
        if not isinstance(skipped, list):
            skipped = []
        if any(cls._is_required_body_skipped_feature(feature) for feature in skipped):
            return True

        warnings = modeling_instructions.get("warnings", []) or []
        if not isinstance(warnings, list):
            warnings = [warnings]
        text = " ".join(
            str(item)
            for item in [
                modeling_instructions.get("analysis_summary", ""),
                modeling_instructions.get("modeling_strategy", ""),
                modeling_instructions.get("partial_completion_reason", ""),
                *warnings,
            ]
        ).lower()
        no_solid_markers = (
            "no valid shape",
            "cannot generate solid",
            "no solid",
            "无法生成solid",
            "无法生成实体",
            "不生成实体",
            "缺失拉伸深度",
            "主体拉伸深度缺失",
        )
        return any(marker in text for marker in no_solid_markers)

    @staticmethod
    def _is_required_body_skipped_feature(feature: Any) -> bool:
        if not isinstance(feature, dict):
            return False
        text = " ".join(
            str(feature.get(key, ""))
            for key in ("name", "kind", "reason", "risk")
        ).lower()
        body_markers = (
            "base",
            "body",
            "profile",
            "main",
            "主体",
            "基体",
            "基座",
            "外轮廓",
        )
        failure_markers = (
            "missing",
            "cannot",
            "failed",
            "缺失",
            "无法",
            "失败",
            "未生成",
        )
        return any(marker in text for marker in body_markers) and any(
            marker in text for marker in failure_markers
        )

    @staticmethod
    def _build_pre_modeling_clarification_questions(
        modeling_instructions: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        skipped_text = CADProcessor._format_skipped_features_for_question(
            modeling_instructions.get("skipped_features") or []
        )
        reason = skipped_text or "\n".join(
            str(item) for item in modeling_instructions.get("warnings", []) or []
        )
        return [
            {
                "id": "user_modeling_hint",
                "kind": "text",
                "text": (
                    "建模指令显示主体实体无法生成。请补充主体厚度、拉伸深度或可接受的建模假设，"
                    "系统会基于当前图纸上下文重新生成模型。"
                ),
                "reason": reason,
                "required": True,
                "example": "例如：主体厚度按49处理；或主体厚度未标注，先按10生成主体供检查。",
            }
        ]

    @staticmethod
    def _build_pre_modeling_clarification_context(
        intelligent_analysis_result: Dict[str, Any],
        *,
        geometry_data: Dict[str, Any],
        extrude_height: float,
        file_path: str,
    ) -> Dict[str, Any]:
        modeling_instructions = intelligent_analysis_result.get("modeling_instructions", {}) or {}
        return {
            "geometry_data": geometry_data,
            "view_analysis": intelligent_analysis_result.get("view_analysis", {}),
            "dimension_data": intelligent_analysis_result.get("dimension_extraction", {}),
            "local_relationships": intelligent_analysis_result.get("local_relationships"),
            "extrude_height": extrude_height,
            "file_path": file_path,
            "reconstruction_context": intelligent_analysis_result.get("reconstruction_context", {}),
            "clarification_stage": "semantic_policy",
            "pre_modeling_recovery": True,
            "previous_modeling_instructions": modeling_instructions,
            "skipped_features": list(modeling_instructions.get("skipped_features", []) or []),
            "partial_completion_reason": modeling_instructions.get("partial_completion_reason"),
        }

    def _execute_intelligent_modeling_path(
        self,
        *,
        result: CADProcessResult,
        intelligent_analysis_result: Dict[str, Any],
        geometry_data: Dict[str, Any],
        output_structure: Dict[str, Path],
        extrude_height: float,
        missing_script_message: str,
        script_failure_prefix: str,
        completion_message: str,
    ) -> CADProcessResult:
        return self._get_modeling_executor().execute(
            result=result,
            intelligent_analysis_result=intelligent_analysis_result,
            geometry_data=geometry_data,
            output_structure=output_structure,
            extrude_height=extrude_height,
            missing_script_message=missing_script_message,
            script_failure_prefix=script_failure_prefix,
            completion_message=completion_message,
        )

    def continue_with_clarification(
        self,
        result: CADProcessResult,
        clarification_answers: Dict[str, Any] | ClarificationResponse,
        output_structure: Dict[str, Path],
    ) -> CADProcessResult:
        """在用户补充答案后，从语义裁决阶段继续智能建模。"""
        if not result.clarification_context:
            result.mark_failed("缺少澄清上下文，无法继续局部恢复")
            return result

        try:
            logger.info("收到用户澄清，继续智能建模")
            clarification_response = ClarificationResponse.from_input(
                clarification_answers,
                source_stage=result.clarification_context.get(
                    "clarification_stage",
                    "semantic_policy",
                ),
            )
            api_key = self.config.get("api", {}).get("deepseek", {}).get("api_key", "")
            from src.intelligent_analyzer import IntelligentEngineeringAnalyzer

            analyzer = IntelligentEngineeringAnalyzer(
                api_key,
                self.config.get("api", {}).get("deepseek", {}),
                enable_cache=False,
            )
            resumed_analysis = analyzer.continue_with_clarification(
                result.clarification_context,
                clarification_response,
            )
            result.intelligent_analysis = resumed_analysis

            clarification_questions = self._collect_clarification_questions(resumed_analysis)
            if clarification_questions:
                result.mark_needs_clarification(
                    clarification_questions,
                    resumed_analysis.get("clarification_context", result.clarification_context),
                )
                logger.info("用户澄清后仍存在未决问题，继续等待输入")
                return result

            output_dir = output_structure.get("directory", Path(".") / "output")
            base_name = Path(
                result.clarification_context.get("file_path", result.input_file)
            ).stem
            analyzer.save_results(resumed_analysis, str(output_dir), base_name)

            modeling_instructions = resumed_analysis.get("modeling_instructions", {}) or {}
            if self._needs_pre_modeling_clarification(modeling_instructions):
                result.mark_needs_clarification(
                    self._build_pre_modeling_clarification_questions(modeling_instructions),
                    self._build_pre_modeling_clarification_context(
                        resumed_analysis,
                        geometry_data=result.clarification_context["geometry_data"],
                        extrude_height=result.clarification_context["extrude_height"],
                        file_path=result.clarification_context.get(
                            "file_path",
                            result.input_file,
                        ),
                    ),
                )
                logger.info("用户澄清后建模指令仍表明主体实体无法生成，继续等待用户澄清")
                return result

            self._notify_progress_stage("modeling", "建模中")
            modeled_result = self._execute_intelligent_modeling_path(
                result=result,
                intelligent_analysis_result=resumed_analysis,
                geometry_data=result.clarification_context["geometry_data"],
                output_structure=output_structure,
                extrude_height=result.clarification_context["extrude_height"],
                missing_script_message="用户澄清后仍未获得可执行的 AI FreeCAD 建模脚本",
                script_failure_prefix="用户澄清后的 AI 脚本执行失败",
                completion_message="用户澄清后的智能建模已完成",
            )
            self._attach_partial_modeling_clarification(
                modeled_result,
                resumed_analysis,
                geometry_data=result.clarification_context["geometry_data"],
                extrude_height=result.clarification_context["extrude_height"],
                file_path=result.clarification_context.get("file_path", result.input_file),
            )
            return modeled_result
        except StageConfirmationStopped as stopped:
            result.mark_stopped_by_user(
                str(stopped),
                action=getattr(stopped.result, "action", None),
                stage=getattr(stopped.result, "stage", None),
            )
            logger.info(
                "%s | action=%s | stage=%s",
                result.error_message,
                result.stage_stop_action,
                result.stage_stop_stage,
            )
            return result
        except Exception as error:
            result.mark_failed(f"用户澄清后的局部恢复失败: {error}")
            logger.error(traceback.format_exc())
            return result

    def _attach_partial_modeling_clarification(
        self,
        result: CADProcessResult,
        intelligent_analysis_result: Optional[Dict[str, Any]],
        *,
        geometry_data: Dict[str, Any],
        extrude_height: float,
        file_path: str,
    ) -> None:
        if result.status != PipelineStatus.PARTIAL_COMPLETED:
            return
        if not result.skipped_features:
            return
        if result.clarification_questions and result.clarification_context:
            return

        skipped_text = self._format_skipped_features_for_question(result.skipped_features)
        result.clarification_questions = [
            {
                "id": "user_modeling_hint",
                "kind": "text",
                "text": (
                    "主体模型已生成，但以下细节被跳过。请补充这些细节的建模要求，"
                    "系统会基于当前图纸上下文重新生成模型。"
                ),
                "reason": skipped_text,
                "required": True,
                "example": "例如：R15 是螺栓头部承面，可用绕轴回转圆弧面表达；其余圆角可以跳过。",
            }
        ]
        result.clarification_context = self._build_partial_modeling_clarification_context(
            intelligent_analysis_result or {},
            geometry_data=geometry_data,
            extrude_height=extrude_height,
            file_path=file_path,
            result=result,
        )

    @staticmethod
    def _format_skipped_features_for_question(skipped_features: list[Dict[str, Any]]) -> str:
        lines = []
        for index, feature in enumerate(skipped_features[:6], start=1):
            name = str(feature.get("name") or feature.get("kind") or f"细节{index}")
            reason = str(feature.get("reason") or feature.get("risk") or "未说明原因")
            lines.append(f"{index}. {name}: {reason}")
        if len(skipped_features) > 6:
            lines.append(f"... 另有 {len(skipped_features) - 6} 项细节")
        return "\n".join(lines)

    @staticmethod
    def _build_partial_modeling_clarification_context(
        intelligent_analysis_result: Dict[str, Any],
        *,
        geometry_data: Dict[str, Any],
        extrude_height: float,
        file_path: str,
        result: CADProcessResult,
    ) -> Dict[str, Any]:
        existing_context = intelligent_analysis_result.get("clarification_context")
        if existing_context:
            context = dict(existing_context)
        else:
            context = {
                "geometry_data": geometry_data,
                "view_analysis": intelligent_analysis_result.get("view_analysis", {}),
                "dimension_data": intelligent_analysis_result.get("dimension_extraction", {}),
                "local_relationships": intelligent_analysis_result.get("local_relationships"),
                "extrude_height": extrude_height,
                "file_path": file_path,
                "reconstruction_context": intelligent_analysis_result.get("reconstruction_context", {}),
            }
        context.update({
            "clarification_stage": "semantic_policy",
            "partial_modeling_recovery": True,
            "previous_modeling_instructions": intelligent_analysis_result.get("modeling_instructions", {}),
            "previous_output_paths": dict(result.output_paths),
            "skipped_features": list(result.skipped_features),
            "partial_completion_reason": result.partial_completion_reason,
        })
        return context

    def process_from_geometry_data(self, geometry_data: Dict,
                                   output_structure: Dict[str, Path],
                                   extrude_height: float = 10.0,
                                   relationships: Optional[Dict] = None) -> CADProcessResult:
        """
        直接从几何数据开始处理（跳过CAD解析阶段）

        参数:
            geometry_data: 几何数据字典
            output_structure: 输出结构
            extrude_height: 拉伸高度
            relationships: 关系数据

        返回:
            处理结果
        """
        result = CADProcessResult(
            success=False,
            input_file="direct_from_data",
            mode="basic",
            modeling_path="planar_extrude",
        )
        result.geometry_data = geometry_data
        result.entity_count = len(geometry_data.get('entities', []))

        try:
            modeler_config = {}
            if "freecad" in self.config:
                modeler_config.update(self.config.get("freecad", {}))
            modeler_config["default_extrude_height"] = extrude_height

            modeler = self._get_modeler()(modeler_config)
            modeler.generate(geometry_data, relationships or {})

            if 'model_step' in output_structure:
                modeler.export(str(output_structure['model_step']), "STEP")
                result.output_paths['model_step'] = str(output_structure['model_step'])

            modeler.close()
            result.mark_completed()

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"模型生成失败: {e}")

        return result
