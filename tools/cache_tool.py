#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存管理命令行工具
"""
import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.cache import AnalysisCache
from src.utils import setup_logging, load_config
import logging


def main():
    parser = argparse.ArgumentParser(
        description="CAD图纸分析缓存管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("command", choices=["clear", "clear-expired", "stats", "invalidate"], 
                       help="操作命令")
    parser.add_argument("--file", help="要失效的文件路径")
    parser.add_argument("--cache-dir", default=".cache/analysis", help="缓存目录")
    parser.add_argument("--verbose", action="store_true", help="显示详细日志")

    args = parser.parse_args()

    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    config = load_config()
    cache = AnalysisCache(
        cache_dir=args.cache_dir or config.get('cache_dir', '.cache/analysis'),
        default_ttl=config.get('cache_ttl', 3600 * 24 * 7)
    )

    if args.command == "stats":
        logger.info("=== 缓存统计 ===")
        stats = cache.get_stats()
        print(f"缓存目录: {stats['cache_dir']}")
        print(f"缓存文件数: {stats['total_count']}")
        print(f"总大小: {stats['total_size_mb']} MB")

    elif args.command == "clear":
        print("清空所有缓存...")
        count = cache.clear_all()
        print(f"已删除 {count} 个缓存文件")

    elif args.command == "clear-expired":
        print("清理过期缓存...")
        count = cache.clear_expired()
        print(f"已删除 {count} 个过期缓存文件")

    elif args.command == "invalidate":
        if not args.file:
            print("错误: 请指定要失效的文件路径")
            return
        count = cache.invalidate(args.file)
        print(f"已删除 {count} 个相关缓存")


if __name__ == "__main__":
    main()
