import ezdxf
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

ELLIPSE_POLYLINE_SEGMENTS = 32
SPLINE_SAMPLE_SEGMENTS = 48


class CADParser:
    """CAD文件解析器，支持DXF和DWG格式，提取几何实体并转换为标准化格式"""

    def __init__(self, file_path: str, config: Optional[Dict] = None):
        self.file_path = Path(file_path)
        self.config = config or {}
        self.doc: Optional[ezdxf.document.Drawing] = None
        self.entities: List[Dict] = []
        self._block_cache: Dict[str, List[Dict]] = {}

    def parse(self) -> Dict[str, Any]:
        """
        解析DXF文件

        Returns:
            包含版本、单位和实体数据的字典
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")

        logger.info(f"正在解析文件: {self.file_path}")

        # 处理DWG文件（如果需要）
        if self.file_path.suffix.lower() == ".dwg":
            self._convert_dwg_to_dxf()

        # 加载DXF文件
        self.doc = ezdxf.readfile(str(self.file_path))

        # 提取实体
        self._extract_entities()

        # 构建结果
        result = {
            "version": self.doc.dxfversion,
            "units": self._get_units(),
            "entities": self.entities
        }

        logger.info(f"解析完成，共提取 {len(self.entities)} 个实体")
        return result

    def _convert_dwg_to_dxf(self):
        """使用LibreDWG将DWG转换为DXF"""
        try:
            self._convert_with_libredwg()
        except Exception as e:
            logger.error(f"DWG转换失败: {e}")
            raise
    
    def _convert_with_libredwg(self):
        """使用LibreDWG将DWG转换为DXF"""
        import shutil
        import tempfile

        libredwg_path = Path(self.config.get("libredwg_path", ""))
        
        if not libredwg_path.exists():
            raise FileNotFoundError(f"LibreDWG路径不存在: {libredwg_path}")
        
        dwg2dxf = libredwg_path / "dwg2dxf.exe"
        if not dwg2dxf.exists():
            for p in libredwg_path.rglob("dwg2dxf.exe"):
                dwg2dxf = p
                break
        
        if not dwg2dxf.exists():
            raise FileNotFoundError(f"未找到 dwg2dxf.exe 在: {libredwg_path}")
        
        dxf_target = self.file_path.with_suffix(".dxf")

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".dxf", prefix="cad_convert_")
        os.close(tmp_fd)
        tmp_dxf = Path(tmp_path)

        cmd = [
            str(dwg2dxf),
            "-y",
            "-o", str(tmp_dxf),
            str(self.file_path)
        ]
        
        logger.info(f"LibreDWG转换: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode != 0 or not tmp_dxf.exists():
            stderr = (result.stderr or "")[-500:]
            logger.error(f"LibreDWG转换失败 (退出码: {result.returncode})")
            if stderr:
                logger.error(f"STDERR: {stderr}")
            try:
                tmp_dxf.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(f"LibreDWG转换失败: {stderr}")
        
        shutil.move(str(tmp_dxf), str(dxf_target))

        self.file_path = dxf_target
        if dxf_target.exists():
            logger.info(f"LibreDWG转换成功: {dxf_target}")
        else:
            raise FileNotFoundError(f"转换后的DXF文件未生成: {dxf_target}")
    
    def _extract_entities(self):
        """从模型空间提取几何实体，支持块引用展开"""
        msp = self.doc.modelspace()
        supported_types = self.config.get("extract_entities", [
            "LINE", "CIRCLE", "ARC", "LWPOLYLINE", "TEXT", "MTEXT",
            "ELLIPSE", "SPLINE", "DIMENSION", "INSERT"
        ])

        for entity in msp:
            entity_type = entity.dxftype()

            if entity_type == "INSERT":
                if "INSERT" in supported_types:
                    expanded = self._expand_block(entity)
                    if expanded:
                        self.entities.extend(expanded)
                continue

            if entity_type in supported_types:
                parsed = self._parse_entity(entity)
                if parsed:
                    self.entities.append(parsed)

    def _parse_entity(self, entity) -> Optional[Dict]:
        """解析单个DXF实体，支持 LINE/CIRCLE/ARC/LWPOLYLINE/TEXT/MTEXT/ELLIPSE/SPLINE/DIMENSION"""
        base_info = {
            "type": entity.dxftype(),
            "layer": entity.dxf.layer,
            "color": entity.dxf.color,
        }

        try:
            etype = entity.dxftype()

            if etype == "LINE":
                base_info.update({
                    "start": list(entity.dxf.start),
                    "end": list(entity.dxf.end)
                })
            elif etype == "CIRCLE":
                base_info.update({
                    "center": list(entity.dxf.center),
                    "radius": entity.dxf.radius
                })
            elif etype == "ARC":
                base_info.update({
                    "center": list(entity.dxf.center),
                    "radius": entity.dxf.radius,
                    "start_angle": entity.dxf.start_angle,
                    "end_angle": entity.dxf.end_angle
                })
            elif etype == "LWPOLYLINE":
                base_info.update({
                    "vertices": [list(v) for v in entity.get_points("xy")],
                    "closed": entity.closed
                })
            elif etype == "TEXT":
                base_info.update({
                    "text": entity.dxf.text,
                    "position": list(entity.dxf.insert),
                    "height": entity.dxf.height
                })
            elif etype == "MTEXT":
                base_info.update({
                    "text": entity.text,
                    "position": list(entity.dxf.insert)
                })
            elif etype == "ELLIPSE":
                base_info.update(self._parse_ellipse(entity))
            elif etype == "SPLINE":
                base_info.update(self._parse_spline(entity))
            elif etype == "DIMENSION":
                base_info.update(self._parse_dimension(entity))
            else:
                return None

            return base_info

        except Exception as e:
            logger.warning(f"解析实体失败: {entity.dxftype()}, 错误: {e}")
            return None

    def _parse_ellipse(self, entity) -> Dict:
        center = list(entity.dxf.center)
        major_vec = entity.dxf.major_axis
        major_len = math.hypot(major_vec[0], major_vec[1])
        ratio = entity.dxf.ratio
        minor_len = major_len * ratio
        angle = math.atan2(major_vec[1], major_vec[0])

        vertices = []
        n = ELLIPSE_POLYLINE_SEGMENTS
        for i in range(n + 1):
            t = 2.0 * math.pi * i / n
            rx = major_len * math.cos(t + angle)
            ry = minor_len * math.sin(t + angle)
            vertices.append([center[0] + rx, center[1] + ry])
        return {"vertices": vertices, "closed": True, "original_type": "ELLIPSE"}

    def _parse_spline(self, entity) -> Dict:
        try:
            fit_points = entity.fit_points
            if fit_points and len(fit_points) >= 2:
                pts = [list(p) for p in fit_points]
                return {"vertices": pts, "closed": entity.closed, "original_type": "SPLINE"}
        except Exception:
            pass
        try:
            ctrl_points = entity.control_points
            if ctrl_points and len(ctrl_points) >= 2:
                pts = [list(p) for p in ctrl_points]
                return {"vertices": pts, "closed": entity.closed, "original_type": "SPLINE"}
        except Exception:
            pass
        return {"vertices": [], "closed": False, "original_type": "SPLINE"}

    def _parse_dimension(self, entity) -> Dict:
        dim_info: Dict[str, Any] = {}
        try:
            dim_info["measurement"] = entity.dxf.measurement
        except Exception:
            dim_info["measurement"] = 0.0
        try:
            dim_info["text"] = entity.dxf.text
        except Exception:
            pass
        try:
            dim_info["dimension_type"] = entity.dimtype
        except Exception:
            pass
        points = []
        for attr_name in ("defpoint2", "defpoint3", "defpoint4", "defpoint5"):
            try:
                pt = getattr(entity.dxf, attr_name, None)
                if pt is not None:
                    points.append(list(pt))
            except Exception:
                pass
        dim_info["definition_points"] = points
        return dim_info

    def _expand_block(self, insert_entity) -> List[Dict]:
        block_name = insert_entity.dxf.name
        insert_pt = list(insert_entity.dxf.insert)
        angle = insert_entity.dxf.rotation if hasattr(insert_entity.dxf, "rotation") else 0.0
        sx = insert_entity.dxf.xscale if hasattr(insert_entity.dxf, "xscale") else 1.0
        sy = insert_entity.dxf.yscale if hasattr(insert_entity.dxf, "yscale") else 1.0

        if block_name in self._block_cache:
            return self._transform_block_entities(self._block_cache[block_name], insert_pt, angle, sx, sy)

        try:
            block = self.doc.blocks.get(block_name)
        except Exception:
            logger.debug(f"Block not found: {block_name}")
            return []

        sub_entities: List[Dict] = []
        for sub in block:
            result = self._parse_entity(sub)
            if isinstance(result, dict):
                sub_entities.append(result)

        self._block_cache[block_name] = sub_entities
        return self._transform_block_entities(sub_entities, insert_pt, angle, sx, sy)

    def _transform_block_entities(self, entities: List[Dict], origin: List[float],
                                    angle: float, sx: float, sy: float) -> List[Dict]:
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        transformed: List[Dict] = []

        for ent in entities:
            new_ent = dict(ent)
            new_ent["_block_ref"] = True

            if "center" in new_ent:
                cx, cy = new_ent["center"][0], new_ent["center"][1]
                rx = cx * cos_a - cy * sin_a
                ry = cx * sin_a + cy * cos_a
                new_ent["center"] = [origin[0] + rx * sx, origin[1] + ry * sy] + ([new_ent["center"][2]] if len(new_ent["center"]) > 2 else [])

            if "start" in new_ent:
                rx = new_ent["start"][0] * cos_a - new_ent["start"][1] * sin_a
                ry = new_ent["start"][0] * sin_a + new_ent["start"][1] * cos_a
                new_ent["start"] = [origin[0] + rx * sx, origin[1] + ry * sy] + ([new_ent["start"][2]] if len(new_ent["start"]) > 2 else [])

            if "end" in new_ent:
                rx = new_ent["end"][0] * cos_a - new_ent["end"][1] * sin_a
                ry = new_ent["end"][0] * sin_a + new_ent["end"][1] * cos_a
                new_ent["end"] = [origin[0] + rx * sx, origin[1] + ry * sy] + ([new_ent["end"][2]] if len(new_ent["end"]) > 2 else [])

            if "vertices" in new_ent:
                new_verts = []
                for v in new_ent["vertices"]:
                    rx = v[0] * cos_a - v[1] * sin_a
                    ry = v[0] * sin_a + v[1] * cos_a
                    new_verts.append([origin[0] + rx * sx, origin[1] + ry * sy] + ([v[2]] if len(v) > 2 else []))
                new_ent["vertices"] = new_verts

            if "position" in new_ent:
                rx = new_ent["position"][0] * cos_a - new_ent["position"][1] * sin_a
                ry = new_ent["position"][0] * sin_a + new_ent["position"][1] * cos_a
                new_ent["position"] = [origin[0] + rx * sx, origin[1] + ry * sy] + ([new_ent["position"][2]] if len(new_ent["position"]) > 2 else [])

            if "definition_points" in new_ent:
                new_pts = []
                for p in new_ent["definition_points"]:
                    rx = p[0] * cos_a - p[1] * sin_a
                    ry = p[0] * sin_a + p[1] * cos_a
                    new_pts.append([origin[0] + rx * sx, origin[1] + ry * sy] + ([p[2]] if len(p) > 2 else []))
                new_ent["definition_points"] = new_pts

            if "radius" in new_ent:
                new_ent["radius"] = new_ent["radius"] * max(abs(sx), abs(sy))

            transformed.append(new_ent)

        return transformed

    def _get_units(self) -> str:
        """获取图纸单位"""
        units_map = {
            0: "Unitless", 1: "Inches", 2: "Feet", 3: "Miles",
            4: "Millimeters", 5: "Centimeters", 6: "Meters",
            7: "Kilometers", 8: "Microinches", 9: "Mils",
            10: "Yards", 11: "Angstroms", 12: "Nanometers",
            13: "Microns", 14: "Decimeters", 15: "Decameters",
            16: "Hectometers", 17: "Gigameters", 18: "Astronomical units",
            19: "Light years", 20: "Parsecs"
        }
        return units_map.get(self.doc.units, "Unitless")

    def export_json(self, output_path: str):
        """
        导出解析结果为JSON文件

        Args:
            output_path: 输出文件路径
        """
        if not self.entities:
            logger.warning("没有实体数据可导出")
            return

        result = {
            "version": self.doc.dxfversion if self.doc else "unknown",
            "units": self._get_units() if self.doc else "unknown",
            "entities": self.entities
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"已导出到: {output_path}")

    def visualize(self, output_path: Optional[str] = None):
        """
        可视化DXF文件（使用matplotlib）

        Args:
            output_path: 可选，保存为图片文件
        """
        try:
            import matplotlib.pyplot as plt
            from ezdxf.addons.drawing import RenderContext, Frontend
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

            for layer in self.doc.layers:
                layer.on()

            fig = plt.figure(figsize=(12, 8))
            ax = fig.add_axes([0, 0, 1, 1])
            ctx = RenderContext(self.doc)
            out = MatplotlibBackend(ax)
            Frontend(ctx, out).draw_layout(self.doc.modelspace(), finalize=True)

            if output_path:
                plt.savefig(output_path, dpi=150, bbox_inches='tight')
                logger.info(f"可视化已保存到: {output_path}")
            else:
                plt.show()

            plt.close()

        except ImportError:
            logger.error("需要安装matplotlib才能使用可视化功能")
        except Exception as e:
            logger.error(f"可视化失败: {e}")


# 向后兼容性：保持 DXFParser 作为 CADParser 的别名
class DXFParser(CADParser):
    """
    DXFParser 已重命名为 CADParser。
    此别名保持向后兼容性，请使用 CADParser。
    """
    pass
