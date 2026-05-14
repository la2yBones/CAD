#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量处理模块测试脚本
验证各个组件功能是否正常
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
import logging

logger = setup_logging(level="INFO")


def test_file_manager():
    """测试文件管理器"""
    logger.info("\n" + "="*50)
    logger.info("测试1: 文件管理器")
    logger.info("="*50)

    from src.batch_processor import CADFileManager

    fm = CADFileManager(
        input_dir="examples/cad_files",
        output_dir="examples/output/test"
    )

    # 测试列出文件
    files = fm.list_available_files()
    logger.info(f"找到 {len(files)} 个CAD文件")
    for f in files[:3]:
        logger.info(f"  - {f['name']}")

    # 测试文件验证
    if files:
        test_file = files[0]['path']
        valid, msg = fm.validate_file(test_file)
        logger.info(f"文件验证: {valid} - {msg}")

    # 测试输出路径生成
    if files:
        structure = fm.create_output_structure(files[0]['path'])
        logger.info(f"输出结构:")
        for key, path in structure.items():
            logger.info(f"  {key}: {path}")

    logger.info("✓ 文件管理器测试完成")
    return True


def test_processor():
    """测试处理器（模拟）"""
    logger.info("\n" + "="*50)
    logger.info("测试2: 处理器接口")
    logger.info("="*50)

    from src.batch_processor.processor import CADProcessResult

    # 测试结果对象
    result = CADProcessResult(success=True, input_file="test.dxf")
    result.entity_count = 10
    result.output_paths['model_step'] = "test.step"

    logger.info(f"结果对象: success={result.success}")
    logger.info(f"输出字典: {result.to_dict()}")

    logger.info("✓ 处理器接口测试完成")
    return True


def test_pipeline():
    """测试处理管道"""
    logger.info("\n" + "="*50)
    logger.info("测试3: 处理管道")
    logger.info("="*50)

    from src.batch_processor import CADPipeline
    config = load_config()

    pipeline = CADPipeline(
        config=config,
        input_dir="examples/cad_files",
        output_dir="examples/output/test"
    )

    # 测试列出文件
    files = pipeline.list_available_files()
    logger.info(f"管道找到 {len(files)} 个文件")

    logger.info("✓ 处理管道接口测试完成")
    return True


def main():
    logger.info("="*60)
    logger.info("CAD批量处理模块 - 功能验证")
    logger.info("="*60)

    tests = [
        test_file_manager,
        test_processor,
        test_pipeline
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"测试失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            failed += 1

    logger.info("\n" + "="*60)
    logger.info(f"测试完成: {passed} 成功, {failed} 失败")
    logger.info("="*60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
