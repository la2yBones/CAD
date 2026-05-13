#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD图纸处理命令行工具（统一版）
支持基础处理、AI几何分析、智能分析三种模式
"""

import sys
import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import load_config, setup_logging, Result
from src.batch_processor import BatchPipeline, CADProcessor, CADProcessResult, FileManager


logger = logging.getLogger(__name__)


def _run_intelligent_analysis_only(file_path, config, extrude_height, output_dir):
    """仅运行智能分析，不生成3D模型"""
    from src.cad_parser import CADParser
    from src.intelligent_analyzer import IntelligentEngineeringAnalyzer

    api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
    if not api_key or api_key == "your-deepseek-api-key-here":
        logger.error("未配置DeepSeek API Key，请在 config/config.yaml 中设置")
        return None

    parser = CADParser(config)
    parse_result = parser.parse(file_path)
    if parse_result.is_err():
        logger.error(f"解析失败: {parse_result.error}")
        return None
    geometry_data = parse_result.value
    entity_count = len(geometry_data.get("entities", []))
    logger.info(f"解析完成，提取到 {entity_count} 个实体")

    cache_config = config.get("cache", {})
    analyzer = IntelligentEngineeringAnalyzer(
        api_key,
        config.get("api", {}).get("deepseek", {}),
        enable_cache=True,
        cache_dir=cache_config.get("cache_dir"),
        cache_ttl=config.get("cache_ttl", 3600 * 24 * 7)
    )
    analysis_result = analyzer.analyze_full(
        geometry_data, extrude_height, file_path=str(file_path)
    )
    if analysis_result.is_err():
        logger.error(f"智能分析失败: {analysis_result.error}")
        return None

    analysis_data = analysis_result.value

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    base_name = Path(file_path).stem

    script = analysis_data.get("freecad_script", "")
    if script:
        script_path = output_path / f"{base_name}_freecad.py"
        script_path.write_text(script, encoding="utf-8")
        logger.info(f"  FreeCAD脚本: {script_path}")

    import json
    json_path = output_path / f"{base_name}_full.json"
    json_path.write_text(json.dumps(analysis_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    logger.info("智能分析结果已保存:")
    logger.info(f"  完整数据: {json_path}")

    return {"entity_count": entity_count, "output_dir": str(output_path)}


def main():
    parser = argparse.ArgumentParser(
        description="CAD图纸3D建模工具 (统一版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
处理模式:
  默认模式      纯几何建模（不调用API）
  --analysis    基础AI分析模式（AI几何关系分析 + 通用建模器）
  --intelligent 智能分析模式（AI视图识别 + 尺寸提取 + AI脚本建模）
  --analysis-only 仅AI分析模式（生成分析报告和FreeCAD脚本，不建3D模型）

示例:
  python cad_cli.py --file sample.dxf
  python cad_cli.py --file sample.dxf --height 10 --analysis
  python cad_cli.py --file sample.dxf --intelligent
  python cad_cli.py --file sample.dxf --analysis-only
  python cad_cli.py --dir examples/cad_files --out examples/output
  python cad_cli.py --list
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", help="指定要处理的CAD文件名")
    group.add_argument("--dir", "-d", help="指定包含CAD文件的文件夹路径")
    group.add_argument("--list", "-l", action="store_true", help="列出可用的CAD文件")

    analysis_group = parser.add_mutually_exclusive_group()
    analysis_group.add_argument("--analysis", "-a", action="store_true",
                                help="启用基础AI几何关系分析（DeepSeek API）")
    analysis_group.add_argument("--intelligent", "-I", action="store_true",
                                help="启用智能分析（视图识别+尺寸提取+AI脚本建模）")
    analysis_group.add_argument("--analysis-only", "-A", action="store_true",
                                help="仅运行智能分析并保存报告，不生成3D模型")

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
        scan_result = FileManager.scan_files(args.input_dir)
        if scan_result.is_err():
            logger.info(f"目录扫描失败: {scan_result.error}")
        else:
            files = scan_result.value
            logger.info(f"找到 {len(files)} 个CAD文件:")
            for f in files:
                try:
                    size_kb = f.stat().st_size / 1024
                    logger.info(f"  - {f.name} ({size_kb:.1f} KB)")
                except OSError:
                    logger.info(f"  - {f.name}")
        return

    if args.file:
        _process_single_file(args, config)
    elif args.dir:
        _process_directory(args, config)


def _process_single_file(args, config):
    logger.info(f"处理文件: {args.file}")

    if args.analysis_only:
        logger.info("模式: 仅智能分析（不生成模型）")
        logger.info(f"拉伸高度: {args.height}mm")
        result = _run_intelligent_analysis_only(
            args.file, config, args.height, args.output_dir
        )
        if result:
            logger.info(f"\n√ 分析完成! 实体数: {result['entity_count']}")
            logger.info(f"  输出目录: {result['output_dir']}")
        else:
            sys.exit(1)
        return

    mode_label = ("智能分析 (视图识别+尺寸提取+AI脚本)" if args.intelligent
                  else ("基础AI分析" if args.analysis else "纯几何建模"))
    logger.info(f"模式: {mode_label}")
    logger.info(f"拉伸高度: {args.height}mm")

    pipeline = BatchPipeline(config)

    if args.intelligent:
        api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
        result = pipeline.process_file_intelligent(
            args.file,
            api_key,
            output_dir=args.output_dir,
            extrude_height=args.height
        )
    elif args.analysis:
        result = pipeline.process_file(
            args.file,
            output_dir=args.output_dir,
            extrude_height=args.height
        )
    else:
        result = pipeline.process_file(
            args.file,
            output_dir=args.output_dir,
            extrude_height=args.height
        )

    if result.success:
        logger.info("\n√ 处理成功!")
        logger.info(f"  处理时间: {result.processing_time_seconds:.1f}秒")
        if result.model_result:
            logger.info(f"  输出目录: {result.model_result.get('output_dir', '')}")
    else:
        logger.error(f"\n× 处理失败: {result.error_message}")
        sys.exit(1)


def _process_directory(args, config):
    logger.info(f"处理目录: {args.dir}")
    logger.info(f"拉伸高度: {args.height}mm")

    pipeline = BatchPipeline(config)

    results, summary = pipeline.process_directory(
        input_dir=args.dir,
        output_dir=args.output_dir,
        extrude_height=args.height
    )

    for r in results:
        status = "√" if r.success else "×"
        logger.info(f"  {status} {Path(r.file_path).name}")

    if summary.get("error"):
        logger.error(f"批量处理失败: {summary['error']}")
        sys.exit(1)
    else:
        logger.info(f"\n批量处理完成: {summary['successful']}/{summary['total_files']} 成功 ({summary['success_rate']})")
