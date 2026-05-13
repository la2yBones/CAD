#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理自定义CAD图纸
修改下面的配置来处理你自己的图纸
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.cad_parser import CADParser
from src.intelligent_analyzer import IntelligentEngineeringAnalyzer
from src.model_generator import FreeCADModeler

def main():
    # =========================================================
    # 在这里配置你的图纸文件
    # =========================================================
    CAD_FILE = "examples/cad_files/sample.dxf"  # 改成你的图纸文件名
    EXTRUDE_HEIGHT = 10.0  # 拉伸高度(mm)，根据需要修改
    # =========================================================

    logger = setup_logging(level="INFO")
    logger.info("=" * 50)
    logger.info("自定义CAD图纸处理")
    logger.info("=" * 50)

    # 检查图纸是否存在
    cad_path = project_root / CAD_FILE
    if not cad_path.exists():
        logger.error(f"图纸文件不存在: {cad_path}")
        logger.info(f"请将你的图纸放到 {project_root / 'examples' / 'cad_files'} 目录中")
        return

    config = load_config()
    logger.info(f"处理图纸: {CAD_FILE}")

    # 1. 解析CAD
    logger.info("\n[步骤1] 解析CAD文件...")
    parser = CADParser(str(cad_path), config.get("dxf_parser", {}))
    geometry_data = parser.parse()
    logger.info(f"提取到 {len(geometry_data['entities'])} 个实体")

    # 保存解析结果
    json_output = project_root / "examples" / "output" / f"{cad_path.stem}_geometry.json"
    parser.export_json(str(json_output))
    logger.info(f"几何数据已保存到: {json_output}")

    # 2. 统一智能分析
    logger.info("\n[步骤2] 智能分析...")
    api_key = config.get("api", {}).get("deepseek", {}).get("api_key", "")
    relationships = {}
    if api_key and api_key != "your-deepseek-api-key-here":
        analyzer_config = config.get("api", {}).get("deepseek", {})
        analyzer = IntelligentEngineeringAnalyzer(api_key, analyzer_config, enable_cache=True)
        analysis_result = analyzer.analyze_full(geometry_data, extrude_height=EXTRUDE_HEIGHT)
        relationships = analysis_result.get("modeling_instructions", {})
    else:
        logger.info("跳过智能分析（未配置API密钥）")

    # 3. 生成3D模型
    logger.info("\n[步骤3] 生成3D模型...")
    modeler_config = {}
    if "freecad" in config:
        modeler_config.update(config.get("freecad", {}))
    modeler_config["default_extrude_height"] = EXTRUDE_HEIGHT

    modeler = FreeCADModeler(modeler_config)
    modeler.generate(geometry_data, relationships)

    step_output = project_root / "examples" / "output" / f"{cad_path.stem}.step"
    modeler.export(str(step_output), "STEP")
    logger.info(f"模型已导出: {step_output}")

    modeler.close()

    logger.info("\n" + "=" * 50)
    logger.info("处理完成！")
    logger.info(f"3D模型位置: {step_output}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
