#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview image cache path helpers."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional


DEFAULT_PREVIEW_CACHE_DIR = Path(".cache") / "previews"


def get_preview_cache_dir(configured_dir: Optional[str] = None) -> Path:
    """Return the shared preview cache directory."""
    raw_dir = configured_dir or os.getenv("CAD_PREVIEW_CACHE_DIR")
    cache_dir = Path(raw_dir) if raw_dir else DEFAULT_PREVIEW_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_preview_cache_path(file_path: str, cache_dir: Optional[str] = None) -> Path:
    """Build a stable preview image path for one CAD file."""
    path = Path(file_path)
    try:
        resolved = path.resolve()
        stat = resolved.stat()
        key_source = f"{resolved}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        resolved = path
        key_source = str(path)

    digest = hashlib.sha1(key_source.encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_stem = path.stem.replace("/", "_").replace("\\", "_")
    return get_preview_cache_dir(cache_dir) / f"{safe_stem}_{digest}_preview.png"
