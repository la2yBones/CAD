"""
DXF/DWG 解析器

支持 DXF（直接 ezdxf 解析）和 DWG（通过 LibreDWG 转换为 DXF 后解析）。
提取图层、实体、嵌套图块等工程图元信息。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import tempfile

import ezdxf

from ..utils.config import load_config
from ..utils.result import Result


class CADParser:
    """CAD 图纸解析器，支持 DXF 和 DWG 格式。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config: Dict[str, Any] = config or load_config()

    def parse(self, file_path: str) -> Result[Dict[str, Any]]:
        """
        解析 CAD 文件，返回工程图元数据。

        Args:
            file_path: DXF 或 DWG 文件路径

        Returns:
            Result[Dict]: Ok 时包含 layers/entities/blocks 等键，
                          解析失败时返回 Err。
        """
        path = Path(file_path)
        if not path.exists():
            return Result.Err(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()

        if suffix == ".dwg":
            return self._parse_dwg(path)
        elif suffix == ".dxf":
            return self._parse_dxf(path)
        else:
            return Result.Err(f"不支持的文件格式: {suffix}，仅支持 .dxf 和 .dwg")

    def _parse_dxf(self, path: Path) -> Result[Dict[str, Any]]:
        """直接解析 DXF 文件。"""
        try:
            doc = ezdxf.readfile(str(path))
            msp = doc.modelspace()

            entities = []
            for entity in msp:
                entity_data = self._extract_entity(entity)
                if entity_data:
                    entities.append(entity_data)

            layers = self._extract_layers(doc)
            blocks = self._extract_blocks(doc)

            return Result.Ok({
                "file_path": str(path),
                "file_type": "dxf",
                "layers": layers,
                "entities": entities,
                "blocks": blocks,
                "entity_count": len(entities),
                "layer_count": len(layers),
                "block_count": len(blocks),
            })
        except Exception as e:
            return Result.Err(f"DXF 解析失败: {e}")

    def _parse_dwg(self, path: Path) -> Result[Dict[str, Any]]:
        """通过 LibreDWG 将 DWG 转换为 DXF 后解析。"""
        libredwg_path = self._config.get("dxf_parser", {}).get("libredwg_path", "")
        if not libredwg_path:
            return Result.Err(
                "未配置 LibreDWG 路径。请在 config/config.yaml 中设置 dxf_parser.libredwg_path。"
            )

        dwg2dxf = Path(libredwg_path) / "dwg2dxf.exe"
        if not dwg2dxf.exists():
            return Result.Err(f"LibreDWG 工具未找到: {dwg2dxf}")

        try:
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            proc = subprocess.run(
                [str(dwg2dxf), str(path), "-o", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )

            if proc.returncode != 0:
                tmp_path.unlink(missing_ok=True)
                return Result.Err(f"DWG 转换 DXF 失败: {proc.stderr.strip()}")

            result = self._parse_dxf(tmp_path)
            tmp_path.unlink(missing_ok=True)
            return result

        except subprocess.TimeoutExpired:
            return Result.Err("DWG 转换 DXF 超时（60秒）")
        except Exception as e:
            return Result.Err(f"DWG 解析失败: {e}")

    def _extract_entity(self, entity) -> Optional[Dict[str, Any]]:
        """提取单个实体的属性。"""
        try:
            dxftype = entity.dxftype()

            data: Dict[str, Any] = {
                "type": dxftype,
                "handle": entity.dxf.handle,
                "layer": entity.dxf.layer,
            }

            if dxftype in ("LINE", "CIRCLE", "ARC", "ELLIPSE"):
                self._add_geometry(data, entity)
            elif dxftype == "LWPOLYLINE":
                self._add_polyline(data, entity)
            elif dxftype == "TEXT":
                data["text"] = entity.dxf.text
            elif dxftype == "MTEXT":
                data["text"] = entity.text
                data["plain_text"] = entity.plain_text() if hasattr(entity, 'plain_text') else entity.text
            elif dxftype == "INSERT":
                data["block_name"] = entity.dxf.name

            return data
        except Exception:
            return None

    def _add_geometry(self, data: Dict[str, Any], entity) -> None:
        """添加几何信息（LINE/CIRCLE/ARC/ELLIPSE）。"""
        if data["type"] == "LINE":
            data["start"] = (entity.dxf.start.x, entity.dxf.start.y)
            data["end"] = (entity.dxf.end.x, entity.dxf.end.y)
        elif data["type"] == "CIRCLE":
            data["center"] = (entity.dxf.center.x, entity.dxf.center.y)
            data["radius"] = entity.dxf.radius
        elif data["type"] == "ARC":
            data["center"] = (entity.dxf.center.x, entity.dxf.center.y)
            data["radius"] = entity.dxf.radius
        elif data["type"] == "ELLIPSE":
            data["center"] = (entity.dxf.center.x, entity.dxf.center.y)

    def _add_polyline(self, data: Dict[str, Any], entity) -> None:
        """添加多段线的顶点信息。"""
        points = []
        with entity.points() as pts:
            for p in pts:
                points.append((p[0], p[1]))
        data["points"] = points
        data["is_closed"] = entity.closed

    def _extract_layers(self, doc) -> List[Dict[str, Any]]:
        """提取所有图层信息。"""
        layers = []
        for layer in doc.layers:
            layers.append({
                "name": layer.dxf.name,
                "color": layer.dxf.color,
                "linetype": layer.dxf.linetype,
                "is_frozen": layer.is_frozen(),
                "is_locked": layer.is_locked(),
            })
        return layers

    def _extract_blocks(self, doc) -> List[Dict[str, Any]]:
        """提取所有图块定义。"""
        blocks = []
        for block in doc.blocks:
            if block.name.startswith("*"):
                continue
            entity_count = len(list(block))
            blocks.append({
                "name": block.name,
                "entity_count": entity_count,
            })
        return blocks
