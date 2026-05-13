import sys
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class FreeCADModeler:
    """FreeCAD 3D模型生成器 - 支持 direct 和 subprocess 双模式"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.doc = None
        self.shape = None
        self.bridge = None
        self._bridge_result = None
        self._init_freecad()

    def _init_freecad(self):
        from .freecad_bridge import FreeCADBridge
        self.bridge = FreeCADBridge(self.config)
        if self.bridge.mode == "direct":
            self.App = self.bridge.App
            self.Part = self.bridge.Part
            logger.info("FreeCAD initialized (direct mode)")
        elif self.bridge.mode == "subprocess":
            self.App = None
            self.Part = None
            logger.info("FreeCAD will be called via subprocess")
        else:
            self.App = None
            self.Part = None
            logger.warning(
                "FreeCAD not available. Install FreeCAD 1.0+ and set freecad.bin_path in config.yaml"
            )

    def generate(self, geometry_data: Dict[str, Any], relationships: Dict[str, Any]) -> 'FreeCADModeler':
        """
        根据几何数据和关系生成3D模型

        Args:
            geometry_data: 几何数据
            relationships: 关系分析结果

        Returns:
            self
        """
        if self.bridge is not None and self.bridge.mode == "subprocess":
            return self._generate_via_bridge(geometry_data, relationships)

        if self.App is None:
            raise Exception(
                "FreeCAD not available. "
                "Install FreeCAD 1.0+ and set freecad.bin_path in config.yaml, "
                "or run inside FreeCAD's Python environment."
            )

        return self._generate_direct(geometry_data, relationships)

    def _generate_direct(self, geometry_data: Dict[str, Any], relationships: Dict[str, Any]) -> 'FreeCADModeler':
        logger.info("generating 3D model (direct mode)")

        # 创建新文档
        self.doc = self.App.newDocument("CADModel")

        # 创建轮廓面和进行拉伸
        entities = geometry_data.get("entities", [])
        extrude_height = self.config.get("default_extrude_height", 10.0)

        # 分离不同层的实体（支持中英文）
        outline_entities = []
        hole_entities = []
        slot_entities = []

        for entity in entities:
            layer = entity.get("layer", "").upper()
            # 支持中英文图层名
            if "OUTLINE" in layer or "轮廓" in layer:
                outline_entities.append(entity)
            elif "HOLE" in layer or "孔" in layer:
                hole_entities.append(entity)
            elif "SLOT" in layer or "槽" in layer:
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
                obj = self.Part.show(extruded, "FinalModel")
                self.doc.recompute()
                logger.info(f"模型对象创建: {obj.Name}")
                logger.info(f"形状有效性: {self.shape.isValid()}")

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
        """从实体创建线框（支持LWPOLYLINE, LINE, CIRCLE, ARC）"""
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

            elif entity_type == "CIRCLE":
                center = self.App.Vector(entity["center"][0], entity["center"][1], 0)
                radius = entity["radius"]
                circle = self.Part.Circle(center, self.App.Vector(0, 0, 1), radius)
                edges.append(circle.toShape())

            elif entity_type == "ARC":
                center = self.App.Vector(entity["center"][0], entity["center"][1], 0)
                radius = entity["radius"]
                start_angle = entity.get("start_angle", 0) * 3.14159265 / 180.0
                end_angle = entity.get("end_angle", 360) * 3.14159265 / 180.0
                
                circle = self.Part.Circle(center, self.App.Vector(0, 0, 1), radius)
                arc = self.Part.ArcOfCircle(circle, start_angle, end_angle)
                edges.append(arc.toShape())

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

    def _generate_via_bridge(self, geometry_data: Dict[str, Any],
                              relationships: Dict[str, Any]) -> 'FreeCADModeler':
        logger.info("generating 3D model (subprocess mode)")
        extrude_height = self.config.get("default_extrude_height", 10.0)
        script = self.bridge.build_geometry_script(geometry_data, extrude_height)
        output_dir = tempfile.mkdtemp(prefix="cad_model_")
        self._bridge_result = self.bridge.execute_script(script, output_dir)
        if self._bridge_result.get("success"):
            logger.info("subprocess modeling completed")
        else:
            logger.error(f"subprocess modeling failed: {self._bridge_result.get('error')}")
        return self

    def export(self, output_path: str, format: str = "STEP"):
        """
        导出模型

        Args:
            output_path: 输出文件路径
            format: 导出格式 (STEP, STL, FCStd)
        """
        if self._bridge_result is not None:
            return self._export_from_bridge(output_path, format)

        if self.doc is None:
            logger.warning("没有活动文档")
            return False

        try:
            # 确保输出目录存在
            out_dir = Path(output_path).parent
            out_dir.mkdir(parents=True, exist_ok=True)

            exported = False
            output_path = str(Path(output_path).absolute())

            logger.info(f"开始导出: {output_path}")

            if format.upper() == "STEP":
                # 方法1: 直接从self.shape导出
                if self.shape is not None and self.shape.isValid():
                    try:
                        logger.info("方法1: 从self.shape导出STEP")
                        self.shape.exportStep(output_path)
                        if Path(output_path).exists():
                            logger.info(f"✓ 方法1成功")
                            exported = True
                    except Exception as e:
                        logger.warning(f"方法1失败: {e}")

                # 方法2: 从文档对象导出
                if not exported:
                    try:
                        logger.info("方法2: 从文档对象导出STEP")
                        for obj in self.doc.Objects:
                            if hasattr(obj, "Shape") and obj.Shape.isValid():
                                obj.Shape.exportStep(output_path)
                                if Path(output_path).exists():
                                    logger.info(f"✓ 方法2成功")
                                    exported = True
                                    break
                    except Exception as e:
                        logger.warning(f"方法2失败: {e}")

                # 方法3: 使用Part.export()
                if not exported and self.shape is not None:
                    try:
                        logger.info("方法3: 使用Part.export()")
                        import Part
                        shapes = [self.shape]
                        Part.export(shapes, output_path)
                        if Path(output_path).exists():
                            logger.info(f"✓ 方法3成功")
                            exported = True
                    except Exception as e:
                        logger.warning(f"方法3失败: {e}")

                if not exported:
                    logger.error("所有STEP导出失败，所有方法都失败")

            elif format.upper() == "STL":
                if self.shape and self.shape.isValid():
                    try:
                        import Mesh
                        mesh = Mesh.Mesh(self.shape.tessellate(0.1))
                        mesh.write(output_path)
                        logger.info(f"STL模型已导出到: {output_path}")
                        exported = True
                    except Exception as e:
                        logger.warning(f"STL导出失败: {e}")
                else:
                    for obj in self.doc.Objects:
                        if hasattr(obj, "Shape") and obj.Shape.isValid():
                            import Mesh
                            mesh = Mesh.Mesh(obj.Shape.tessellate(0.1))
                            mesh.write(output_path)
                            logger.info(f"STL模型已导出到: {output_path}")
                            exported = True
                            break
            else:
                self.doc.saveAs(output_path)
                logger.info(f"模型已保存到: {output_path}")
                exported = True

            # 验证文件是否存在
            if exported and not Path(output_path).exists():
                logger.warning(f"导出后文件不存在: {output_path}")
                # 尝试用另一种方式（通过文档保存）
                try:
                    fcstd_path = str(Path(output_path).with_suffix('.FCStd'))
                    self.doc.saveAs(fcstd_path)
                    logger.info(f"已保存为FreeCAD文档: {fcstd_path}")
                except Exception as e2:
                    logger.error(f"备用导出也失败: {e2}")

            if exported:
                file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
                logger.info(f"导出成功，文件大小: {file_size} 字节")

            return exported

        except Exception as e:
            logger.error(f"导出失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

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

    def _export_from_bridge(self, output_path: str, format: str = "STEP") -> bool:
        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        fmt = format.upper()
        source_key = None
        ext = None

        if fmt == "STEP":
            source_key = "step_path"
            ext = ".step"
        elif fmt == "FCStd":
            source_key = "fcstd_path"
            ext = ".FCStd"
        else:
            source_key = "fcstd_path"
            ext = ".FCStd"

        src = self._bridge_result.get(source_key) if self._bridge_result else None
        if src and Path(src).exists():
            import shutil
            dest = str(Path(output_path).with_suffix(ext))
            shutil.copy2(src, dest)
            logger.info(f"exported from bridge: {dest}")
            return Path(dest).exists()

        outputs = (self._bridge_result or {}).get("outputs", [])
        for o in outputs:
            if o.lower().endswith(ext.lower()):
                import shutil
                dest = str(Path(output_path).with_suffix(ext))
                shutil.copy2(o, dest)
                logger.info(f"exported from bridge: {dest}")
                return Path(dest).exists()

        logger.warning(f"no {fmt} output found in bridge result")
        return False

    def close(self):
        """关闭文档"""
        if self.doc:
            self.doc = None
