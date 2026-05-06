# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
创建示例DXF文件用于测试
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import ezdxf


def create_sample_dxf(output_path: str):
    """创建一个简单的示例DXF文件"""
    # 创建新的DXF文档
    doc = ezdxf.new('R2018', units=ezdxf.units.MM)
    msp = doc.modelspace()

    # 添加一些基本几何图形
    # 外轮廓矩形
    msp.add_lwpolyline(
        [(0, 0), (100, 0), (100, 80), (0, 80)],
        close=True,
        dxfattribs={'layer': 'OUTLINE'}
    )

    # 中心圆
    msp.add_circle(
        center=(50, 40),
        radius=15,
        dxfattribs={'layer': 'HOLES'}
    )

    # 两个小圆形孔
    msp.add_circle(center=(25, 20), radius=5, dxfattribs={'layer': 'HOLES'})
    msp.add_circle(center=(75, 20), radius=5, dxfattribs={'layer': 'HOLES'})
    msp.add_circle(center=(25, 60), radius=5, dxfattribs={'layer': 'HOLES'})
    msp.add_circle(center=(75, 60), radius=5, dxfattribs={'layer': 'HOLES'})

    # 一个矩形槽
    msp.add_line((30, 30), (70, 30), dxfattribs={'layer': 'SLOTS'})
    msp.add_line((70, 30), (70, 50), dxfattribs={'layer': 'SLOTS'})
    msp.add_line((70, 50), (30, 50), dxfattribs={'layer': 'SLOTS'})
    msp.add_line((30, 50), (30, 30), dxfattribs={'layer': 'SLOTS'})

    # 添加文字
    msp.add_text(
        "Sample Part",
        dxfattribs={
            'height': 5,
            'insert': (50, 90),
            'layer': 'TEXT'
        }
    )

    # 保存文件
    doc.saveas(output_path)
    print(f"示例DXF文件已创建: {output_path}")


if __name__ == "__main__":
    output_dir = project_root / "examples" / "cad_files"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "sample.dxf"
    create_sample_dxf(str(output_path))
