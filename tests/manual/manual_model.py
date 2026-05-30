#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接测试FreeCAD模型生成
"""

import sys
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging
import logging

logger = setup_logging(level="DEBUG")

# 加载geometry.json
json_path = project_root / "examples" / "output" / "geometry.json"
if not json_path.exists():
    logger.error(f"Geometry文件不存在: {json_path}")
    sys.exit(1)

with open(json_path, 'r', encoding='utf-8') as f:
    geometry_data = json.load(f)

logger.info(f"加载到 {len(geometry_data['entities'])} 个实体")

# 导入FreeCADModeler
from src.model_generator import PlanarExtrudeModeler

modeler = PlanarExtrudeModeler({"default_extrude_height": 10.0})
modeler.generate(geometry_data, {})

# 导出
output_path = project_root / "examples" / "output" / "model_test.step"
modeler.export(str(output_path), "STEP")

logger.info("测试完成")
modeler.close()
