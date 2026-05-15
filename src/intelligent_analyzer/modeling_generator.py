#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility import; actual shim exports live in src.compat."""

from src.compat.intelligent_analyzer import FreeCADInstructionGenerator

__all__ = ["FreeCADInstructionGenerator"]
