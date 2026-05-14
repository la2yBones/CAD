#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例2: 批量处理整个文件夹中的图纸
演示如何批量处理多个CAD图纸
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging
from src.batch_processor import CADPipeline


def progress_callback(current: int, total: int, result):
    """进度回调函数"""
    print(f"进度: [{current}/{total}] {'✓' if result.success else '✗'} {Path(result.input_file).name}")


def main():
    # ==========================================
    # 配置区域
    # ==========================================
    INPUT_DIR = "examples/cad_files"   # 图纸文件夹
    OUTPUT_DIR = "examples/output"     # 输出文件夹
    EXTRUDE_HEIGHT = 10.0              # 拉伸高度
    ENABLE_ANALYSIS = False            # 是否启用AI分析
    # ==========================================

    logger = setup_logging(level="INFO")
    config = load_config()

    logger.info("=" * 60)
    logger.info("CAD图纸批量处理 - 多文件示例")
    logger.info("=" * 60)

    # 创建处理管道
    pipeline = CADPipeline(
        config=config,
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR
    )

    # 列出可用文件
    files = pipeline.list_available_files()
    if not files:
        logger.warning("未找到CAD文件!")
        return

    logger.info(f"找到 {len(files)} 个CAD文件:")
    for f in files:
        logger.info(f"  - {f['name']}")

    # 批量处理
    logger.info("\n开始批量处理...")
    results = pipeline.process_directory(
        input_dir=INPUT_DIR,
        extrude_height=EXTRUDE_HEIGHT,
        enable_analysis=ENABLE_ANALYSIS,
        progress_callback=progress_callback
    )

    # 打印摘要
    pipeline.print_summary(results)


if __name__ == "__main__":
    main()
