#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追问问题的纯工具函数，无外部依赖，避免循环导入。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def choice_option(label: str, value: Any) -> Dict[str, str]:
    return {"label": str(label), "value": str(value)}


def clarification_question(
    *,
    question_id: str,
    text: str,
    kind: str,
    options: Optional[List[Dict[str, Any]]] = None,
    reason: str = "",
    example: str = "",
    required: bool = False,
) -> Dict[str, Any]:
    question: Dict[str, Any] = {
        "id": question_id,
        "text": text,
        "kind": kind,
        "options": options or [],
    }
    if reason:
        question["reason"] = reason
    if example:
        question["example"] = example
    if required:
        question["required"] = True
    return question
