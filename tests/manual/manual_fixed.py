#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的智能分析流程
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.batch_processor import CADProcessor, CADFileManager
import logging


def test_fixed_flow():
    """测试修复后的流程"""
    logger = setup_logging(level="INFO")
    config = load_config()

    # 找到图纸
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

    # 准备输出
    output_dir = project_root / "examples/output/test_fixed_flow"
    file_manager = CADFileManager(str(output_dir))
    output_structure = file_manager.create_output_structure(str(cad_file))

    # 创建处理器
    processor = CADProcessor(config)

    # 处理
    logger.info("\n开始处理...")
    result = processor.process_with_intelligent_analysis(
        str(cad_file),
        output_structure,
        extrude_height=10.0
    )

    # 输出结果
    logger.info("\n" + "=" * 60)
    if result.success:
        logger.info("✓ 处理成功！")
        for key, path in result.output_paths.items():
            p = Path(path)
            if p.exists():
                size = p.stat().st_size
                logger.info(f"  {key}: {path} ({size} bytes)")
            else:
                logger.warning(f"  {key}: {path} (不存在)")
    else:
        logger.error("✗ 处理失败")
        if result.error_message:
            logger.error(f"  错误: {result.error_message}")
    logger.info("=" * 60)


if __name__ == "__main__":
    test_fixed_flow()
