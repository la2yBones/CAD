#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例2: 批量处理整个文件夹中的图纸
演示如何批量处理多个CAD图纸
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging
from src.batch_processor import BatchPipeline, FileManager


def progress_callback(current, total, result):
    print(f"进度: [{current}/{total}] {'✓' if result.success else '✗'} {Path(result.file_path).name}")


def main():
    INPUT_DIR = "examples/cad_files"
    OUTPUT_DIR = "examples/output"
    EXTRUDE_HEIGHT = 10.0

    logger = setup_logging(level="INFO")
    config = load_config()

    logger.info("=" * 60)
    logger.info("CAD图纸批量处理 - 多文件示例")
    logger.info("=" * 60)

    pipeline = BatchPipeline(config)

    scan_result = FileManager.scan_files(INPUT_DIR)
    if scan_result.is_err():
        logger.warning(f"扫描失败: {scan_result.error}")
        return

    files = scan_result.value
    logger.info(f"找到 {len(files)} 个CAD文件:")
    for f in files:
        logger.info(f"  - {f.name}")

    logger.info("\n开始批量处理...")
    results, summary = pipeline.process_directory(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
        extrude_height=EXTRUDE_HEIGHT
    )

    for i, r in enumerate(results):
        progress_callback(i + 1, len(results), r)

    logger.info(
        f"\n批量处理完成: {summary['successful']}/{summary['total_files']} 成功 "
        f"({summary['success_rate']})"
    )


if __name__ == "__main__":
    main()
