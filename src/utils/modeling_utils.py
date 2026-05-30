#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建模相关公共工具函数。"""

import re
from typing import Any, Dict, List


def looks_like_english_sentence(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    letters = len(re.findall(r"[A-Za-z]", text))
    return letters >= 12


def normalize_feature_records(value: Any) -> List[Dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return [{"name": str(value), "reason": "unspecified"}]
    records: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            records.append(item)
        else:
            records.append({"name": str(item), "reason": "unspecified"})
    return records
