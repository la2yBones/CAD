# -*- coding: utf-8 -*-
"""基于 CAD 图纸的 3D 建模系统。"""

from importlib import import_module
from typing import Any

__version__ = "1.0.0"

_EXPORTS = {
    "CADParser": ("src.cad_parser", "CADParser"),
    "DXFParser": ("src.cad_parser", "DXFParser"),
    "GeometryAnalyzer": ("src.geometry_analyzer", "GeometryAnalyzer"),
    "IntelligentEngineeringAnalyzer": (
        "src.intelligent_analyzer",
        "IntelligentEngineeringAnalyzer",
    ),
    "PlanarExtrudeModeler": ("src.model_generator", "PlanarExtrudeModeler"),
    "FreeCADModeler": ("src.model_generator", "FreeCADModeler"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module 'src' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
