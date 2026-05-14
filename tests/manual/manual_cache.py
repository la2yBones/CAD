#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存系统测试脚本
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.utils.cache import AnalysisCache
import logging

logger = setup_logging(level="INFO")
config = load_config()


def test_basic_operations():
    """测试基本操作"""
    logger.info("=" * 60)
    logger.info("测试1: 基本缓存操作")
    logger.info("=" * 60)

    cache = AnalysisCache(".cache/test", default_ttl=3600)

    # 清理测试数据
    cache.clear_all()

    # 测试数据
    test_file = str(project_root / "examples/cad_files/sample.dxf")
    test_data = {"view_analysis": {}, "dimension_extraction": {}, "modeling_instructions": {}}

    # 写入缓存
    cache.set(test_file, 10, test_data)
    logger.info("缓存写入完成")

    # 读取缓存
    cached = cache.get(test_file, 10)
    if cached:
        logger.info("缓存读取成功 ✓")

    # 显示统计
    stats = cache.get_stats()
    logger.info(f"缓存统计: {stats}")


def test_cache_expiry():
    """测试过期机制"""
    logger.info("\n" + "=" * 60)
    logger.info("测试2: 过期机制")
    logger.info("=" * 60)

    cache = AnalysisCache(".cache/test", default_ttl=1)
    test_file = str(project_root / "examples/cad_files/sample.dxf")

    cache.set(test_file, 10, {"test": "data"})
    logger.info("已写入短期缓存")

    import time
    time.sleep(2)

    cached = cache.get(test_file, 10)
    if not cached:
        logger.info("过期机制正常 ✓")

    # 清理
    cache.clear_all()


def main():
    logger.info("缓存系统测试\n")

    test_basic_operations()
    test_cache_expiry()

    logger.info("\n所有测试完成 ✓")


if __name__ == "__main__":
    main()
