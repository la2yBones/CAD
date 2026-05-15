#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility import; actual shim exports live in src.compat."""

from src.compat.intelligent_analyzer import PART_SEMANTICS_SCHEMA, PartSemanticsValidator

__all__ = ["PART_SEMANTICS_SCHEMA", "PartSemanticsValidator"]
