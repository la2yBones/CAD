# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
快速开始示例
演示从DXF文件解析到3D模型生成的完整流程
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
from src.cad_parser import CADParser
from src.geometry_analyzer import GeometryAnalyzer
from src.model_generator import FreeCADModeler


def main():
    # 设置日志
    logger = setup_logging(level="INFO")
    logger.info("=" * 50)
    logger.info("基于CAD图纸的3D建模系统 - 快速开始")
    logger.info("=" * 50)

    # 加载配置
    config = load_config()
    logger.info("配置加载完成")

    # 1. 解析CAD文件
    cad_path = project_root / "examples" / "cad_files" / "sample.dxf"
    if not cad_path.exists():
        logger.warning(f"示例CAD文件不存在: {cad_path}")
        logger.info("请先放置DXF/DWG文件到 examples/cad_files/ 目录")
        return

    logger.info(f"\n[步骤1] 解析CAD文件: {cad_path}")
    parser = CADParser(str(cad_path), config.get("dxf_parser", {}))
    geometry_data = parser.parse()
    logger.info(f"提取到 {len(geometry_data['entities'])} 个实体")

    # 导出JSON
    json_output = project_root / "examples" / "output" / "geometry.json"
    json_output.parent.mkdir(exist_ok=True)
    parser.export_json(str(json_output))

    # 可视化（可选）
    try:
        viz_output = project_root / "examples" / "output" / "visualization.png"
        parser.visualize(str(viz_output))
    except Exception as e:
        logger.warning(f"可视化跳过: {e}")

    # 2. 分析几何关系
    logger.info("\n[步骤2] 分析几何关系")
    api_key = config.get("api", {}).get("qwen", {}).get("api_key", "")

    if api_key and api_key != "your-dashscope-api-key-here":
        analyzer_config = config.get("api", {}).get("qwen", {})
        analyzer = GeometryAnalyzer(api_key, analyzer_config)
        relationships = analyzer.analyze(geometry_data)
        logger.info(f"关系分析完成: {relationships.get('summary', '')}")
    else:
        logger.warning("未配置API密钥，跳过AI分析")
        relationships = {}

    # 3. 生成3D模型
    logger.info("\n[步骤3] 生成3D模型")
    try:
        # 合并FreeCAD配置和建模配置
        modeler_config = {}
        if "freecad" in config:
            modeler_config.update(config.get("freecad", {}))
        if "modeling" in config:
            modeler_config.update(config.get("modeling", {}))
        
        modeler = FreeCADModeler(modeler_config)
        modeler.generate(geometry_data, relationships)

        # 导出模型
        step_output = project_root / "examples" / "output" / "model.step"
        modeler.export(str(step_output), format="STEP")
        logger.info(f"模型已导出: {step_output}")

        modeler.close()

    except Exception as e:
        logger.error(f"模型生成失败: {e}")
        logger.info("请确保已安装FreeCAD")

    logger.info("\n" + "=" * 50)
    logger.info("处理完成！")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
