#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单直接的模型生成，只要确保生成一个基本的3D模型
"""

import sys
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 尝试加载FreeCAD
try:
    # 先检查FreeCAD是否在常见位置
    import FreeCAD as App
    import Part
    logger.info("FreeCAD成功加载！")

    # 加载几何数据
    json_path = project_root / "examples" / "output" / "geometry.json"
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    entities = data['entities']
    logger.info(f"找到 {len(entities)} 个实体")

    # 创建文档
    doc = App.newDocument("SimpleTest")

    # 先找到轮廓
    outline = None
    for ent in entities:
        if ent['type'] == 'LWPOLYLINE' and 'OUTLINE' in ent['layer'].upper():
            outline = ent
            break

    if outline:
        # 创建外轮廓
        pts = [App.Vector(p[0], p[1], 0) for p in outline['vertices']]
        edges = []
        for i in range(len(pts)):
            p1 = pts[i]
            p2 = pts[(i+1) % len(pts)]
            edges.append(Part.LineSegment(p1, p2).toShape())
        
        wire = Part.Wire(edges)
        face = Part.Face(wire)
        solid = face.extrude(App.Vector(0,0,10))
        
        # 处理孔
        for ent in entities:
            if ent['type'] == 'CIRCLE' and 'HOLE' in ent['layer'].upper():
                center = App.Vector(ent['center'][0], ent['center'][1], 0)
                circle = Part.Circle(center, App.Vector(0,0,1), ent['radius'])
                w = Part.Wire(circle.toShape())
                f = Part.Face(w)
                hole = f.extrude(App.Vector(0,0,10))
                solid = solid.cut(hole)
        
        Part.show(solid, "Model")
        doc.recompute()
        
        # 导出STEP
        output_path = project_root / "examples" / "output" / "simple_model.step"
        solid.exportStep(str(output_path))
        logger.info(f"模型已导出到: {output_path}")
        logger.info("完成！")
        
    else:
        logger.error("找不到轮廓！")
        
except ImportError as e:
    logger.error(f"FreeCAD加载失败: {e}")
    logger.error("请确保FreeCAD已安装并在系统路径中")
