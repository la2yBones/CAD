# 基于CAD图纸的3D建模系统
# 毕业设计项目

__version__ = "0.2.0"
__author__ = "Your Name"

from .cad_parser import CADParser, DXFParser
from .geometry_analyzer import GeometryAnalyzer
from .model_generator import FreeCADModeler

__all__ = ["CADParser", "DXFParser", "GeometryAnalyzer", "FreeCADModeler"]
