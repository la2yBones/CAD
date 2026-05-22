#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建模约束：共享 FreeCAD 生成提示、特征守门和脚本执行前校验。"""
from __future__ import annotations

import ast
import json
from typing import Any, Dict, Optional

from src.utils.result import Result


class ModelingConstraints:
    """建模指令生成和 AI 脚本执行共同使用的约束 module。"""

    PROMPT_SECTION = """【允许 API 白名单：显式几何构造 API】
仅允许使用以下导入、对象、方法和语法。原则是：允许明确构造几何，不允许自动选择拓扑。

1. 基础导入与文档对象
- import FreeCAD
- import Part
- FreeCAD.Vector
- FreeCAD.newDocument
- FreeCAD.ActiveDocument

2. 基础原生几何体
- Part.makeBox
- Part.makeCylinder
- Part.makeCone
限制：仅生成标准棱柱、圆柱、圆锥，不允许使用带内置圆角、倒角或自动修复参数的重载。

3. 低阶几何图元
- Part.LineSegment
- Part.Circle
- Part.ArcOfCircle
- Part.Wire
- Part.Face
说明：这是手动画直线、圆、圆弧、R角轮廓、回转承面轮廓和闭合截面的核心积木。
ArcOfCircle 固定模板：只能使用 3 个位置参数，例如 `arc_edge = Part.ArcOfCircle(Part.Circle(center, FreeCAD.Vector(0, 0, 1), radius), start_angle, end_angle).toShape()`，或使用三点式 `Part.ArcOfCircle(p1, p2, p3).toShape()`。不要写 `Part.ArcOfCircle(center, radius, start_angle, end_angle)`。

4. 形体生成与变换
- Shape.extrude
- Shape.revolve
说明：使用 Shape.revolve 替代自动圆角/球面/倒角函数，生成轴对称圆弧面或回转切除体。
圆角要求：若 modeling_task_payload.dimensions.allowed_dimensions 中存在 role=radius 的圆角/圆弧标注，尤其是 R=4x1.5 这类 repeat_count+radius_value 标注，不得因为 makeFillet 被禁用就直接跳过。应优先使用图纸中 ARC 摘要、Part.ArcOfCircle、Part.Wire、Part.Face、Shape.revolve 或显式轮廓构造来表达该圆角；只有缺少半径、位置和构造方向时，才允许记录为 skipped_features。
重复孔要求：若 allowed_dimensions 中存在 repeated_diameter 或 repeated_thread 标注，例如 3xφ5、3×Φ5、3-φ5、3-M5，repeat_count 表示孔数量，diameter_value/thread_value 表示孔径或螺纹规格值；不得把前面的数量当作孔径，也不得只生成一个孔后忽略数量。

5. 基础布尔
- Shape.fuse
- Shape.cut
限制：仅用于合并实体和手动差集切割；单个步骤中连续 fuse/cut 不得超过 2 次。

6. 文档操作与展示
- Part.show
- doc.recompute
- doc.saveAs
限制：doc.saveAs 只能保存到执行器提供的 output_path 或输出目录内。

7. 向量计算
- Vector.x / Vector.y / Vector.z
- Vector.add / Vector.sub / Vector.multiply
- Vector.normalize
限制：normalize 前必须避免零向量；优先构造新的 FreeCAD.Vector，不要依赖复杂隐式变换。

8. 基础数学库
- import math
- math.radians / math.degrees
- math.cos / math.sin / math.tan
说明：仅用于正多边形、圆弧角度、倒角和回转轮廓计算。

9. 基础数据构造语法
- for 循环
- range
- list / append
禁止使用 while、动态执行、反射、文件相关语法或任何系统访问。

【当前强禁用黑名单：自动拓扑、高级工作台、系统能力】
以下 API、模块和能力严禁使用，无例外：

1. 自动圆角、倒角和拓扑自动化
- Part.makeFillet
- Part.makeChamfer
- Shape.makeFillet
- Shape.makeChamfer
- Part.ShapeSplit
- Part.BooleanOperations
- BOPTools 全系

2. 工作台与高级模块
- Sketcher 全系
- Draft 全系
- PartDesign 全系
- Mesh 全系
- Assembly 全系
原因：这些模块依赖交互式选边、特征树、隐式拓扑或工作台状态，LLM 无法稳定控制。

3. 拓扑修复与复杂派生操作
- 拓扑修复、缝合、补面、简化、自适应细分等所有高级拓扑 API
- common / section / split / thickness / shell / offset
原因：这些操作容易产生不可预测拓扑或坏形体，且错误难以从脚本文本中审查。

4. 系统与安全高危能力
- subprocess
- os
- sys
- eval
- exec
- 文件删除、重命名、移动
- 网络请求
- shell 调用"""

    ALLOWED_IMPORTS = {"FreeCAD", "Part", "math", "json"}
    FORBIDDEN_IMPORTS = {
        "os",
        "sys",
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "http",
        "pathlib",
        "shutil",
        "tempfile",
        "importlib",
    }
    FORBIDDEN_CALL_NAMES = {
        "eval",
        "exec",
        "open",
        "compile",
        "input",
        "__import__",
    }
    FORBIDDEN_ATTRS = {
        "makeFillet",
        "makeChamfer",
        "ShapeSplit",
        "BooleanOperations",
        "common",
        "section",
        "split",
        "thickness",
        "shell",
        "offset",
    }
    FORBIDDEN_TEXT_MARKERS = (
        "BOPTools",
        "Sketcher",
        "Draft",
        "PartDesign",
        "Mesh",
        "Assembly",
        "os.system",
        "subprocess.",
        "socket.",
        "requests.",
        "urllib.",
        "shutil.",
        "Path(",
        ".unlink(",
        ".rename(",
        ".replace(",
        "while ",
    )

    def prompt_section(self) -> str:
        return self.PROMPT_SECTION

    def retry_reason(
        self,
        result: Dict[str, Any],
        reconstruction_context: Optional[Dict[str, Any]],
        part_semantics: Optional[Dict[str, Any]],
    ) -> str:
        if self._needs_chamfer_retry(result, reconstruction_context, part_semantics):
            return "chamfer"
        if self._needs_radius_surface_retry(result, reconstruction_context, part_semantics):
            return "radius_surface"
        return ""

    def retry_prompt(self, prompt: str, retry_reason: str) -> str:
        extra = ""
        if retry_reason == "radius_surface":
            extra = (
                "- 若存在 R15 / radius 且语义说明它是螺栓头部圆弧面/承面，必须用 Part.ArcOfCircle + Part.Wire + Part.Face + Shape.revolve() 绕螺栓轴线生成回转圆弧面或回转切除体。\n"
                "- 不得在 analysis_summary、modeling_strategy、warnings 或 runtime_warnings 中写“R15未实现/圆角未实现/跳过/忽略”。\n"
                "- 该 R15 是螺栓头部的球面/承面，不是普通 edge fillet；不要使用被禁用的 makeFillet/PartDesign。\n"
            )
        elif retry_reason == "chamfer":
            extra = (
                "- 若存在 1x45° / chamfer，必须在 freecad_script 中实现可见外角斜面。\n"
                "- 不得在 analysis_summary、modeling_strategy、warnings 或 runtime_warnings 中写“倒角未实现/跳过/忽略”。\n"
                "- 可用 Part.makeCone 表达圆柱端部 45° 截锥倒角；可用 Part.Wire/Part.Face/extrude/cut 表达六角头外角切除。\n"
                "- R15 是圆角/圆弧面，不是倒角；如果无法精确圆角，可单独处理，但不能因此跳过 1x45° 倒角。\n"
            )
        return (
            prompt
            + "\n\n【必须修正】\n"
            + "上一版建模指令跳过了已经识别到并裁决过的几何特征。请重新生成完整 JSON：\n"
            + extra
        )

    def validate_script(self, script_content: str) -> Result[None]:
        errors = []
        try:
            tree = ast.parse(script_content)
        except SyntaxError as error:
            return Result.fail(f"脚本语法无效: {error}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name in self.FORBIDDEN_IMPORTS or root_name not in self.ALLOWED_IMPORTS:
                        errors.append(f"禁止导入模块: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = (node.module or "").split(".", 1)[0]
                errors.append(f"禁止 from-import: {node.module or ''}")
                if module_name in self.FORBIDDEN_IMPORTS:
                    errors.append(f"禁止导入模块: {node.module}")
            elif isinstance(node, ast.While):
                errors.append("禁止使用 while 循环")
            elif isinstance(node, ast.Call):
                call_name = self._call_name(node.func)
                leaf_name = call_name.rsplit(".", 1)[-1]
                if call_name in self.FORBIDDEN_CALL_NAMES or leaf_name in self.FORBIDDEN_CALL_NAMES:
                    errors.append(f"禁止动态执行或系统调用: {call_name}")
                if leaf_name in self.FORBIDDEN_ATTRS:
                    errors.append(f"禁止使用 FreeCAD 拓扑自动化或复杂派生 API: {call_name}")
                api_error = self._validate_geometry_call(call_name, node)
                if api_error:
                    errors.append(api_error)

        for marker in self.FORBIDDEN_TEXT_MARKERS:
            if marker in script_content:
                errors.append(f"脚本文本包含禁用能力: {marker}")

        unique_errors = list(dict.fromkeys(errors))
        if unique_errors:
            return Result.fail("; ".join(unique_errors), warnings=unique_errors)
        return Result.ok(None)

    def _needs_chamfer_retry(
        self,
        result: Dict[str, Any],
        reconstruction_context: Optional[Dict[str, Any]],
        part_semantics: Optional[Dict[str, Any]],
    ) -> bool:
        if not self._requires_chamfer(reconstruction_context, part_semantics):
            return False
        combined = self._combined_result_text(result)
        return "倒角" in combined and any(marker in combined for marker in ("未实现", "跳过", "忽略"))

    def _needs_radius_surface_retry(
        self,
        result: Dict[str, Any],
        reconstruction_context: Optional[Dict[str, Any]],
        part_semantics: Optional[Dict[str, Any]],
    ) -> bool:
        if not self._requires_radius_surface(reconstruction_context, part_semantics):
            return False
        combined = self._combined_result_text(result)
        mentions_radius = any(marker in combined for marker in ("R15", "圆角", "圆弧面", "承面"))
        skips_radius = any(marker in combined for marker in ("未实现", "跳过", "忽略"))
        return mentions_radius and skips_radius

    def _requires_chamfer(
        self,
        reconstruction_context: Optional[Dict[str, Any]],
        part_semantics: Optional[Dict[str, Any]],
    ) -> bool:
        policy_plan = (reconstruction_context or {}).get("semantic_policy", {}).get("dimension_plan", {})
        for item in policy_plan.get("allowed_dimensions", []) or []:
            if item.get("role") == "chamfer":
                return True
        semantic_text = json.dumps(part_semantics or {}, ensure_ascii=False, default=str)
        return "chamfer" in semantic_text.lower() or "倒角" in semantic_text

    def _requires_radius_surface(
        self,
        reconstruction_context: Optional[Dict[str, Any]],
        part_semantics: Optional[Dict[str, Any]],
    ) -> bool:
        policy_plan = (reconstruction_context or {}).get("semantic_policy", {}).get("dimension_plan", {})
        for item in policy_plan.get("allowed_dimensions", []) or []:
            if item.get("role") == "radius":
                return True
        semantic_text = json.dumps(part_semantics or {}, ensure_ascii=False, default=str)
        return "R15" in semantic_text or "圆弧面" in semantic_text or "承面" in semantic_text

    @staticmethod
    def _combined_result_text(result: Dict[str, Any]) -> str:
        return "\n".join([
            str(result.get("analysis_summary") or ""),
            str(result.get("modeling_strategy") or ""),
            str(result.get("freecad_script") or ""),
            "\n".join(str(item) for item in result.get("warnings", []) or []),
        ])

    @classmethod
    def _call_name(cls, func: ast.AST) -> str:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            base = cls._call_name(func.value)
            return f"{base}.{func.attr}" if base else func.attr
        return ""

    @staticmethod
    def _validate_geometry_call(call_name: str, node: ast.Call) -> str:
        leaf_name = call_name.rsplit(".", 1)[-1]
        if leaf_name == "ArcOfCircle" and len(node.args) != 3:
            return "Part.ArcOfCircle must use exactly 3 positional arguments"
        if leaf_name == "LineSegment" and len(node.args) != 2:
            return "Part.LineSegment must use exactly 2 positional arguments"
        if leaf_name == "Circle" and len(node.args) < 1:
            return "Part.Circle must include a center or construction geometry"
        return ""


DEFAULT_MODELING_CONSTRAINTS = ModelingConstraints()
