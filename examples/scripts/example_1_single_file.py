#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例1: 快速处理单个CAD图纸
演示如何使用batch_processor模块处理单个图纸
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging
from src.batch_processor import CADPipeline


def main():
    # ==========================================
    # 配置区域 - 修改这里的参数即可
    # ==========================================
    CAD_FILENAME = "sample.dxf"  # 你的图纸文件名
    EXTRUDE_HEIGHT = 10.0        # 拉伸高度(mm)
    INPUT_DIR = "examples/cad_files"  # 图纸所在目录
    OUTPUT_DIR = "examples/output"    # 输出目录
    ENABLE_ANALYSIS = False       # 是否启用AI分析
    # ==========================================

    logger = setup_logging(level="INFO")
    config = load_config()

    logger.info("=" * 60)
    logger.info("CAD图纸批量处理 - 单文件示例")
    logger.info("=" * 60)

    # 创建处理管道
    pipeline = CADPipeline(
        config=config,
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR
    )

    # 先列出可用的文件
    logger.info("\n可用的CAD文件:")
    files = pipeline.list_available_files()
    for f in files:
        logger.info(f"  - {f['name']}")

    # 处理指定文件
    logger.info(f"\n开始处理: {CAD_FILENAME}")
    result = pipeline.process_file(
        CAD_FILENAME,
        extrude_height=EXTRUDE_HEIGHT,
        enable_analysis=ENABLE_ANALYSIS
    )

    # 显示结果
    if result.success:
        logger.info("\n✓ 处理成功!")
        logger.info(f"  提取实体数: {result.entity_count}")
        logger.info(f"  输出文件:")
        for key, path in result.output_paths.items():
            logger.info(f"    {key}: {path}")
    else:
        logger.error(f"\n✗ 处理失败: {result.error_message}")

    logger.info("\n完成!")


if __name__ == "__main__":
    main()
