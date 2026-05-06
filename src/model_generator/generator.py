import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class FreeCADModeler:
    """FreeCAD 3D模型生成器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.doc = None
        self.shape = None
        self._init_freecad()

    def _init_freecad(self):
        """初始化FreeCAD环境"""
        try:
            # 如果配置了FreeCAD路径，先添加到系统路径
            freecad_bin_path = self.config.get("bin_path", "")
            if freecad_bin_path:
                freecad_path = Path(freecad_bin_path)
                if freecad_path.exists():
                    logger.info(f"添加FreeCAD路径到系统环境: {freecad_path}")
                    sys.path.insert(0, str(freecad_path))
                    # 也添加到PATH环境变量
                    if str(freecad_path) not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = str(freecad_path) + os.pathsep + os.environ.get("PATH", "")
            
            import FreeCAD as App
            import Part
            self.App = App
            self.Part = Part
            logger.info("FreeCAD加载成功")
        except ImportError as e:
            logger.warning(f"FreeCAD未找到，部分功能将不可用: {e}")
            self.App = None
            self.Part = None

    def generate(self, geometry_data: Dict[str, Any], relationships: Dict[str, Any]) -> 'FreeCADModeler':
        """
        根据几何数据和关系生成3D模型

        Args:
            geometry_data: 几何数据
            relationships: 关系分析结果

        Returns:
            self
        """
        if self.App is None:
            raise Exception("FreeCAD不可用")

        logger.info("开始生成3D模型")

        # 创建新文档
        self.doc = self.App.newDocument("CADModel")

        # 创建轮廓面和进行拉伸
        entities = geometry_data.get("entities", [])
        extrude_height = self.config.get("default_extrude_height", 10.0)

        # 分离不同层的实体
        outline_entities = []
        hole_entities = []
        slot_entities = []

        for entity in entities:
            layer = entity.get("layer", "").upper()
            if "OUTLINE" in layer:
                outline_entities.append(entity)
            elif "HOLE" in layer:
                hole_entities.append(entity)
            elif "SLOT" in layer:
                slot_entities.append(entity)

        # 首先处理外部轮廓
        if outline_entities:
            logger.info(f"发现 {len(outline_entities)} 个轮廓实体")
            base_shape = self._create_outline_shape(outline_entities)
            if base_shape:
                # 拉伸成3D
                extruded = base_shape.extrude(self.App.Vector(0, 0, extrude_height))

                # 处理孔
                if hole_entities:
                    logger.info(f"发现 {len(hole_entities)} 个孔实体")
                    extruded = self._subtract_holes(extruded, hole_entities, extrude_height)

                # 处理槽
                if slot_entities:
                    logger.info(f"发现 {len(slot_entities)} 个槽实体")
                    extruded = self._subtract_slots(extruded, slot_entities, extrude_height)

                self.shape = extruded
                # 添加到文档
                self.Part.show(extruded, "FinalModel")
                self.doc.recompute()

        logger.info("3D模型生成完成")
        return self

    def _create_outline_shape(self, entities: List[Dict]):
        """创建外部轮廓形状"""
        wires = []
        for entity in entities:
            wire = self._create_wire_from_entity(entity)
            if wire:
                wires.append(wire)

        if not wires:
            logger.warning("没有有效的轮廓实体")
            return None

        # 尝试合并所有的线
        try:
            if len(wires) == 1:
                wire = wires[0]
            else:
                wire = self.Part.Wire(wires)

            if wire.isValid() and wire.isClosed():
                face = self.Part.Face(wire)
                if face.isValid():
                    logger.info("成功创建轮廓面")
                    return face
            else:
                logger.warning("轮廓不是闭合的")
        except Exception as e:
            logger.error(f"创建轮廓失败: {e}")

        return None

    def _create_wire_from_entity(self, entity: Dict):
        """从实体创建线框"""
        try:
            edges = []
            entity_type = entity.get("type")

            if entity_type == "LWPOLYLINE":
                vertices = entity["vertices"]
                for i in range(len(vertices)):
                    p1 = self.App.Vector(vertices[i][0], vertices[i][1], 0)
                    next_idx = (i + 1) % len(vertices)
                    p2 = self.App.Vector(vertices[next_idx][0], vertices[next_idx][1], 0)
                    edges.append(self.Part.LineSegment(p1, p2).toShape())

            elif entity_type == "LINE":
                p1 = self.App.Vector(entity["start"][0], entity["start"][1], 0)
                p2 = self.App.Vector(entity["end"][0], entity["end"][1], 0)
                edges.append(self.Part.LineSegment(p1, p2).toShape())

            if edges:
                wire = self.Part.Wire(edges)
                if wire.isValid():
                    return wire

        except Exception as e:
            logger.warning(f"创建线框失败 {entity_type}: {e}")

        return None

    def _subtract_holes(self, base_shape, hole_entities: List[Dict], height: float):
        """减去孔"""
        result = base_shape
        for entity in hole_entities:
            try:
                if entity["type"] == "CIRCLE":
                    center = self.App.Vector(entity["center"][0], entity["center"][1], 0)
                    circle = self.Part.Circle(center, self.App.Vector(0, 0, 1), entity["radius"])
                    face = self.Part.Face(self.Part.Wire(circle.toShape()))
                    hole = face.extrude(self.App.Vector(0, 0, height))
                    result = result.cut(hole)
            except Exception as e:
                logger.warning(f"减去孔失败: {e}")
        return result

    def _subtract_slots(self, base_shape, slot_entities: List[Dict], height: float):
        """减去槽"""
        try:
            # 收集槽的所有线
            slot_wires = self._collect_wires(slot_entities)
            result = base_shape
            for wire in slot_wires:
                try:
                    face = self.Part.Face(wire)
                    slot_shape = face.extrude(self.App.Vector(0, 0, height))
                    result = result.cut(slot_shape)
                except Exception as e:
                    logger.warning(f"减去槽失败: {e}")
            return result
        except Exception as e:
            logger.warning(f"槽处理失败: {e}")
            return base_shape

    def _collect_wires(self, entities: List[Dict]):
        """收集线框 - 改进版本，正确处理闭合多边形"""
        wires = []
        # 收集所有的点
        points = []
        for entity in entities:
            if entity["type"] == "LINE":
                start = tuple(entity["start"][:2])
                end = tuple(entity["end"][:2])
                points.append((start, end))
        
        if not points:
            return wires
        
        # 简单的连接逻辑：找到连接的线
        try:
            # 尝试按顺序连接
            edges = []
            for entity in entities:
                if entity["type"] == "LINE":
                    p1 = self.App.Vector(entity["start"][0], entity["start"][1], 0)
                    p2 = self.App.Vector(entity["end"][0], entity["end"][1], 0)
                    edges.append(self.Part.LineSegment(p1, p2).toShape())
            
            if edges:
                wire = self.Part.Wire(edges)
                if wire.isValid():
                    if wire.isClosed():
                        wires.append(wire)
                    else:
                        logger.warning("槽线框不闭合，尝试按顺序连接")
                        # 如果不闭合，尝试在最后和第一个之间添加边
                        # 但这里暂时先不处理，因为我们已经有轮廓了
        except Exception as e:
            logger.warning(f"收集线框失败: {e}")
        
        return wires

    def export(self, output_path: str, format: str = "STEP"):
        """
        导出模型

        Args:
            output_path: 输出文件路径
            format: 导出格式 (STEP, STL, FCStd)
        """
        if self.doc is None:
            logger.warning("没有活动文档")
            return

        try:
            if format.upper() == "STEP":
                if self.shape and self.shape.isValid():
                    self.shape.exportStep(output_path)
                    logger.info(f"模型已导出到: {output_path}")
                else:
                    # 尝试导出文档对象
                    for obj in self.doc.Objects:
                        if hasattr(obj, "Shape") and obj.Shape.isValid():
                            obj.Shape.exportStep(output_path)
                            logger.info(f"模型已导出到: {output_path}")
                            break

            elif format.upper() == "STL":
                if self.shape and self.shape.isValid():
                    import Mesh
                    mesh = Mesh.Mesh(self.shape.tessellate(0.1))
                    mesh.write(output_path)
                    logger.info(f"模型已导出到: {output_path}")
                else:
                    for obj in self.doc.Objects:
                        if hasattr(obj, "Shape") and obj.Shape.isValid():
                            import Mesh
                            mesh = Mesh.Mesh(obj.Shape.tessellate(0.1))
                            mesh.write(output_path)
                            logger.info(f"模型已导出到: {output_path}")
                            break
            else:
                self.doc.saveAs(output_path)
                logger.info(f"模型已保存到: {output_path}")
        except Exception as e:
            logger.error(f"导出失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def generate_script(self, output_path: str):
        """
        生成Python建模脚本

        Args:
            output_path: 输出脚本路径
        """
        script_content = f"""
import FreeCAD as App
import Part

doc = App.newDocument("GeneratedModel")

# 此脚本由CAD建模系统自动生成

doc.recompute()
doc.saveAs("{output_path.replace('.py', '.FCStd')}")
"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        logger.info(f"脚本已生成: {output_path}")

    def close(self):
        """关闭文档"""
        if self.doc:
            self.doc = None
