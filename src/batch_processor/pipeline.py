"""
批量处理流水线

提供从文件发现到模型生成的端到端接口。
支持 CLI 入口和编程式调用。
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.config import load_config
from ..utils.result import Result
from .file_manager import FileManager
from .processor import CADProcessor, CADProcessResult

logger = logging.getLogger(__name__)


class BatchPipeline:
    """端到端批量处理流水线。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or load_config()
        self._file_manager = FileManager()
        self._processor = CADProcessor(self._config)

    def process_directory(
        self,
        input_dir: str,
        output_dir: Optional[str] = None,
        extrude_height: float = 10.0,
    ) -> Tuple[List[CADProcessResult], Dict[str, Any]]:
        """
        基础模式：批量处理目录中所有 CAD 文件。

        Args:
            input_dir: 输入目录
            output_dir: 输出目录
            extrude_height: 默认拉伸高度（毫米）

        Returns:
            (处理结果列表, 汇总统计)
        """
        output_dir = output_dir or self._config.get("generation", {}).get("output_dir", "output")
        logger.info(f"开始批量处理: {input_dir} → {output_dir}")

        scan_result = FileManager.scan_files(input_dir)
        if scan_result.is_err():
            logger.error(scan_result.error)
            return [], {"error": scan_result.error}

        files = scan_result.value
        logger.info(f"发现 {len(files)} 个文件待处理")

        results = []
        for i, file_path in enumerate(files):
            logger.info(f"[{i + 1}/{len(files)}] 处理: {file_path}")
            result = self._processor.process_single_file(
                str(file_path), extrude_height, output_dir
            )
            results.append(result)

        summary = self._processor.generate_summary(results)
        logger.info(
            f"批量处理完成: {summary['successful']}/{summary['total_files']} 成功 "
            f"({summary['success_rate']})"
        )
        return results, summary

    def process_file(
        self,
        file_path: str,
        output_dir: Optional[str] = None,
        extrude_height: float = 10.0,
    ) -> CADProcessResult:
        """
        基础模式：处理单个 CAD 文件。

        Args:
            file_path: CAD 文件路径
            output_dir: 输出目录
            extrude_height: 默认拉伸高度（毫米）

        Returns:
            CADProcessResult: 处理结果
        """
        validate_result = FileManager.validate_file(file_path)
        if validate_result.is_err():
            r = CADProcessResult(file_path=file_path)
            r.error_message = validate_result.error
            return r

        output_dir = output_dir or self._config.get("generation", {}).get("output_dir", "output")
        return self._processor.process_single_file(file_path, extrude_height, output_dir)

    def process_file_intelligent(
        self,
        file_path: str,
        api_key: str,
        output_dir: Optional[str] = None,
        extrude_height: float = 10.0,
    ) -> CADProcessResult:
        """
        智能模式：使用 AI 分析处理单个 CAD 文件。

        Args:
            file_path: CAD 文件路径
            api_key: AI 服务 API 密钥
            output_dir: 输出目录
            extrude_height: 默认拉伸高度（毫米）

        Returns:
            CADProcessResult: 处理结果
        """
        validate_result = FileManager.validate_file(file_path)
        if validate_result.is_err():
            r = CADProcessResult(file_path=file_path, mode="intelligent")
            r.error_message = validate_result.error
            return r

        output_dir = output_dir or self._config.get("generation", {}).get("output_dir", "output")
        return self._processor.process_with_intelligent_analysis(
            file_path, api_key, extrude_height, output_dir
        )

    @classmethod
    def run_complete_pipeline(
        cls,
        input_path: str,
        output_dir: str = "output",
        extrude_height: float = 10.0,
        mode: str = "basic",
        api_key: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> Result[Dict[str, Any]]:
        """
        便捷入口：执行完整的 解析→分析→生成 流水线。

        Args:
            input_path: 输入文件或目录路径
            output_dir: 输出目录
            extrude_height: 默认拉伸高度（毫米）
            mode: 'basic' 或 'intelligent'
            api_key: 智能模式所需的 AI API 密钥
            config_path: 配置文件路径

        Returns:
            Result[Dict]: Ok 时包含完整的流水线结果
        """
        start_time = time.time()
        config = load_config(config_path)

        if mode == "intelligent" and (not api_key or api_key == "your-deepseek-api-key-here"):
            return Result.Err("智能模式需要有效的 API 密钥")

        in_path = Path(input_path)

        if not in_path.exists():
            return Result.Err(f"输入路径不存在: {input_path}")

        pipeline = cls(config)

        if in_path.is_dir():
            results, summary = pipeline.process_directory(
                str(in_path), output_dir, extrude_height
            )
            if not results and "error" in summary:
                return Result.Err(summary["error"])
        else:
            validate_result = FileManager.validate_file(input_path)
            if validate_result.is_err():
                return Result.Err(validate_result.error)

            if mode == "intelligent":
                result = pipeline.process_file_intelligent(
                    input_path, api_key or "", output_dir, extrude_height
                )
            else:
                result = pipeline.process_file(input_path, output_dir, extrude_height)
            results = [result]
            summary = pipeline._processor.generate_summary(results)

        elapsed = round(time.time() - start_time, 2)

        return Result.Ok({
            "success": summary.get("failed", 0) == 0,
            "results": [
                {
                    "file_path": r.file_path,
                    "success": r.success,
                    "error": r.error_message,
                    "model": r.model_result.get("model_path") if r.model_result else None,
                    "time_seconds": r.processing_time_seconds,
                }
                for r in results
            ],
            "summary": summary,
            "total_time_seconds": elapsed,
        })
