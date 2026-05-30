# -*- coding: utf-8 -*-
import sys
import os
import json
import csv
import threading
import time
import queue
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable

os.environ.setdefault('MPLBACKEND', 'Agg')

try:
    import matplotlib
    matplotlib.use('Agg')
except Exception:
    pass

import matplotlib.pyplot as plt
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'KaiTi', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging

from src.utils.deepseek_gui_config import (
    apply_gui_runtime_overrides,
    format_llm_token_status,
    normalize_gui_reasoning_effort as _gui_reasoning_effort,
)
from src.reconstruction.clarification import (
    build_candidate_clarification_summary,
    clarification_option_label,
    clarification_option_value,
    is_candidate_clarification_question,
)
from src.batch_processor.pending_view_model import (
    build_pending_item_detail,
    pending_recovery_summary,
    pending_recovery_type,
)

logger = logging.getLogger(__name__)


def _read_field(source: Any, key: str, default: Any = None) -> Any:
    """兼容读取 dict 与类型化结果对象的字段。"""
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def format_stage_supervision_message(result) -> tuple[str, str]:
    """把阶段监督动作转换为 GUI 状态和用户可见说明。"""
    action = getattr(result, "stage_stop_action", "") or ""
    stage = getattr(result, "stage_stop_stage", "") or ""
    try:
        from src.utils.stage_confirmation import stage_display_name

        stage_name = stage_display_name(stage) if stage else "当前"
    except Exception:
        stage_name = stage or "当前"

    if action == "self_correct":
        return "已请求模型自纠", f"已请求 {stage_name} 阶段进入模型自纠"
    if action == "retry_stage":
        return "已请求重跑阶段", f"已请求重跑 {stage_name} 阶段"
    return "已请求阶段操作", getattr(result, "error_message", "") or "用户请求阶段监督动作"


def stage_self_correction_log_lines(result) -> List[str]:
    """从处理结果里提取各阶段自纠记录，供 GUI 日志展示。"""
    analysis = getattr(result, "intelligent_analysis", None) or {}
    stage_sources = [
        ("view_analysis", _read_field(analysis, "view_analysis", {}) or {}),
        ("semantic_adjudication", _read_field(analysis, "semantic_adjudication", {}) or {}),
        (
            "semantic_adjudication",
            _read_field(_read_field(analysis, "semantic_policy", {}) or {}, "semantic_adjudication", {}) or {},
        ),
        ("semantic_reconstruction", _read_field(analysis, "part_semantics", {}) or {}),
        ("modeling_generation", _read_field(analysis, "modeling_instructions", {}) or {}),
    ]
    try:
        from src.utils.stage_confirmation import stage_display_name
    except Exception:
        stage_display_name = lambda stage: stage

    lines = []
    seen = set()
    for default_stage, source in stage_sources:
        logs = _read_field(source, "self_correction_log", [])
        if isinstance(logs, dict):
            logs = [logs]
        if not isinstance(logs, list):
            continue
        for item in logs:
            if not isinstance(item, dict):
                continue
            marker = (
                item.get("stage") or default_stage,
                item.get("round_index"),
                item.get("trigger"),
                item.get("result"),
            )
            if marker in seen:
                continue
            seen.add(marker)
            stage = str(item.get("stage") or default_stage)
            round_index = item.get("round_index", "?")
            max_rounds = item.get("max_rounds", "?")
            trigger = item.get("trigger") or "本地校验问题"
            result_text = item.get("result") or "已完成"
            lines.append(
                f"模型自纠第 {round_index}/{max_rounds} 轮 | 阶段: {stage_display_name(stage)} | "
                f"原因: {trigger} | 结果: {result_text}"
            )
    return lines


def center_window_on_parent(window: tk.Toplevel, parent: tk.Widget) -> None:
    window.update_idletasks()
    parent.update_idletasks()

    width = max(window.winfo_width(), window.winfo_reqwidth())
    height = max(window.winfo_height(), window.winfo_reqheight())
    parent_width = parent.winfo_width()
    parent_height = parent.winfo_height()
    parent_x = parent.winfo_rootx()
    parent_y = parent.winfo_rooty()

    if parent_width <= 1 or parent_height <= 1:
        parent_width = parent.winfo_screenwidth()
        parent_height = parent.winfo_screenheight()
        parent_x = 0
        parent_y = 0

    x = parent_x + max((parent_width - width) // 2, 0)
    y = parent_y + max((parent_height - height) // 2, 0)
    window.geometry(f"{width}x{height}+{x}+{y}")


class AppConfig:
    """GUI 应用配置管理"""

    DEFAULT_CONFIG = {
        'cache': {
            'dir': '.cache/analysis',
            'default_ttl_days': 7,
            'max_size_mb': 500,
        },
        'output': {
            'base_dir': 'examples/output',
        },
        'processing': {
            'basic_default_height': 10.0,
            'intelligent_mode': True,
            'confirm_llm_stages': True,
        },
        'log': {
            'max_display': 2000,
        },
        'deepseek': {
            'user_id': 'cad-system-local',
            'request_timeout_seconds': 300,
            'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-v4-pro',
            'view_model': 'deepseek-v4-pro',
            'adjudication_model': 'deepseek-v4-pro',
            'semantic_model': 'deepseek-v4-pro',
            'front_stage_provider': '',
            'front_stage_base_url': 'https://api.moonshot.cn/v1',
            'enable_multimodal_front_stage_input': False,
            'semantic_adjudication_max_images': 1,
            'view_thinking_enabled': False,
            'view_reasoning_effort': 'high',
            'adjudication_thinking_enabled': False,
            'adjudication_reasoning_effort': 'high',
            'semantic_thinking_enabled': False,
            'semantic_reasoning_effort': 'high',
            'modeling_thinking_enabled': False,
            'modeling_reasoning_effort': 'max',
        },
    }

    def __init__(self, config_path: str = 'config/gui_config.json'):
        self.config_path = Path(config_path)
        self.data = dict(self.DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self._deep_update(self.data, loaded)
            except Exception:
                pass

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _deep_update(self, target: dict, source: dict):
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def get(self, *keys, default=None):
        node = self.data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return default
        return node if node is not None else default

    def set(self, *keys, value):
        node = self.data
        for key in keys[:-1]:
            if key not in node:
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value
        self.save()


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def read_project_env(env_path: Path = ENV_PATH) -> Dict[str, str]:
    """Read simple KEY=VALUE pairs from the project .env file."""
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_project_env(updates: Dict[str, str], env_path: Path = ENV_PATH) -> None:
    """Update simple KEY=VALUE entries while preserving comments and unknown keys."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    seen = set()
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_lines = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            updated_lines.append(raw)
            continue
        key, _, _ = raw.partition("=")
        key = key.strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            updated_lines.append(raw)

    for key, value in updates.items():
        if key not in seen:
            updated_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


__all__ = [
    "format_stage_supervision_message",
    "stage_self_correction_log_lines",
    "center_window_on_parent",
    "AppConfig",
    "PROJECT_ROOT",
    "ENV_PATH",
    "read_project_env",
    "write_project_env",
]
