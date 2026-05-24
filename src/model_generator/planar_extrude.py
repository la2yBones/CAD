#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Planar extrusion modeling adapter.

The implementation still reuses the legacy basic modeler, but new internal code
should depend on the planar-extrude name instead of the historical FreeCADModeler
export.
"""

from src.legacy.basic_modeling import FreeCADModeler


class PlanarExtrudeModeler(FreeCADModeler):
    """Adapter name for the planar extrusion path."""


__all__ = ["PlanarExtrudeModeler"]
