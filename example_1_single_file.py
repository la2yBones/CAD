#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例1: 快速处理单个CAD图纸
演示如何使用batch_processor模块处理单个图纸
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging
from src.batch_processor import BatchPipeline, FileManager


def main():
    CAD_FILENAME = "sample.dxf"
    EXTRUDE_HEIGHT = 10.0
    INPUT_DIR = "examples/cad_files"
    OUTPUT_DIR = "examples/output"

    logger = setup_logging(level="INFO")
    config = load_config()

    logger.info("=" * 60)
    logger.info("CAD图纸批量处理 - 单文件示例")
    logger.info("=" * 60)

    pipeline = BatchPipeline(config)

    logger.info("\n可用的CAD文件:")
    scan_result = FileManager.scan_files(INPUT_DIR)
    if scan_result.is_err():
        logger.warning(f"扫描失败: {scan_result.error}")
        return
    for f in scan_result.value:
        logger.info(f"  - {f.name}")

    file_path = str(Path(INPUT_DIR) / CAD_FILENAME)
    logger.info(f"\n开始处理: {CAD_FILENAME}")
    result = pipeline.process_file(
        file_path,
        output_dir=OUTPUT_DIR,
        extrude_height=EXTRUDE_HEIGHT
    )

    if result.success:
        logger.info("\n✓ 处理成功!")
        logger.info(f"  处理时间: {result.processing_time_seconds:.1f}秒")
        if result.model_result:
            logger.info(f"  输出目录: {result.model_result.get('output_dir', '')}")
    else:
        logger.error(f"\n✗ 处理失败: {result.error_message}")

    logger.info("\n完成!")


if __name__ == "__main__":
    main()
