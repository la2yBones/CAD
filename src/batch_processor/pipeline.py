#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD处理管道
提供高级接口，支持单文件和批量处理
"""

from pathlib import Path
from typing import List, Dict, Optional, Callable
import logging
from .file_manager import CADFileManager
from .processor import CADProcessor, CADProcessResult

logger = logging.getLogger(__name__)


class CADPipeline:
    """
    CAD处理管道
    提供标准化的处理接口，支持单文件和批量处理
    """

    def __init__(self, config: Optional[Dict] = None,
                 input_dir: Optional[str] = None,
                 output_dir: Optional[str] = None):
        """
        初始化处理管道

        参数:
            config: 配置字典
            input_dir: 输入目录
            output_dir: 输出目录
        """
        self.config = config or {}
        self.file_manager = CADFileManager(input_dir, output_dir)
        self.processor = CADProcessor(config)
        self._setup_logging()

    def _setup_logging(self):
        """设置日志配置"""
        log_config = self.config.get('logging', {})
        level = getattr(logging, log_config.get('level', 'INFO'))
        logging.basicConfig(level=level)

    def set_input_dir(self, input_dir: str):
        """设置输入目录"""
        self.file_manager.set_input_dir(input_dir)

    def set_output_dir(self, output_dir: str):
        """设置输出目录"""
        self.file_manager.set_output_dir(output_dir)

    def list_available_files(self, input_dir: Optional[str] = None) -> List[Dict]:
        """列出可用的CAD文件"""
        return self.file_manager.list_available_files(input_dir)

    def _prepare_file_for_processing(
        self,
        filename: str,
        *,
        mode: str,
    ) -> tuple[Optional[Path], Optional[Dict[str, Path]], Optional[CADProcessResult]]:
        """Resolve, validate, and prepare output paths for a single file."""
        # 解析文件路径
        file_path = self.file_manager.resolve_file_path(filename)
        if not file_path:
            result = CADProcessResult(success=False, input_file=filename, mode=mode)
            result.error_message = f"找不到文件: {filename}"
            logger.error(result.error_message)
            return None, None, result

        # 验证文件
        valid, error_msg = self.file_manager.validate_file(str(file_path))
        if not valid:
            result = CADProcessResult(success=False, input_file=str(file_path), mode=mode)
            result.error_message = error_msg
            logger.error(error_msg)
            return None, None, result

        # 创建输出结构
        output_structure = self.file_manager.create_output_structure(str(file_path))
        return file_path, output_structure, None

    def process_multiple_files_intelligent(
        self,
        filenames: List[str],
        extrude_height: float = 10.0,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, CADProcessResult]:
        """使用统一智能处理批量处理多个文件。"""
        results = {}
        total = len(filenames)

        for idx, filename in enumerate(filenames):
            logger.info(f"[{idx + 1}/{total}] 智能处理: {filename}")
            result = self.process_file_intelligent(filename, extrude_height)
            results[filename] = result

            if progress_callback:
                progress_callback(idx + 1, total, result)

        return results

    def process_directory_intelligent(
        self,
        input_dir: Optional[str] = None,
        extrude_height: float = 10.0,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, CADProcessResult]:
        """使用统一智能处理处理目录。"""
        files = self.list_available_files(input_dir)
        if not files:
            logger.warning("没有找到可处理的CAD文件")
            return {}

        filenames = [f["name"] for f in files]
        if input_dir:
            self.set_input_dir(input_dir)

        return self.process_multiple_files_intelligent(
            filenames,
            extrude_height,
            progress_callback,
        )

    def get_summary(self, results: Dict[str, CADProcessResult]) -> Dict:
        """
        生成处理摘要

        参数:
            results: 处理结果字典

        返回:
            摘要信息字典
        """
        total = len(results)
        success_count = sum(1 for r in results.values() if r.success)
        partial_count = sum(
            1 for r in results.values()
            if getattr(getattr(r, "status", None), "value", "") == "partial_completed"
        )
        stopped_count = sum(
            1 for r in results.values()
            if getattr(getattr(r, "status", None), "value", "") == "stopped_by_user"
        )
        stage_action_count = sum(
            1 for r in results.values()
            if getattr(getattr(r, "status", None), "value", "") == "stage_action_requested"
        )
        clarification_count = sum(
            1 for r in results.values()
            if getattr(getattr(r, "status", None), "value", "") == "needs_clarification"
        )
        fail_count = (
            total
            - success_count
            - stopped_count
            - stage_action_count
            - clarification_count
        )
        total_entities = sum(r.entity_count for r in results.values())

        return {
            'total': total,
            'success': success_count,
            'partial_completed': partial_count,
            'failed': fail_count,
            'stopped_by_user': stopped_count,
            'stage_action_requested': stage_action_count,
            'needs_clarification': clarification_count,
            'total_entities': total_entities,
            'details': {name: result.to_dict() for name, result in results.items()}
        }

    def process_file_intelligent(self, filename: str, extrude_height: float = 10.0) -> CADProcessResult:
        """
        使用统一智能处理处理单个文件。

        参数:
            filename: 文件名或路径
            extrude_height: 拉伸高度

        返回:
            处理结果
        """
        file_path, output_structure, error_result = self._prepare_file_for_processing(
            filename,
            mode="intelligent",
        )
        if error_result:
            return error_result
        assert file_path is not None and output_structure is not None
        return self.processor.process_with_intelligent_analysis(
            str(file_path),
            output_structure,
            extrude_height
        )

    def continue_file_with_clarification(
        self,
        result: CADProcessResult,
        clarification_answers: Dict[str, object],
    ) -> CADProcessResult:
        """继续一个已进入 needs_clarification 的智能处理任务。"""
        output_structure = self.file_manager.create_output_structure(result.input_file)
        return self.processor.continue_with_clarification(
            result,
            clarification_answers,
            output_structure,
        )

    def print_summary(self, results: Dict[str, CADProcessResult]):
        """打印处理摘要"""
        summary = self.get_summary(results)
        print("\n" + "=" * 60)
        print("处理摘要")
        print("=" * 60)
        print(f"总数: {summary['total']}")
        print(f"成功: {summary['success']}")
        print(f"失败: {summary['failed']}")
        print(f"总实体数: {summary['total_entities']}")
        print("\n详细信息:")
        for name, detail in summary['details'].items():
            status = "✓ 成功" if detail['success'] else "✗ 失败"
            extra_info = ""
            if detail.get('has_intelligent_analysis'):
                extra_info = " [智能分析]"
            print(f"  {name}: {status}, 实体数: {detail['entity_count']}{extra_info}")
            if not detail['success'] and detail.get('error_message'):
                print(f"    错误: {detail['error_message']}")
        print("=" * 60)
