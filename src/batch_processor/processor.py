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

        Args:
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
            from src.model_generator import FreeCADModeler
            self._modeler = FreeCADModeler
        return self._modeler

    def process_single_file(self, file_path: str, output_structure: Dict[str, Path],
                            extrude_height: float = 10.0,
                            enable_analysis: bool = True) -> CADProcessResult:
        """
        处理单个CAD文件

        Args:
            file_path: CAD文件路径
            output_structure: 输出结构字典
            extrude_height: 拉伸高度
            enable_analysis: 是否启用AI分析

        Returns:
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

        Args:
            file_path: CAD文件路径
            output_structure: 输出结构
            extrude_height: 拉伸高度

        Returns:
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

            # 2. 智能分析
            api_key = self.config.get("api", {}).get("deepseek", {}).get("api_key", "")
            has_ai_script = False
            ai_script_content = None

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
                        ai_script_content = analysis_result['modeling_instructions'].get('freecad_script')
                        has_ai_script = bool(ai_script_content)
                        
                except Exception as e:
                    logger.warning(f"智能分析失败: {e}")
                    logger.warning(traceback.format_exc())

            # 3. 生成3D模型 - 优先使用AI脚本
            if has_ai_script and ai_script_content:
                logger.info("优先使用AI生成的脚本进行建模")
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
                        logger.warning("AI脚本执行失败，回退到通用建模器")
                        has_ai_script = False
                        
                except Exception as e:
                    logger.warning(f"执行AI脚本出错: {e}")
                    has_ai_script = False

            # 如果没有AI脚本，使用通用建模器
            if not has_ai_script:
                logger.info("使用通用建模器")
                modeler_config = {}
                if "freecad" in self.config:
                    modeler_config.update(self.config.get("freecad", {}))
                modeler_config["default_extrude_height"] = extrude_height

                modeler = self._get_modeler()(modeler_config)
                modeler.generate(geometry_data, {})

                if 'model_step' in output_structure:
                    export_path = str(output_structure['model_step'])
                    export_success = modeler.export(export_path, "STEP")
                    if export_success and Path(export_path).exists():
                        result.output_paths['model_step'] = export_path
                        logger.info(f"STEP模型已确认保存: {export_path}")
                    else:
                        logger.warning(f"STEP模型可能未正确保存: {export_path}")

                modeler.close()

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

        Args:
            geometry_data: 几何数据字典
            output_structure: 输出结构
            extrude_height: 拉伸高度
            relationships: 关系数据

        Returns:
            处理结果
        """
        result = CADProcessResult(success=False, input_file="direct_from_data")
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
            result.success = True

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"模型生成失败: {e}")

        return result
