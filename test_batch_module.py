#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量处理模块测试脚本
验证各个组件功能是否正常
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
import logging

logger = setup_logging(level="INFO")


def test_file_manager():
    logger.info("\n" + "="*50)
    logger.info("测试1: 文件管理器")
    logger.info("="*50)

    from src.batch_processor import FileManager

    result = FileManager.scan_files("examples/cad_files")
    if result.is_err():
        logger.error(f"扫描失败: {result.error}")
        return False

    files = result.value
    logger.info(f"找到 {len(files)} 个CAD文件")
    for f in files[:3]:
        logger.info(f"  - {f.name}")

    if files:
        validate_result = FileManager.validate_file(str(files[0]))
        if validate_result.is_ok():
            logger.info(f"文件验证通过: {validate_result.value.name}")
        else:
            logger.warning(f"文件验证失败: {validate_result.error}")

    if files:
        build_result = FileManager.build_output_structure(
            str(files[0]), "examples/output/test"
        )
        if build_result.is_ok():
            logger.info(f"输出结构:")
            for key, path in build_result.value.items():
                logger.info(f"  {key}: {path}")
        else:
            logger.error(f"构建输出结构失败: {build_result.error}")

    logger.info("✓ 文件管理器测试完成")
    return True


def test_processor():
    logger.info("\n" + "="*50)
    logger.info("测试2: 处理器接口")
    logger.info("="*50)

    from src.batch_processor import CADProcessResult

    result = CADProcessResult(file_path="test.dxf")
    result.success = True
    result.model_result = {"output_dir": "test_output", "model_path": "test.step"}

    logger.info(f"结果对象: success={result.success}")
    logger.info(f"file_path: {result.file_path}")
    logger.info(f"model_result: {result.model_result}")

    logger.info("✓ 处理器接口测试完成")
    return True


def test_pipeline():
    logger.info("\n" + "="*50)
    logger.info("测试3: 处理管道")
    logger.info("="*50)

    from src.batch_processor import BatchPipeline
    config = load_config()

    pipeline = BatchPipeline(config)

    from src.batch_processor import FileManager
    scan_result = FileManager.scan_files("examples/cad_files")
    if scan_result.is_err():
        logger.warning(f"扫描目录失败: {scan_result.error}")
    else:
        logger.info(f"管道找到 {len(scan_result.value)} 个文件")

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
