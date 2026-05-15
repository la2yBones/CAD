#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行AI生成的FreeCAD脚本并导出STEP
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logging, load_config
import logging


def run_and_export():
    """运行AI脚本并导出"""
    logger = setup_logging(level="INFO")
    
    # 找到AI生成的脚本
    script_path = project_root / "examples/output/底座二视图/底座二视图_freecad.py"
    if not script_path.exists():
        logger.error(f"找不到AI脚本: {script_path}")
        return

    logger.info("=" * 60)
    logger.info("运行AI生成的FreeCAD脚本")
    logger.info("=" * 60)

    try:
        # 添加FreeCAD路径
        config = load_config()
        fc_path = config.get("freecad", {}).get("bin_path", "")
        if fc_path:
            sys.path.insert(0, fc_path)

        import FreeCAD as App
        import Part
        logger.info("FreeCAD已加载")

        # 准备输出路径
        output_dir = project_root / "examples/output/底座二视图"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        step_path = output_dir / "底座二视图.step"
        fcstd_path = output_dir / "底座二视图.FCStd"

        # 创建新文档
        doc = App.newDocument("MechanicalPart")

        # 关键尺寸参数（基于图纸坐标差值推导）
        BASE_W, BASE_H = 96.0, 96.0
        BASE_THICK = 8.0
        BOSS_DIA = 64.0
        BOSS_LEN = 40.0
        HOLE_DIA = 32.0
        TOTAL_THICK = BASE_THICK + BOSS_LEN  # 48.0
        FILLET_R = 1.5

        # 1. 创建底座 (96x96x8)
        base = Part.makeBox(BASE_W, BASE_H, BASE_THICK)
        base.Placement.Base = App.Vector(-BASE_W/2, -BASE_H/2, 0)

        # 2. 底座四角倒圆角 (R1.5)
        # 筛选垂直方向的边（长度等于底座厚度）
        v_edges = [e for e in base.Edges if abs(e.Length - BASE_THICK) < 0.01]
        base_fillet = base.makeFillet(FILLET_R, v_edges)

        # 3. 创建中心凸台 (D64, 长40)
        boss = Part.makeCylinder(BOSS_DIA/2, BOSS_LEN)
        boss.Placement.Base = App.Vector(0, 0, BASE_THICK)

        # 4. 布尔并集：底座 + 凸台
        body = base_fillet.fuse(boss)

        # 5. 创建中心通孔 (D32, 贯穿总厚度48)
        hole = Part.makeCylinder(HOLE_DIA/2, TOTAL_THICK)
        hole.Placement.Base = App.Vector(0, 0, 0)

        # 6. 布尔差集：切除通孔
        final_shape = body.cut(hole)

        # 7. 生成模型对象并更新
        obj = doc.addObject("Part::Feature", "PartModel")
        obj.Shape = final_shape
        doc.recompute()

        logger.info("\n模型创建完成")
        logger.info(f"形状有效: {final_shape.isValid()}")

        # 导出STEP
        logger.info(f"\n导出STEP: {step_path}")
        final_shape.exportStep(str(step_path))
        
        # 保存FCStd
        logger.info(f"保存FCStd: {fcstd_path}")
        doc.saveAs(str(fcstd_path))

        if step_path.exists():
            size = step_path.stat().st_size
            logger.info("\n" + "=" * 60)
            logger.info(f"✓ 成功！")
            logger.info(f"  STEP: {step_path}")
            logger.info(f"  大小: {size} 字节")
            logger.info(f"  FCStd: {fcstd_path}")
            logger.info("=" * 60)
        else:
            logger.error("导出失败！")

    except Exception as e:
        logger.error(f"错误: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    run_and_export()
