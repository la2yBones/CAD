#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的智能分析流程
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.batch_processor import CADProcessor, FileManager
import logging


def test_fixed_flow():
    logger = setup_logging(level="INFO")
    config = load_config()

    cad_dir = project_root / "examples/cad_files"
    cad_file = None
    for name in ["底座二视图.dxf", "底座二视图.DXF"]:
        f = cad_dir / name
        if f.exists():
            cad_file = f
            break

    if not cad_file:
        logger.error(f"找不到图纸，请检查 {cad_dir}")
        return

    logger.info("=" * 60)
    logger.info(f"测试: {cad_file.name}")
    logger.info("=" * 60)

    api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
    if not api_key or api_key == "your-deepseek-api-key-here":
        logger.error("未配置有效的 API 密钥，请在 config/config.yaml 中设置")
        return

    output_dir = str(project_root / "examples/output/test_fixed_flow")
    output_result = FileManager.build_output_structure(str(cad_file), output_dir)
    if output_result.is_err():
        logger.error(f"构建输出结构失败: {output_result.error}")
        return

    processor = CADProcessor(config)

    logger.info("\n开始处理...")
    result = processor.process_with_intelligent_analysis(
        str(cad_file),
        api_key,
        extrude_height=10.0,
        output_dir=output_dir
    )

    logger.info("\n" + "=" * 60)
    if result.success:
        logger.info("✓ 处理成功！")
        if result.model_result:
            logger.info(f"  输出目录: {result.model_result.get('output_dir', '')}")
    else:
        logger.error("✗ 处理失败")
        if result.error_message:
            logger.error(f"  错误: {result.error_message}")
    logger.info("=" * 60)


if __name__ == "__main__":
    test_fixed_flow()
