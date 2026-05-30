#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD图纸处理命令行工具"""

import sys
import os

os.environ.setdefault('MPLBACKEND', 'Agg')

try:
    import matplotlib
    matplotlib.use('Agg')
except Exception:
    pass

import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging
from src.batch_processor import CADPipeline


logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="CAD图纸3D建模工具 (统一版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cad_cli.py --file sample.dxf
  python cad_cli.py --dir examples/cad_files --output-dir my_output
  python cad_cli.py --list
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", help="指定要处理的CAD文件名")
    group.add_argument("--dir", "-d", help="指定包含CAD文件的文件夹路径")
    group.add_argument("--list", "-l", action="store_true", help="列出可用的CAD文件")

    parser.add_argument("--input-dir", "-i", default="examples/cad_files",
                        help="CAD文件所在目录 (默认: examples/cad_files)")
    parser.add_argument("--output-dir", "-o", default="examples/output",
                        help="输出目录 (默认: examples/output)")
    parser.add_argument("--height", "-H", type=float, default=10.0,
                        help="拉伸高度(mm) (默认: 10.0)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="显示详细日志")

    args = parser.parse_args()

    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)
    config = load_config()

    logger.info("=" * 60)
    logger.info("CAD图纸3D建模 - 命令行工具")
    logger.info("=" * 60)

    if args.list:
        pipeline = CADPipeline(
            config=config,
            input_dir=args.input_dir,
            output_dir=args.output_dir
        )
        files = pipeline.list_available_files()
        if not files:
            logger.info("未找到CAD文件")
        else:
            logger.info(f"找到 {len(files)} 个CAD文件:")
            for f in files:
                size_kb = f["size"] / 1024
                logger.info(f"  - {f['name']} ({size_kb:.1f} KB)")
        return

    if args.file:
        _process_single_file(args, config)
    elif args.dir:
        _process_directory(args, config)


def _process_single_file(args, config):
    logger.info(f"处理文件: {args.file}")
    logger.info("模式: 统一智能处理")

    pipeline = CADPipeline(
        config=config,
        input_dir=args.input_dir,
        output_dir=args.output_dir
    )

    result = pipeline.process_file_intelligent(args.file)

    status = getattr(getattr(result, "status", None), "value", "")
    if result.success:
        if status == "partial_completed":
            logger.info("\n✓ 处理部分完成，已生成可检查的主体模型")
            if getattr(result, "partial_completion_reason", None):
                logger.info(f"  原因: {result.partial_completion_reason}")
            for feature in getattr(result, "skipped_features", []) or []:
                logger.info(f"  跳过细节: {feature}")
        else:
            logger.info("\n✓ 处理成功!")
        logger.info(f"  实体数: {result.entity_count}")
        for key, path in result.output_paths.items():
            logger.info(f"  {key}: {path}")
    else:
        logger.error(f"\n✗ 处理失败: {result.error_message}")
        sys.exit(1)


def _process_directory(args, config):
    logger.info(f"处理目录: {args.dir}")
    logger.info(f"拉伸高度: {args.height}mm")

    pipeline = CADPipeline(
        config=config,
        input_dir=args.input_dir,
        output_dir=args.output_dir
    )

    def progress(current, total, result):
        logger.info(f"[{current}/{total}] {'✓' if result.success else '✗'} {Path(result.input_file).name}")

    results = pipeline.process_directory_intelligent(
        input_dir=args.dir,
        extrude_height=args.height,
        progress_callback=progress
    )

    pipeline.print_summary(results)


if __name__ == "__main__":
    main()
