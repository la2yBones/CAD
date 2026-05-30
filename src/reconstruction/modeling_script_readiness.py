#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI FreeCAD 脚本执行前的可执行性诊断。"""
from __future__ import annotations

import ast
from typing import Dict, List, Optional, Set

from src.utils.result import Result


class ModelingScriptReadinessChecker:
    """拦截语法安全但高度可能运行失败的 FreeCAD 脚本。"""

    def check(self, script_content: str) -> Result[None]:
        try:
            tree = ast.parse(script_content)
        except SyntaxError as error:
            return Result.fail(f"脚本语法无效: {error}")

        errors: List[str] = []
        assigned_names = self._assigned_names(tree)
        imported_roots = self._imported_roots(tree)

        if "json" in self._referenced_roots(tree) and "json" not in imported_roots:
            errors.append("脚本使用 json 但缺少 import json")

        if "final_shape" not in assigned_names:
            errors.append("缺少 final_shape 赋值，无法确认最终实体")

        if not self._shows_final_shape(tree):
            errors.append('缺少 Part.show(final_shape, "GeneratedModel")')

        if not self._has_recompute_call(tree):
            errors.append("缺少 doc.recompute() 或等价的文档重算调用")

        closed_wire_checks = self._closed_wire_checks(tree)
        for wire_name in self._face_wire_args(tree):
            if wire_name is None:
                errors.append("Part.Face 使用临时 Wire，无法确认轮廓闭合")
            elif wire_name not in closed_wire_checks:
                errors.append(f"Part.Face({wire_name}) 前缺少 {wire_name}.isClosed() 闭合检查")

        for message in self._wire_edge_errors(tree):
            errors.append(message)

        for message in self._arc_argument_errors(tree):
            errors.append(message)

        unique_errors = list(dict.fromkeys(errors))
        if unique_errors:
            return Result.fail("; ".join(unique_errors), warnings=unique_errors)
        return Result.ok(None)

    @classmethod
    def _call_name(cls, func: ast.AST) -> str:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            base = cls._call_name(func.value)
            return f"{base}.{func.attr}" if base else func.attr
        return ""

    @staticmethod
    def _assigned_names(tree: ast.AST) -> Set[str]:
        names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
        return names

    @staticmethod
    def _imported_roots(tree: ast.AST) -> Set[str]:
        roots: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
        return roots

    @staticmethod
    def _referenced_roots(tree: ast.AST) -> Set[str]:
        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }

    @classmethod
    def _shows_final_shape(cls, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if cls._call_name(node.func) != "Part.show":
                continue
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "final_shape":
                return True
        return False

    @classmethod
    def _has_recompute_call(cls, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and cls._call_name(node.func).endswith(".recompute"):
                return True
        return False

    @classmethod
    def _closed_wire_checks(cls, tree: ast.AST) -> Set[str]:
        checked: Set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if cls._call_name(node.func).endswith(".isClosed"):
                owner = node.func.value if isinstance(node.func, ast.Attribute) else None
                if isinstance(owner, ast.Name):
                    checked.add(owner.id)
        return checked

    @classmethod
    def _face_wire_args(cls, tree: ast.AST) -> List[Optional[str]]:
        wire_args: List[Optional[str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if cls._call_name(node.func) != "Part.Face" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name):
                wire_args.append(arg.id)
            elif isinstance(arg, ast.Call) and cls._call_name(arg.func) == "Part.Wire":
                wire_args.append(None)
        return wire_args

    @classmethod
    def _wire_edge_errors(cls, tree: ast.AST) -> List[str]:
        errors: List[str] = []
        list_assignments = cls._list_assignments(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or cls._call_name(node.func) != "Part.Wire":
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Name):
                first_arg = list_assignments.get(first_arg.id, first_arg)
            if not isinstance(first_arg, (ast.List, ast.Tuple)):
                continue
            for item in first_arg.elts:
                if cls._is_raw_edge_constructor(item):
                    errors.append("Part.Wire 中的 LineSegment/ArcOfCircle 必须先转换为 Edge/Shape")
        return errors

    @staticmethod
    def _list_assignments(tree: ast.AST) -> Dict[str, ast.AST]:
        assignments: Dict[str, ast.AST] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        return assignments

    @classmethod
    def _is_raw_edge_constructor(cls, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        call_name = cls._call_name(node.func)
        if call_name in {"Part.LineSegment", "Part.ArcOfCircle"}:
            return True
        if call_name.endswith(".toShape"):
            return False
        if call_name == "as_edge":
            return False
        return False

    @classmethod
    def _arc_argument_errors(cls, tree: ast.AST) -> List[str]:
        errors: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and cls._call_name(node.func) == "Part.ArcOfCircle":
                if len(node.args) != 3:
                    errors.append("Part.ArcOfCircle must use exactly 3 positional arguments")
        return errors
