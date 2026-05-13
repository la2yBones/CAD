"""
批量处理器

对多个 CAD 文件依次执行 解析 → 分析 → 生成 的完整流水线，
支持并发处理和结果汇总。
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cad_parser import CADParser
from ..geometry_analyzer import GeometryAnalyzer
from ..model_generator import ModelGenerator
from ..utils.config import load_config
from ..utils.result import Result
from .file_manager import FileManager

logger = logging.getLogger(__name__)


@dataclass
class CADProcessResult:
    """单个 CAD 文件处理结果。"""
    file_path: str
    success: bool = False
    error_message: str = ""
    parse_result: Optional[Dict[str, Any]] = None
    geometry_analysis: Optional[Dict[str, Any]] = None
    intelligent_analysis: Optional[Dict[str, Any]] = None
    model_result: Optional[Dict[str, Any]] = None
    processing_time_seconds: float = 0.0
    mode: str = "basic"


class CADProcessor:
    """CAD 批量处理器，管理完整的 解析→分析→生成 流水线。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or load_config()
        self._parser = CADParser(self._config)
        self._generator = ModelGenerator(self._config)

    def process_single_file(
        self,
        file_path: str,
        extrude_height: float = 10.0,
        output_dir: Optional[str] = None,
    ) -> CADProcessResult:
        """
        基础模式：处理单个 CAD 文件。

        Args:
            file_path: CAD 文件路径
            extrude_height: 默认拉伸高度（毫米）
            output_dir: 输出目录

        Returns:
            CADProcessResult: 包含处理状态和产物的结果对象
        """
        start_time = time.time()
        result = CADProcessResult(file_path=str(file_path))

        try:
            parse_result = self._parser.parse(file_path)
            if parse_result.is_err():
                result.error_message = parse_result.error
                return result
            result.parse_result = parse_result.value

            geometry_analyzer = GeometryAnalyzer()
            geo_result = geometry_analyzer.analyze(result.parse_result)
            if geo_result.is_err():
                result.error_message = geo_result.error
                return result
            result.geometry_analysis = geo_result.value

            gen_result = self._generator.generate_basic_model(
                result.parse_result, extrude_height, output_dir
            )
            if gen_result.is_err():
                result.error_message = gen_result.error
                return result
            result.model_result = gen_result.value
            result.success = True
        except Exception as e:
            result.error_message = f"处理异常: {e}"
            logger.exception(f"处理文件失败: {file_path}")

        result.processing_time_seconds = round(time.time() - start_time, 2)
        return result

    def process_with_intelligent_analysis(
        self,
        file_path: str,
        api_key: str,
        extrude_height: float = 10.0,
        output_dir: Optional[str] = None,
    ) -> CADProcessResult:
        """
        智能模式：使用 AI 驱动的分析处理单个 CAD 文件。

        Args:
            file_path: CAD 文件路径
            api_key: AI 服务 API 密钥
            extrude_height: 默认拉伸高度（毫米）
            output_dir: 输出目录

        Returns:
            CADProcessResult: 包含处理状态和产物的结果对象
        """
        start_time = time.time()
        result = CADProcessResult(file_path=str(file_path), mode="intelligent")

        try:
            parse_result = self._parser.parse(file_path)
            if parse_result.is_err():
                result.error_message = parse_result.error
                return result
            result.parse_result = parse_result.value

            geometry_analyzer = GeometryAnalyzer()
            geo_result = geometry_analyzer.analyze(result.parse_result)
            if geo_result.is_err():
                result.error_message = geo_result.error
                return result
            result.geometry_analysis = geo_result.value

            if not api_key or api_key == "your-deepseek-api-key-here":
                result.error_message = "未配置有效的 API 密钥"
                return result

            from ..intelligent_analyzer import IntelligentEngineeringAnalyzer
            analyzer = IntelligentEngineeringAnalyzer(
                api_key,
                self._config.get("api", {}).get("deepseek", {}),
                enable_cache=True,
                cache_dir=self._config.get("cache", {}).get("cache_dir"),
                cache_ttl=self._config.get("cache_ttl", 3600 * 24 * 7),
            )

            analysis_result = analyzer.analyze_full(
                result.parse_result,
                extrude_height,
                file_path=str(file_path),
            )
            if analysis_result.is_err():
                result.error_message = analysis_result.error
                return result
            result.intelligent_analysis = analysis_result.value

            logger.info("智能分析完成")

            gen_result = self._generator.generate_intelligent_model(
                result.parse_result,
                analysis_result.value,
                output_dir,
            )
            if gen_result.is_err():
                result.error_message = gen_result.error
                return result
            result.model_result = gen_result.value
            result.success = True
        except Exception as e:
            result.error_message = f"智能处理异常: {e}"
            logger.exception(f"智能处理文件失败: {file_path}")

        result.processing_time_seconds = round(time.time() - start_time, 2)
        return result

    def process_batch(
        self,
        file_paths: List[str],
        extrude_height: float = 10.0,
        output_dir: Optional[str] = None,
        max_workers: int = 1,
    ) -> List[CADProcessResult]:
        """
        批量处理多个 CAD 文件（基础模式）。

        Args:
            file_paths: CAD 文件路径列表
            extrude_height: 默认拉伸高度（毫米）
            output_dir: 输出目录
            max_workers: 最大并发数

        Returns:
            List[CADProcessResult]: 每个文件的处理结果列表
        """
        results: List[CADProcessResult] = []
        for file_path in file_paths:
            r = self.process_single_file(file_path, extrude_height, output_dir)
            results.append(r)
        return results

    def generate_summary(self, results: List[CADProcessResult]) -> Dict[str, Any]:
        """生成批量处理的汇总统计。"""
        total = len(results)
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        return {
            "total_files": total,
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": f"{(len(successful) / total * 100):.1f}%" if total > 0 else "0%",
            "total_time_seconds": round(sum(r.processing_time_seconds for r in results), 2),
            "failed_files": [
                {"file_path": r.file_path, "error": r.error_message}
                for r in failed
            ],
            "successful_files": [r.file_path for r in successful],
            "mode_distribution": {
                "basic": len([r for r in successful if r.mode == "basic"]),
                "intelligent": len([r for r in successful if r.mode == "intelligent"]),
            },
        }

    def get_parser(self) -> CADParser:
        """获取 CAD 解析器实例。"""
        return self._parser

    def get_generator(self) -> ModelGenerator:
        """获取模型生成器实例。"""
        return self._generator
