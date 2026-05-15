#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD处理器组件
封装单个图纸的完整处理流程
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import traceback

logger = logging.getLogger(__name__)


class CADProcessResult:
    """处理结果封装类"""

    def __init__(self, success: bool, input_file: str):
        self.success = success
        self.input_file = input_file
        self.geometry_data: Optional[Dict] = None
        self.relationships: Optional[Dict] = None
        self.intelligent_analysis: Optional[Dict] = None  # 智能分析结果
        self.output_paths: Dict[str, str] = {}
        self.error_message: Optional[str] = None
        self.entity_count: int = 0

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'input_file': self.input_file,
            'entity_count': self.entity_count,
            'output_paths': self.output_paths,
            'error_message': self.error_message,
            'has_intelligent_analysis': self.intelligent_analysis is not None
        }


class CADProcessor:
    """
    CAD图纸处理器
    封装单个图纸从解析到导出的完整流程
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化处理器

        ??:
            config: 配置字典
        """
        self.config = config or {}
        self._init_components()

    def _init_components(self):
        """初始化各个处理组件"""
        self._cad_parser = None
        self._modeler = None

    def _get_parser(self):
        """获取或创建CAD解析器"""
        if self._cad_parser is None:
            from src.cad_parser import CADParser
            self._cad_parser = CADParser
        return self._cad_parser

    def _get_modeler(self):
        """获取或创建模型生成器"""
        if self._modeler is None:
            from src.legacy.basic_modeling import FreeCADModeler
            self._modeler = FreeCADModeler
        return self._modeler

    def _analyze_view_context(
        self,
        geometry_data: Dict[str, Any],
        analysis_result: Optional[Dict[str, Any]] = None,
        source_name: Optional[str] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """判断图纸是否为多视图工程图。"""
        view_analysis = {}

        if analysis_result:
            view_analysis = analysis_result.get("view_analysis") or {}

        if not view_analysis:
            try:
                from src.intelligent_analyzer.view_analyzer import EngineeringViewAnalyzer
                view_analysis = EngineeringViewAnalyzer(self.config).analyze_views(
                    geometry_data,
                    source_name=source_name
                )
            except Exception as e:
                logger.warning(f"视图识别失败，暂按单视图处理: {e}")
                return {}, False

        is_multiview = self._is_multiview_view_analysis(view_analysis)
        if source_name and self._has_planar_name_hint(source_name):
            is_multiview = False
        elif not is_multiview and source_name:
            stem = Path(source_name).stem
            is_multiview = any(
                marker in stem
                for marker in ("二视图", "两视图", "三视图", "多视图")
            )

        return view_analysis, is_multiview

    def _has_planar_name_hint(self, source_name: str) -> bool:
        """将装配图按单张平面/剖视图处理。"""
        stem = Path(source_name).stem
        explicit_multiview = any(
            marker in stem
            for marker in ("二视图", "两视图", "三视图", "多视图")
        )
        if explicit_multiview:
            return False

        return any(marker in stem for marker in ("装配图", "总装图"))

    def _is_multiview_view_analysis(self, view_analysis: Dict[str, Any]) -> bool:
        """视图分析器找到两个或更多投影视图时返回 True。"""
        drawing_type = view_analysis.get("drawing_type")
        if drawing_type in ("assembly_drawing", "single_view", "section_view"):
            return False
        if drawing_type in ("two_view", "three_view"):
            return True

        views = view_analysis.get("views") or []
        relationships = view_analysis.get("relationships") or []

        named_views = [
            v for v in views
            if v.get("name") not in ("single", "unknown", None)
        ]
        view_names = {v.get("name") for v in named_views}

        if len(named_views) < 2:
            return False

        strong_relationships = [
            rel for rel in relationships
            if self._is_strong_projection_relationship(rel)
        ]

        if strong_relationships:
            return True

        return False

    def _is_strong_projection_relationship(self, relationship: Dict[str, Any]) -> bool:
        """仅将已校验的投影对齐关系视为多视图信号。"""
        if relationship.get("type") != "projection":
            return False

        description = str(relationship.get("description", ""))
        if "偏差较大" in description:
            return False

        strong_markers = ("长对正", "高平齐", "宽相等")
        if any(marker in description for marker in strong_markers):
            return True

        return any(
            marker in str(value)
            for key, value in relationship.items()
            if key != "description"
            for marker in strong_markers
        )

    def _build_multiview_block_message(
        self,
        view_analysis: Dict[str, Any],
        reason: Optional[str] = None
    ) -> str:
        """构建阻止平面拉伸降级时面向用户的说明。"""
        label_map = {
            "main": "主视图",
            "top": "俯视图",
            "bottom": "仰视图",
            "left": "左视图",
            "right": "右视图",
        }
        names = [
            label_map.get(v.get("name"), str(v.get("name")))
            for v in view_analysis.get("views", [])
            if v.get("name") not in ("single", "unknown", None)
        ]
        view_text = "、".join(names) if names else "多个投影视图"
        prefix = f"{reason}；" if reason else ""
        return (
            f"{prefix}检测到二视图/三视图工程图（{view_text}）。"
            "当前通用建模器只能处理单一闭合轮廓的平面拉伸，"
            "已阻止直接拉伸以避免生成错误模型。"
            "请使用智能模式并确保 AI 生成可用的 FreeCAD 多视图建模脚本，"
            "或实现多视图投影重建策略后再转换。"
        )

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

        ??:
            file_path: CAD文件路径
            output_structure: 输出结构字典
            extrude_height: 拉伸高度
            enable_analysis: 是否启用AI分析

        ??:
            处理结果对象
        """
        result = CADProcessResult(success=False, input_file=file_path)

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
                        analyzer = IntelligentEngineeringAnalyzer(
                            api_key,
                            self.config.get("api", {}).get("deepseek", {}),
                            enable_cache=True,
                            cache_dir=self.config.get('cache_dir', '.cache/analysis'),
                            cache_ttl=self.config.get('cache_ttl', 3600 * 24 * 7)
                        )
                        analysis_result = analyzer.analyze_full(
                            geometry_data,
                            extrude_height,
                            file_path=str(file_path)
                        )
                        result.intelligent_analysis = analysis_result
                        relationships = analysis_result.get("modeling_instructions", {})
                        logger.info("智能分析完成")
                    except Exception as e:
                        logger.warning(f"智能分析失败，使用纯几何建模: {e}")

            view_analysis, is_multiview = self._analyze_view_context(
                geometry_data,
                result.intelligent_analysis,
                source_name=file_path
            )
            if is_multiview:
                result.intelligent_analysis = result.intelligent_analysis or {
                    "view_analysis": view_analysis
                }
                result.error_message = self._build_multiview_block_message(
                    view_analysis,
                    reason="当前入口未执行 AI 建模脚本"
                )
                logger.warning(result.error_message)
                return result

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

            result.success = True
            logger.info(f"处理完成: {Path(file_path).name}")

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"处理失败 {file_path}: {e}")
            logger.error(traceback.format_exc())

        return result

    def process_with_intelligent_analysis(self, file_path: str, output_structure: Dict[str, Path],
                                         extrude_height: float = 10.0) -> CADProcessResult:
        """
        使用智能分析处理图纸（视图识别、尺寸提取、建模指令生成）

        ??:
            file_path: CAD文件路径
            output_structure: 输出结构
            extrude_height: 拉伸高度

        ??:
            处理结果
        """
        result = CADProcessResult(success=False, input_file=file_path)

        try:
            logger.info(f"开始智能分析处理: {Path(file_path).name}")

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

            view_analysis, is_multiview = self._analyze_view_context(
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
                    from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
                    analyzer = IntelligentEngineeringAnalyzer(
                        api_key,
                        self.config.get("api", {}).get("deepseek", {}),
                        enable_cache=True,
                        cache_dir=self.config.get('cache_dir', '.cache/analysis'),
                        cache_ttl=self.config.get('cache_ttl', 3600 * 24 * 7)
                    )
                    analysis_result = analyzer.analyze_full(
                        geometry_data, 
                        extrude_height, 
                        file_path=str(file_path)
                    )
                    result.intelligent_analysis = analysis_result

                    # 保存分析结果
                    output_dir = output_structure.get('directory', Path('.') / 'output')
                    base_name = Path(file_path).stem
                    analyzer.save_results(analysis_result, str(output_dir), base_name)
                    
                    # 显示缓存状态
                    if analysis_result.get('_cache_hit'):
                        logger.info("智能分析已从缓存加载")
                    else:
                        logger.info("智能分析完成并已缓存")
                    
                    # 获取AI生成的脚本
                    if 'modeling_instructions' in analysis_result:
                        modeling_instructions = analysis_result['modeling_instructions']
                        ai_script_content = modeling_instructions.get('freecad_script')
                        has_ai_script = bool(ai_script_content)

                    view_analysis, is_multiview = self._analyze_view_context(
                        geometry_data,
                        analysis_result,
                        source_name=file_path
                    )
                        
                except Exception as e:
                    result.error_message = f"智能分析失败，未进入建模阶段: {e}"
                    logger.warning(result.error_message)
                    logger.warning(traceback.format_exc())
                    return result
            else:
                result.error_message = "智能模式需要有效的 DeepSeek API Key，未进入建模阶段"
                logger.warning(result.error_message)
                return result

            if has_ai_script and self._is_fallback_modeling_result(modeling_instructions):
                result.error_message = (
                    "AI 未能生成可靠的建模脚本，当前结果属于基础拉伸降级方案；"
                    "智能模式不会调用通用建模器兜底"
                )
                logger.warning(result.error_message)
                return result

            if not has_ai_script or not ai_script_content:
                result.error_message = (
                    "未获得可执行的 AI FreeCAD 建模脚本；"
                    "智能模式不会调用通用建模器兜底"
                )
                logger.warning(result.error_message)
                return result

            # 3. 智能模式只执行 AI 生成的 FreeCAD 脚本，不调用通用建模器兜底
            logger.info("使用 AI 生成的 FreeCAD 脚本进行智能建模")
            try:
                from src.model_generator.ai_script_runner import AIScriptRunner
                runner = AIScriptRunner(self.config)

                step_path = None
                if 'model_step' in output_structure:
                    step_path = str(output_structure['model_step'])

                run_result = runner.run_script(ai_script_content, step_path)

                if run_result.get('success'):
                    if run_result.get('step_path'):
                        result.output_paths['model_step'] = run_result['step_path']
                    if run_result.get('fcstd_path'):
                        result.output_paths['model_fcstd'] = run_result['fcstd_path']
                    logger.info("AI脚本建模成功")
                else:
                    result.error_message = (
                        f"AI脚本执行失败，智能模式不会调用通用建模器兜底: "
                        f"{run_result.get('error', '未知错误')}"
                    )
                    logger.warning(result.error_message)
                    return result

            except Exception as e:
                result.error_message = f"执行AI脚本出错，智能模式不会调用通用建模器兜底: {e}"
                logger.warning(result.error_message)
                return result

            result.success = True
            logger.info(f"智能分析处理完成: {Path(file_path).name}")

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"智能分析处理失败: {e}")
            logger.error(traceback.format_exc())

        return result

    def process_from_geometry_data(self, geometry_data: Dict,
                                   output_structure: Dict[str, Path],
                                   extrude_height: float = 10.0,
                                   relationships: Optional[Dict] = None) -> CADProcessResult:
        """
        直接从几何数据开始处理（跳过CAD解析阶段）

        ??:
            geometry_data: 几何数据字典
            output_structure: 输出结构
            extrude_height: 拉伸高度
            relationships: 关系数据

        ??:
            处理结果
        """
        result = CADProcessResult(success=False, input_file="direct_from_data")
        result.geometry_data = geometry_data
        result.entity_count = len(geometry_data.get('entities', []))

        try:
            allow_planar_extrude = bool((relationships or {}).get("allow_planar_extrude"))
            view_analysis, is_multiview = self._analyze_view_context(geometry_data)
            if is_multiview and not allow_planar_extrude:
                result.intelligent_analysis = {"view_analysis": view_analysis}
                result.error_message = self._build_multiview_block_message(
                    view_analysis,
                    reason="直接几何数据入口未声明允许平面拉伸"
                )
                logger.warning(result.error_message)
                return result

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
            result.success = True

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"模型生成失败: {e}")

        return result
