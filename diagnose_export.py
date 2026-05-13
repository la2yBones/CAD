#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STEP文件导出诊断和修复工具
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.cad_parser import CADParser
from src.model_generator import FreeCADModeler
import logging


def test_export():
    """测试导出功能"""
    logger = setup_logging(level="INFO")
    config = load_config()

    # 使用示例图纸
    cad_file = project_root / "examples/cad_files/sample.dxf"
    if not cad_file.exists():
        logger.error(f"找不到测试文件: {cad_file}")
        return

    logger.info("=" * 60)
    logger.info("STEP导出诊断测试")
    logger.info("=" * 60)

    # 1. 解析CAD文件
    logger.info("\n[1] 解析CAD文件...")
    parser = CADParser(str(cad_file), config.get("dxf_parser", {}))
    geometry_data = parser.parse()
    logger.info(f"解析完成，实体数: {len(geometry_data['entities'])}")

    # 2. 生成模型
    logger.info("\n[2] 生成3D模型...")
    modeler_config = {}
    if "freecad" in config:
        modeler_config.update(config.get("freecad", {}))
    modeler_config["default_extrude_height"] = 10

    modeler = FreeCADModeler(modeler_config)
    modeler.generate(geometry_data, {})

    # 3. 尝试多种导出方法
    logger.info("\n[3] 测试导出方法...")
    output_dir = project_root / "examples/output/test_diagnostic"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 测试导出
    logger.info("\n--- 测试STEP导出 ---")
    step_path = output_dir / "diagnostic_test.step"
    success = modeler.export(str(step_path), "STEP")
    if success and step_path.exists():
        size = step_path.stat().st_size
        logger.info(f"✓ STEP文件成功创建: {step_path}")
        logger.info(f"  大小: {size} 字节")
    else:
        logger.error("✗ STEP导出失败")

    # 测试FCStd
    logger.info("\n--- 测试FCStd保存 ---")
    fcstd_path = output_dir / "diagnostic_test.FCStd"
    modeler.export(str(fcstd_path), "FCStd")

    modeler.close()

    logger.info("\n" + "=" * 60)
    logger.info("诊断完成，检查输出目录:")
    logger.info(str(output_dir))
    logger.info("=" * 60)


if __name__ == "__main__":
    test_export()
