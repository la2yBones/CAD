"""
建模指令生成器

将视图分析结果与尺寸提取结果融合，生成 FreeCAD 可执行的建模脚本。
"""

from typing import Any, Dict, List, Optional

from ..utils.result import Result


class ModelingGenerator:
    """基于分析结果生成 FreeCAD 建模脚本。"""

    def generate(
        self,
        views: List[Dict[str, Any]],
        dimensions: Dict[str, Any],
        extrude_height: float = 10.0,
    ) -> Result[Dict[str, Any]]:
        """
        生成建模指令和 FreeCAD 脚本。

        Args:
            views: 视图分析结果列表
            dimensions: 尺寸提取结果
            extrude_height: 默认拉伸高度（毫米）

        Returns:
            Result[Dict]: Ok 时包含 modeling_instructions 和 freecad_script，
                          生成失败时返回 Err。
        """
        try:
            instructions = self._build_instructions(views, dimensions, extrude_height)
            script = self._generate_script(instructions, extrude_height)

            return Result.Ok({
                "modeling_instructions": instructions,
                "freecad_script": script,
                "extrude_height": extrude_height,
            })
        except Exception as e:
            return Result.Err(f"建模指令生成失败: {e}")

    def _build_instructions(
        self,
        views: List[Dict[str, Any]],
        dimensions: Dict[str, Any],
        extrude_height: float,
    ) -> Dict[str, Any]:
        """构建建模指令字典。"""
        instructions: Dict[str, Any] = {
            "views": [],
            "dimensions": {},
            "operations": [],
            "extrude_height": extrude_height,
        }

        for view in (views or []):
            view_info = {
                "label": view.get("label", "unknown"),
                "boundary": view.get("boundary"),
                "entities": view.get("entities", []),
                "entity_count": view.get("entity_count", 0),
            }
            instructions["views"].append(view_info)

        if dimensions:
            instructions["dimensions"] = {
                "width": dimensions.get("width"),
                "height": dimensions.get("height"),
                "depth": dimensions.get("depth"),
                "unit": dimensions.get("unit", "mm"),
            }

            width = dimensions.get("width")
            height = dimensions.get("height")
            depth = dimensions.get("depth")

            if width and height:
                instructions["operations"].append({
                    "type": "extrude",
                    "profile": "rectangle",
                    "width": width,
                    "height": height if depth is None else depth,
                    "extrude_distance": height if depth is not None else extrude_height,
                    "description": f"创建 {width}x{height}mm 矩形并拉伸",
                })
            else:
                instructions["operations"].append({
                    "type": "extrude",
                    "profile": "views",
                    "extrude_distance": extrude_height,
                    "description": f"基于识别的 {len(views)} 个视图进行拉伸",
                })

        return instructions

    def _generate_script(
        self,
        instructions: Dict[str, Any],
        extrude_height: float,
    ) -> str:
        """生成 FreeCAD Python 脚本。"""
        lines: List[str] = [
            "import FreeCAD as App",
            "import Part",
            "import Draft",
            "",
            "doc = App.newDocument('CAD_Model')",
            "",
        ]

        ops = instructions.get("operations", [])
        has_specific_ops = False

        for op in ops:
            if op.get("type") == "extrude" and op.get("profile") == "rectangle":
                width = op.get("width", 100)
                depth = op.get("height", 100)
                distance = op.get("extrude_distance", extrude_height)
                lines.extend([
                    f"rect = Draft.make_rectangle({width}, {depth})",
                    "doc.recompute()",
                    f"face = App.ActiveDocument.getObject('Rectangle').Shape.Faces[0]",
                    f"solid = face.extrude(App.Vector(0, 0, {distance}))",
                    "Part.show(solid)",
                    "doc.recompute()",
                    "",
                ])
                has_specific_ops = True

        if not has_specific_ops:
            views = instructions.get("views", [])
            for view in views:
                entities = view.get("entities", [])
                lines.append(f"# 视图: {view.get('label', 'unknown')} ({len(entities)} 个实体)")
                for entity in entities:
                    lines.append(self._entity_to_script(entity, extrude_height))
                lines.append("")

        lines.extend([
            "doc.recompute()",
            "# 生成完毕",
        ])

        return "\n".join(lines)

    def _entity_to_script(self, entity: Dict[str, Any], extrude_height: float) -> str:
        """将单个实体转换为 FreeCAD 脚本片段。"""
        entity_type = entity.get("type", "")
        layer = entity.get("layer", "0")

        if entity_type == "LINE":
            start = entity.get("start", (0, 0))
            end = entity.get("end", (0, 0))
            return (
                f"# {layer} 层 - 直线: {start} -> {end}\n"
                f"l = Draft.make_line(App.Vector({start[0]}, {start[1]}, 0), "
                f"App.Vector({end[0]}, {end[1]}, 0))"
            )
        elif entity_type == "CIRCLE":
            center = entity.get("center", (0, 0))
            radius = entity.get("radius", 10)
            return (
                f"# {layer} 层 - 圆: 圆心{center}, 半径{radius}\n"
                f"c = Draft.make_circle({radius}, "
                f"placement=App.Placement(App.Vector({center[0]}, {center[1]}, 0), App.Rotation()))"
            )
        elif entity_type == "LWPOLYLINE":
            return f"# {layer} 层 - 多段线\n"
        elif entity_type == "TEXT" or entity_type == "MTEXT":
            return f"# {layer} 层 - 文字标注\n"
        else:
            return f"# {layer} 层 - 未处理的实体类型: {entity_type}\n"
