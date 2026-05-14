#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试底座二视图的处理
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.cad_parser import CADParser
from src.model_generator import FreeCADModeler
import logging


def test_drawing():
    """测试底座二视图"""
    logger = setup_logging(level="DEBUG")
    config = load_config()

    # 使用底座图纸
    cad_dir = project_root / "examples/cad_files"
    possible_names = ["底座二视图.dxf", "底座二视图.DXF"]
    
    cad_file = None
    for name in possible_names:
        f = cad_dir / name
        if f.exists():
            cad_file = f
            break

    if not cad_file:
        logger.error(f"找不到图纸文件，请检查 {cad_dir} 目录")
        return

    logger.info("=" * 60)
    logger.info(f"测试图纸: {cad_file.name}")
    logger.info("=" * 60)

    # 1. 解析CAD文件
    logger.info("\n[1] 解析CAD文件...")
    parser = CADParser(str(cad_file), config.get("dxf_parser", {}))
    geometry_data = parser.parse()
    logger.info(f"解析完成，实体数: {len(geometry_data['entities'])}")

    # 打印图层信息
    layers = {}
    for ent in geometry_data["entities"]:
        layer = ent.get("layer", "无图层")
        layers[layer] = layers.get(layer, 0) + 1
    logger.info(f"图层统计: {layers}")

    # 2. 生成模型
    logger.info("\n[2] 生成3D模型...")
    modeler_config = {}
    if "freecad" in config:
        modeler_config.update(config.get("freecad", {}))
    modeler_config["default_extrude_height"] = 10

    modeler = FreeCADModeler(modeler_config)
    modeler.generate(geometry_data, {})

    # 3. 导出
    logger.info("\n[3] 导出STEP文件...")
    output_dir = project_root / "examples/output/test_drawing"
    output_dir.mkdir(parents=True, exist_ok=True)

    step_path = output_dir / f"{cad_file.stem}.step"
    success = modeler.export(str(step_path), "STEP")

    # 4. 验证结果
    logger.info("\n" + "=" * 60)
    if success and step_path.exists():
        size = step_path.stat().st_size
        logger.info(f"✓ 成功！")
        logger.info(f"  位置: {step_path}")
        logger.info(f"  大小: {size} 字节")

        # 也保存为FCStd供FreeCAD打开
        fcstd_path = output_dir / f"{cad_file.stem}.FCStd"
        modeler.export(str(fcstd_path), "FCStd")
    else:
        logger.error("✗ 导出失败")
        logger.info("\n尝试更简单的导出...")
        # 尝试简单FCStd保存
        fcstd_path = output_dir / f"{cad_file.stem}.FCStd"
        modeler.export(str(fcstd_path), "FCStd")

    modeler.close()
    logger.info("=" * 60)


if __name__ == "__main__":
    test_drawing()
