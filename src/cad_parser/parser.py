# -*- coding: utf-8 -*-
import ezdxf
import json
import math
import os
import re
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
        self.output_dir = Path(self.config.get("output_dir", "examples/output"))
        self.doc: Optional[ezdxf.document.Drawing] = None
        self.entities: List[Dict] = []
        self._block_cache: Dict[str, List[Dict]] = {}

    def parse(self) -> Dict[str, Any]:
        """
        解析DXF文件

        返回:
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
    
    def _find_dwg2dxf(self):
        """查找 dwg2dxf.exe：优先项目内置，其次配置路径"""
        # 1. 项目内置 tools/bin/dwg2dxf.exe
        builtin = Path(__file__).parent.parent.parent / "tools" / "bin" / "dwg2dxf.exe"
        if builtin.exists():
            logger.info(f"使用项目内置 LibreDWG: {builtin}")
            return builtin

        # 2. 配置路径 (libredwg_path 可为目录或直接指向 exe)
        libredwg_path = self.config.get("libredwg_path", "")
        if libredwg_path:
            p = Path(libredwg_path)
            if p.is_file() and p.suffix.lower() == ".exe":
                logger.info(f"使用配置 LibreDWG: {p}")
                return p
            if p.is_dir():
                exe = p / "dwg2dxf.exe"
                if exe.exists():
                    logger.info(f"使用配置 LibreDWG: {exe}")
                    return exe
                for found in p.rglob("dwg2dxf.exe"):
                    logger.info(f"使用配置 LibreDWG (搜索): {found}")
                    return found

        return None

    def _convert_with_libredwg(self):
        """使用LibreDWG将DWG转换为DXF"""
        import shutil
        import tempfile

        dwg2dxf = self._find_dwg2dxf()
        if not dwg2dxf:
            raise FileNotFoundError(
                "未找到 dwg2dxf.exe。请将 LibreDWG 放入 tools/bin/dwg2dxf.exe "
                "或在 config.yaml 中配置 dxf_parser.libredwg_path"
            )
        
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
            try:
                dim_info["measurement"] = entity.get_measurement()
            except Exception:
                dim_info["measurement"] = 0.0
        try:
            dim_info["text"] = entity.dxf.text
        except Exception:
            pass
        try:
            dim_info["geometry_block"] = entity.dxf.geometry
        except Exception:
            pass
        block_texts = self._extract_dimension_block_texts(entity)
        if block_texts:
            dim_info["block_texts"] = block_texts
            dim_info["rendered_text"] = block_texts[0]["text"]
            dim_info["text_position"] = block_texts[0]["position"]
        elif dim_info.get("text") and dim_info.get("text") != "<>":
            dim_info["rendered_text"] = dim_info["text"]
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

    def _extract_dimension_block_texts(self, entity) -> List[Dict[str, Any]]:
        if self.doc is None:
            return []
        try:
            block_name = entity.dxf.geometry
        except Exception:
            return []
        if not block_name:
            return []
        try:
            block = self.doc.blocks.get(block_name)
        except Exception:
            return []

        texts: List[Dict[str, Any]] = []
        for sub in block:
            if sub.dxftype() not in ("TEXT", "MTEXT"):
                continue
            text = self._extract_text_content(sub)
            if not text:
                continue
            try:
                position = list(sub.dxf.insert)
            except Exception:
                position = [0, 0, 0]
            text_info: Dict[str, Any] = {
                "text": text,
                "position": position,
                "type": sub.dxftype(),
            }
            try:
                text_info["height"] = float(
                    getattr(sub.dxf, "height", getattr(sub.dxf, "char_height", 1.0))
                )
            except Exception:
                pass
            try:
                text_info["rotation"] = float(sub.dxf.rotation)
            except Exception:
                try:
                    direction = sub.dxf.text_direction
                    text_info["rotation"] = math.degrees(math.atan2(direction[1], direction[0]))
                except Exception:
                    pass
            texts.append(text_info)
        return texts

    def _extract_text_content(self, entity) -> str:
        try:
            if entity.dxftype() == "MTEXT" and hasattr(entity, "plain_text"):
                text = entity.plain_text()
            elif entity.dxftype() == "MTEXT":
                text = entity.text
            else:
                text = entity.dxf.text
        except Exception:
            return ""
        return self._clean_text_content(text)

    def _clean_text_content(self, text: str) -> str:
        if not text:
            return ""
        cleaned = str(text).replace("\\P", " ").replace("\n", " ")
        cleaned = self._decode_dxf_text_escapes(cleaned)
        cleaned = re.sub(r"\\[A-Za-z]+[0-9.;,+-]*", "", cleaned)
        cleaned = cleaned.replace("{", "").replace("}", "")
        return " ".join(cleaned.split())

    def _format_dimension_text_for_preview(self, text: str) -> str:
        return self._decode_dxf_text_escapes(str(text)).replace("∅", "φ").replace("⌀", "φ").replace("Ø", "φ").replace("Φ", "φ")

    @staticmethod
    def _decode_dxf_text_escapes(text: str) -> str:
        if not text:
            return ""
        decoded = str(text).replace("%%c", "⌀").replace("%%C", "⌀")
        decoded = re.sub(r"\\U\+2205(?=\d)", "⌀", decoded, flags=re.IGNORECASE)

        def replace_unicode(match: re.Match[str]) -> str:
            codepoint = int(match.group(1), 16)
            if codepoint == 0x2205:
                return "⌀"
            try:
                return chr(codepoint)
            except ValueError:
                return match.group(0)

        return re.sub(r"\\U\+([0-9A-Fa-f]{4})", replace_unicode, decoded)

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
            logger.debug(f"未找到块定义: {block_name}")
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

        参数:
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

        参数:
            output_path: 可选，保存为图片文件。不指定时自动保存到output_dir
        """
        import os as _os
        _os.environ.setdefault('MPLBACKEND', 'Agg')

        try:
            import sys as _sys
            if 'matplotlib' not in _sys.modules:
                import matplotlib as _mpl
                _mpl.use('Agg')
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            from ezdxf.addons.drawing import RenderContext, Frontend
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

            if output_path is None:
                from src.utils.preview_cache import get_preview_cache_path
                output_path = str(get_preview_cache_path(str(self.file_path), str(self.output_dir)))

            for layer in self.doc.layers:
                layer.on()

            fig = plt.figure(figsize=(12, 8))
            ax = fig.add_axes([0, 0, 1, 1])
            ctx = RenderContext(self.doc)
            out = MatplotlibBackend(ax)
            self._normalize_dimension_block_texts_for_preview()
            self._normalize_annotation_colors_for_preview()
            Frontend(ctx, out).draw_layout(self.doc.modelspace(), finalize=True)
            overlay_mode = self.config.get("overlay_dimension_text", "auto")
            if self._is_dimension_overlay_enabled(overlay_mode):
                min_height = None
                if self._is_auto_dimension_overlay(overlay_mode):
                    min_height = self._auto_dimension_overlay_max_height(ax)
                self._draw_dimension_text_overlays(ax, max_text_height=min_height)

            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            logger.info(f"可视化已保存到: {output_path}")
            plt.close('all')

            import gc
            gc.collect()

        except ImportError:
            logger.error("需要安装matplotlib才能使用可视化功能")
        except Exception as e:
            logger.error(f"可视化失败: {e}")

    def _is_dimension_overlay_enabled(self, mode: Any) -> bool:
        if isinstance(mode, str):
            return mode.strip().lower() in ("auto", "smart", "missing", "true", "yes", "on", "1")
        return bool(mode)

    def _is_auto_dimension_overlay(self, mode: Any) -> bool:
        if isinstance(mode, str):
            return mode.strip().lower() in ("", "auto", "smart", "missing")
        return False

    def _auto_dimension_overlay_max_height(self, ax) -> float:
        try:
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            span = max(abs(x1 - x0), abs(y1 - y0), 1.0)
        except Exception:
            span = 1.0
        ratio = float(self.config.get("dimension_text_auto_overlay_ratio", 0.008))
        min_height = float(self.config.get("dimension_text_auto_overlay_min_height", 1.5))
        return max(min_height, span * ratio)

    def _dimension_overlay_fontsize(self, height: float, max_text_height: Optional[float]) -> float:
        base_size = max(6.0, min(12.0, height * 6.0))
        if max_text_height is None:
            return base_size
        target_size = float(self.config.get("dimension_text_auto_overlay_fontsize", 10.0))
        return max(base_size, target_size)

    def _draw_dimension_text_overlays(self, ax, max_text_height: Optional[float] = None) -> None:
        if self.doc is None:
            return
        for dim in self.doc.modelspace().query("DIMENSION"):
            for text_info in self._extract_dimension_block_texts(dim):
                text = self._format_dimension_text_for_preview(text_info.get("text", ""))
                position = text_info.get("position") or [0, 0, 0]
                if not text or len(position) < 2:
                    continue
                height = float(text_info.get("height") or 1.0)
                if max_text_height is not None and height > max_text_height:
                    continue
                fontsize = self._dimension_overlay_fontsize(height, max_text_height)
                ax.text(
                    position[0],
                    position[1],
                    text,
                    fontsize=fontsize,
                    rotation=text_info.get("rotation", 0.0),
                    ha="center",
                    va="center",
                    color="#f2f2f2",
                    fontfamily=["DejaVu Sans", "Microsoft YaHei", "SimHei"],
                    zorder=1000,
                )

    def _normalize_dimension_block_texts_for_preview(self) -> None:
        if self.doc is None:
            return
        for dim in self.doc.modelspace().query("DIMENSION"):
            try:
                block = self.doc.blocks.get(dim.dxf.geometry)
            except Exception:
                continue
            for sub in block:
                if sub.dxftype() not in ("TEXT", "MTEXT"):
                    continue
                try:
                    current = sub.plain_text() if sub.dxftype() == "MTEXT" and hasattr(sub, "plain_text") else sub.dxf.text
                except Exception:
                    continue
                normalized = self._format_dimension_text_for_preview(current)
                if not normalized or normalized == current:
                    continue
                try:
                    sub.dxf.text = normalized
                except Exception:
                    try:
                        sub.text = normalized
                    except Exception:
                        pass

    def _normalize_annotation_colors_for_preview(self) -> None:
        if self.doc is None:
            return
        color = int(self.config.get("preview_annotation_color", 7))
        for layer in self.doc.layers:
            if self._is_annotation_layer(layer.dxf.name):
                try:
                    layer.dxf.color = color
                except Exception:
                    pass

        for entity in self.doc.modelspace():
            if entity.dxftype() in ("TEXT", "MTEXT", "DIMENSION"):
                self._set_entity_preview_color(entity, color)
            if entity.dxftype() != "DIMENSION":
                continue
            try:
                block = self.doc.blocks.get(entity.dxf.geometry)
            except Exception:
                continue
            for sub in block:
                if sub.dxftype() in ("TEXT", "MTEXT", "LINE", "ARC", "SOLID", "POINT"):
                    self._set_entity_preview_color(sub, color)

    @staticmethod
    def _is_annotation_layer(layer_name: str) -> bool:
        normalized = str(layer_name or "").strip().lower()
        return any(token in normalized for token in ("文本", "标注", "dimension", "dim", "text"))

    @staticmethod
    def _set_entity_preview_color(entity, color: int) -> None:
        try:
            entity.dxf.color = color
        except Exception:
            return
        try:
            entity.dxf.discard("true_color")
        except Exception:
            pass


# 向后兼容性：保持 DXFParser 作为 CADParser 的别名
class DXFParser(CADParser):
    """
    DXFParser 已重命名为 CADParser。
    此别名保持向后兼容性，请使用 CADParser。
    """
    pass
