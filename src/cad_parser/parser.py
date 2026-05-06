import ezdxf
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class CADParser:
    """CAD文件解析器，支持DXF和DWG格式，提取几何实体并转换为标准化格式"""

    def __init__(self, file_path: str, config: Optional[Dict] = None):
        self.file_path = Path(file_path)
        self.config = config or {}
        self.doc: Optional[ezdxf.document.Drawing] = None
        self.entities: List[Dict] = []

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
        """将DWG转换为DXF，支持ODA或LibreDWG"""
        converter_type = self.config.get("dwg_converter", "libredwg").lower()
        
        try:
            if converter_type == "libredwg":
                self._convert_with_libredwg()
            else:
                self._convert_with_oda()
        except Exception as e:
            logger.error(f"DWG转换失败: {e}")
            raise
    
    def _convert_with_libredwg(self):
        """使用LibreDWG将DWG转换为DXF"""
        libredwg_path = Path(self.config.get("libredwg_path", ""))
        
        if not libredwg_path.exists():
            raise FileNotFoundError(f"LibreDWG路径不存在: {libredwg_path}")
        
        # 查找 dwg2dxf 可执行文件
        dwg2dxf = libredwg_path / "dwg2dxf.exe"
        if not dwg2dxf.exists():
            # 尝试在子目录中查找
            for p in libredwg_path.rglob("dwg2dxf.exe"):
                dwg2dxf = p
                break
        
        if not dwg2dxf.exists():
            raise FileNotFoundError(f"未找到 dwg2dxf.exe 在: {libredwg_path}")
        
        dxf_path = self.file_path.with_suffix(".dxf")
        
        # 构建命令
        cmd = [
            str(dwg2dxf),
            "-o", str(dxf_path),
            str(self.file_path)
        ]
        
        logger.info(f"执行LibreDWG转换: {' '.join(cmd)}")
        
        # 执行转换
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode != 0:
            logger.error(f"LibreDWG转换错误 (退出码: {result.returncode})")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            raise RuntimeError(f"LibreDWG转换失败: {result.stderr}")
        
        if not dxf_path.exists():
            raise FileNotFoundError(f"转换后的DXF文件未生成: {dxf_path}")
        
        self.file_path = dxf_path
        logger.info(f"LibreDWG转换成功: {dxf_path}")
    
    def _convert_with_oda(self):
        """使用ODA File Converter将DWG转换为DXF"""
        try:
            from ezdxf.addons import odafc
            dxf_path = self.file_path.with_suffix(".dxf")
            odafc.convert(str(self.file_path), str(dxf_path))
            self.file_path = dxf_path
            logger.info(f"ODA转换成功: {dxf_path}")
        except Exception as e:
            logger.error(f"ODA转换失败: {e}")
            raise

    def _extract_entities(self):
        """从模型空间提取几何实体"""
        msp = self.doc.modelspace()
        supported_types = self.config.get("extract_entities", [
            "LINE", "CIRCLE", "ARC", "LWPOLYLINE", "TEXT", "MTEXT"
        ])

        for entity in msp:
            entity_type = entity.dxftype()
            if entity_type in supported_types:
                parsed = self._parse_entity(entity)
                if parsed:
                    self.entities.append(parsed)

    def _parse_entity(self, entity) -> Optional[Dict]:
        """解析单个DXF实体"""
        base_info = {
            "type": entity.dxftype(),
            "layer": entity.dxf.layer,
            "color": entity.dxf.color,
        }

        try:
            if entity.dxftype() == "LINE":
                base_info.update({
                    "start": list(entity.dxf.start),
                    "end": list(entity.dxf.end)
                })
            elif entity.dxftype() == "CIRCLE":
                base_info.update({
                    "center": list(entity.dxf.center),
                    "radius": entity.dxf.radius
                })
            elif entity.dxftype() == "ARC":
                base_info.update({
                    "center": list(entity.dxf.center),
                    "radius": entity.dxf.radius,
                    "start_angle": entity.dxf.start_angle,
                    "end_angle": entity.dxf.end_angle
                })
            elif entity.dxftype() == "LWPOLYLINE":
                base_info.update({
                    "vertices": [list(v) for v in entity.get_points("xy")],
                    "closed": entity.closed
                })
            elif entity.dxftype() == "TEXT":
                base_info.update({
                    "text": entity.dxf.text,
                    "position": list(entity.dxf.insert),
                    "height": entity.dxf.height
                })
            elif entity.dxftype() == "MTEXT":
                base_info.update({
                    "text": entity.text,
                    "position": list(entity.dxf.insert)
                })
            else:
                return None

            return base_info

        except Exception as e:
            logger.warning(f"解析实体失败: {entity.dxftype()}, 错误: {e}")
            return None

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
