# -*- coding: utf-8 -*-
# 基于CAD图纸的3D建模系统
# 毕业设计项目

__version__ = "0.3.0"
__author__ = "Your Name"

from .cad_parser import CADParser, DXFParser
from .geometry_analyzer import GeometryAnalyzer  # deprecated, 请使用 IntelligentEngineeringAnalyzer
from .model_generator import FreeCADModeler
from .intelligent_analyzer import IntelligentEngineeringAnalyzer

__all__ = [
    "CADParser",
    "DXFParser",
    "GeometryAnalyzer",             # deprecated
    "IntelligentEngineeringAnalyzer",
    "FreeCADModeler"
]
