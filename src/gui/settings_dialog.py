# -*- coding: utf-8 -*-
import logging
import os
from typing import Optional, Callable

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .helpers import AppConfig, PROJECT_ROOT, ENV_PATH, read_project_env, write_project_env
from src.utils.deepseek_gui_config import (
    apply_gui_deepseek_overrides,
    apply_gui_runtime_overrides,
    normalize_gui_reasoning_effort as _gui_reasoning_effort,
)

logger = logging.getLogger(__name__)


class SettingsDialog(tk.Toplevel):
    """Application settings dialog for environment and GUI preferences."""

    def __init__(
        self,
        parent,
        app_config: AppConfig,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.app_config = app_config
        self.on_saved = on_saved
        self.title("设置")
        self.geometry("760x660")
        self.minsize(700, 560)
        self.transient(parent)
        self.grab_set()

        env_values = read_project_env()
        self.api_key_var = tk.StringVar(value=env_values.get("DEEPSEEK_API_KEY", ""))
        self.front_stage_api_key_var = tk.StringVar(
            value=env_values.get("MOONSHOT_API_KEY", "") or env_values.get("KIMI_API_KEY", "")
        )
        self.freecad_path_var = tk.StringVar(value=env_values.get("FREECAD_BIN_PATH", ""))
        self.output_dir_var = tk.StringVar(
            value=self.app_config.get("output", "base_dir", default="examples/output")
        )
        self.cache_dir_var = tk.StringVar(
            value=self.app_config.get("cache", "dir", default=".cache/analysis")
        )
        self.confirm_stage_var = tk.BooleanVar(
            value=bool(self.app_config.get("processing", "confirm_llm_stages", default=True))
        )
        self.deepseek_user_id_var = tk.StringVar(
            value=self.app_config.get("deepseek", "user_id", default="cad-system-local")
        )
        self.deepseek_timeout_var = tk.StringVar(
            value=str(self.app_config.get("deepseek", "request_timeout_seconds", default=300))
        )
        self.deepseek_base_url_var = tk.StringVar(
            value=self.app_config.get("deepseek", "base_url", default="https://api.deepseek.com")
        )
        self.deepseek_model_var = tk.StringVar(
            value=self.app_config.get("deepseek", "model", default="deepseek-v4-pro")
        )
        self.deepseek_view_model_var = tk.StringVar(
            value=self.app_config.get("deepseek", "view_model", default="deepseek-v4-pro")
        )
        self.deepseek_adjudication_model_var = tk.StringVar(
            value=self.app_config.get("deepseek", "adjudication_model", default="deepseek-v4-pro")
        )
        self.deepseek_semantic_model_var = tk.StringVar(
            value=self.app_config.get("deepseek", "semantic_model", default="deepseek-v4-pro")
        )
        self.front_stage_provider_var = tk.StringVar(
            value=self.app_config.get("deepseek", "front_stage_provider", default="")
        )
        self.front_stage_base_url_var = tk.StringVar(
            value=self.app_config.get(
                "deepseek",
                "front_stage_base_url",
                default="https://api.moonshot.cn/v1",
            )
        )
        self.front_stage_multimodal_var = tk.BooleanVar(
            value=bool(
                self.app_config.get(
                    "deepseek",
                    "enable_multimodal_front_stage_input",
                    default=False,
                )
            )
        )
        self.semantic_adjudication_max_images_var = tk.StringVar(
            value=str(
                self.app_config.get(
                    "deepseek",
                    "semantic_adjudication_max_images",
                    default=1,
                )
            )
        )
        self.deepseek_view_thinking_var = tk.BooleanVar(
            value=bool(self.app_config.get("deepseek", "view_thinking_enabled", default=False))
        )
        self.deepseek_view_effort_var = tk.StringVar(
            value=self.app_config.get("deepseek", "view_reasoning_effort", default="high")
        )
        self.deepseek_adjudication_thinking_var = tk.BooleanVar(
            value=bool(self.app_config.get("deepseek", "adjudication_thinking_enabled", default=False))
        )
        self.deepseek_adjudication_effort_var = tk.StringVar(
            value=self.app_config.get("deepseek", "adjudication_reasoning_effort", default="high")
        )
        self.deepseek_semantic_thinking_var = tk.BooleanVar(
            value=bool(self.app_config.get("deepseek", "semantic_thinking_enabled", default=False))
        )
        self.deepseek_modeling_thinking_var = tk.BooleanVar(
            value=bool(self.app_config.get("deepseek", "modeling_thinking_enabled", default=False))
        )
        self.deepseek_semantic_effort_var = tk.StringVar(
            value=self.app_config.get("deepseek", "semantic_reasoning_effort", default="high")
        )
        self.deepseek_modeling_effort_var = tk.StringVar(
            value=self.app_config.get("deepseek", "modeling_reasoning_effort", default="max")
        )
        self._build_ui()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        from src.gui.helpers import center_window_on_parent
        center_window_on_parent(self, parent)

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        runtime_tab = ttk.Frame(notebook, padding=10)
        system_tab = ttk.Frame(notebook, padding=10)
        deepseek_tab = ttk.Frame(notebook, padding=10)
        notebook.add(runtime_tab, text="运行配置")
        notebook.add(system_tab, text="系统设置")
        notebook.add(deepseek_tab, text="大模型")

        self._build_runtime_tab(runtime_tab)
        self._build_system_tab(system_tab)
        self._build_deepseek_tab(deepseek_tab)

        button_row = ttk.Frame(self)
        button_row.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(button_row, text="保存", command=self._save).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _build_runtime_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="DeepSeek API Key:").grid(row=0, column=0, sticky=tk.W, pady=6)
        api_entry = ttk.Entry(parent, textvariable=self.api_key_var, show="*", width=48)
        api_entry.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(
            parent,
            text="显示/隐藏",
            command=lambda: api_entry.configure(show="" if api_entry.cget("show") else "*"),
        ).grid(row=0, column=2, padx=(6, 0), pady=6)

        ttk.Label(parent, text="Kimi/Moonshot API Key:").grid(row=1, column=0, sticky=tk.W, pady=6)
        front_api_entry = ttk.Entry(parent, textvariable=self.front_stage_api_key_var, show="*", width=48)
        front_api_entry.grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(
            parent,
            text="显示/隐藏",
            command=lambda: front_api_entry.configure(show="" if front_api_entry.cget("show") else "*"),
        ).grid(row=1, column=2, padx=(6, 0), pady=6)

        ttk.Label(parent, text="FreeCAD bin 目录:").grid(row=2, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.freecad_path_var).grid(
            row=2, column=1, sticky="ew", pady=6
        )
        ttk.Button(parent, text="选择...", command=self._choose_freecad_dir).grid(
            row=2, column=2, padx=(6, 0), pady=6
        )

        hint = (
            "如项目内已内置 FreeCAD，将优先使用 tools/freecad/*/bin/python.exe；"
            "否则使用上方配置的 FreeCAD bin 目录。"
        )
        ttk.Label(parent, text=hint, foreground="gray", wraplength=520).grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 0)
        )

    def _build_system_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="默认输出目录:").grid(row=0, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="选择...", command=self._choose_output_dir).grid(
            row=0, column=2, padx=(6, 0), pady=6
        )

        ttk.Label(parent, text="分析缓存目录:").grid(row=1, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.cache_dir_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="选择...", command=self._choose_cache_dir).grid(
            row=1, column=2, padx=(6, 0), pady=6
        )

        ttk.Checkbutton(
            parent,
            text="智能处理时逐阶段确认大模型结果",
            variable=self.confirm_stage_var,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(12, 4))

    def _build_deepseek_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="用户标识 user_id:").grid(row=0, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_user_id_var).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="请求超时(秒):").grid(row=1, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_timeout_var, width=16).grid(
            row=1, column=1, sticky=tk.W, pady=6
        )

        ttk.Label(parent, text="默认 Base URL:").grid(row=2, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_base_url_var).grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="默认模型:").grid(row=3, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_model_var).grid(row=3, column=1, sticky="ew", pady=6)

        front_frame = ttk.LabelFrame(parent, text="前置多模态模型（视图校正 + 图纸语义裁决）", padding=8)
        front_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 6))
        front_frame.columnconfigure(1, weight=1)

        ttk.Label(front_frame, text="提供方:").grid(row=0, column=0, sticky=tk.W, pady=4)
        provider_combo = ttk.Combobox(
            front_frame,
            textvariable=self.front_stage_provider_var,
            values=["", "moonshot", "deepseek"],
            width=16,
        )
        provider_combo.grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(front_frame, text="Base URL:").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(front_frame, textvariable=self.front_stage_base_url_var).grid(
            row=1, column=1, sticky="ew", pady=4
        )

        ttk.Checkbutton(
            front_frame,
            text="前置阶段附带图纸预览图",
            variable=self.front_stage_multimodal_var,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=4)

        ttk.Label(front_frame, text="裁决图片数:").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            front_frame,
            from_=1,
            to=4,
            textvariable=self.semantic_adjudication_max_images_var,
            width=8,
        ).grid(row=3, column=1, sticky=tk.W, pady=4)

        ttk.Label(parent, text="视图校正模型:").grid(row=5, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_view_model_var).grid(row=5, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="图纸语义裁决模型:").grid(row=6, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_adjudication_model_var).grid(
            row=6, column=1, sticky="ew", pady=6,
        )

        ttk.Label(parent, text="零件语义重建模型:").grid(row=7, column=0, sticky=tk.W, pady=6)
        ttk.Entry(parent, textvariable=self.deepseek_semantic_model_var).grid(row=7, column=1, sticky="ew", pady=6)

        thinking_frame = ttk.LabelFrame(parent, text="Thinking 分阶段开关", padding=8)
        thinking_frame.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        thinking_frame.columnconfigure(2, weight=1)

        ttk.Checkbutton(
            thinking_frame,
            text="视图语义校正",
            variable=self.deepseek_view_thinking_var,
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 12), pady=4)
        ttk.Label(thinking_frame, text="推理强度:").grid(row=0, column=1, sticky=tk.E, pady=4)
        view_effort = ttk.Combobox(
            thinking_frame,
            textvariable=self.deepseek_view_effort_var,
            state="readonly",
            values=["high", "max"],
            width=10,
        )
        view_effort.grid(row=0, column=2, sticky=tk.W, pady=4)

        ttk.Checkbutton(
            thinking_frame,
            text="图纸语义裁决",
            variable=self.deepseek_adjudication_thinking_var,
        ).grid(row=1, column=0, sticky=tk.W, padx=(0, 12), pady=4)
        ttk.Label(thinking_frame, text="推理强度:").grid(row=1, column=1, sticky=tk.E, pady=4)
        adjudication_effort = ttk.Combobox(
            thinking_frame,
            textvariable=self.deepseek_adjudication_effort_var,
            state="readonly",
            values=["high", "max"],
            width=10,
        )
        adjudication_effort.grid(row=1, column=2, sticky=tk.W, pady=4)

        ttk.Checkbutton(
            thinking_frame,
            text="零件语义重建",
            variable=self.deepseek_semantic_thinking_var,
        ).grid(row=2, column=0, sticky=tk.W, padx=(0, 12), pady=4)
        ttk.Label(thinking_frame, text="推理强度:").grid(row=2, column=1, sticky=tk.E, pady=4)
        semantic_effort = ttk.Combobox(
            thinking_frame,
            textvariable=self.deepseek_semantic_effort_var,
            state="readonly",
            values=["high", "max"],
            width=10,
        )
        semantic_effort.grid(row=2, column=2, sticky=tk.W, pady=4)

        ttk.Checkbutton(
            thinking_frame,
            text="建模指令生成",
            variable=self.deepseek_modeling_thinking_var,
        ).grid(row=3, column=0, sticky=tk.W, padx=(0, 12), pady=4)
        ttk.Label(thinking_frame, text="推理强度:").grid(row=3, column=1, sticky=tk.E, pady=4)
        modeling_effort = ttk.Combobox(
            thinking_frame,
            textvariable=self.deepseek_modeling_effort_var,
            state="readonly",
            values=["high", "max"],
            width=10,
        )
        modeling_effort.grid(row=3, column=2, sticky=tk.W, pady=4)

        hint = "默认关闭 thinking；需要更强语义判断时可只开启语义重建或建模指令阶段。"
        ttk.Label(parent, text=hint, foreground="gray", wraplength=620).grid(
            row=9, column=0, columnspan=2, sticky=tk.W, pady=(10, 0)
        )

    def _choose_freecad_dir(self):
        path = filedialog.askdirectory(title="选择 FreeCAD bin 目录")
        if path:
            self.freecad_path_var.set(path)

    def _choose_output_dir(self):
        path = filedialog.askdirectory(title="选择默认输出目录")
        if path:
            self.output_dir_var.set(path)

    def _choose_cache_dir(self):
        path = filedialog.askdirectory(title="选择分析缓存目录")
        if path:
            self.cache_dir_var.set(path)

    def _save(self):
        api_key = self.api_key_var.get().strip()
        front_stage_api_key = self.front_stage_api_key_var.get().strip()
        freecad_path = self.freecad_path_var.get().strip()
        output_dir = self.output_dir_var.get().strip() or "examples/output"
        cache_dir = self.cache_dir_var.get().strip() or ".cache/analysis"
        try:
            timeout_seconds = float(self.deepseek_timeout_var.get().strip() or "300")
            if timeout_seconds <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("保存失败", "大模型请求超时必须是大于 0 的数字。")
            return
        try:
            adjudication_max_images = int(self.semantic_adjudication_max_images_var.get().strip() or "1")
            if adjudication_max_images <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("保存失败", "裁决图片数必须是大于 0 的整数。")
            return

        try:
            write_project_env({
                "DEEPSEEK_API_KEY": api_key,
                "MOONSHOT_API_KEY": front_stage_api_key,
                "FREECAD_BIN_PATH": freecad_path,
            })
            os.environ["DEEPSEEK_API_KEY"] = api_key
            os.environ["MOONSHOT_API_KEY"] = front_stage_api_key
            self.app_config.set("output", "base_dir", value=output_dir)
            self.app_config.set("cache", "dir", value=cache_dir)
            self.app_config.set(
                "processing",
                "confirm_llm_stages",
                value=bool(self.confirm_stage_var.get()),
            )
            self.app_config.set("deepseek", "user_id", value=self.deepseek_user_id_var.get().strip())
            self.app_config.set("deepseek", "request_timeout_seconds", value=timeout_seconds)
            self.app_config.set("deepseek", "base_url", value=self.deepseek_base_url_var.get().strip())
            self.app_config.set("deepseek", "model", value=self.deepseek_model_var.get().strip())
            self.app_config.set("deepseek", "view_model", value=self.deepseek_view_model_var.get().strip())
            self.app_config.set(
                "deepseek",
                "adjudication_model",
                value=self.deepseek_adjudication_model_var.get().strip(),
            )
            self.app_config.set("deepseek", "semantic_model", value=self.deepseek_semantic_model_var.get().strip())
            self.app_config.set(
                "deepseek",
                "front_stage_provider",
                value=self.front_stage_provider_var.get().strip(),
            )
            self.app_config.set(
                "deepseek",
                "front_stage_base_url",
                value=self.front_stage_base_url_var.get().strip(),
            )
            self.app_config.set(
                "deepseek",
                "enable_multimodal_front_stage_input",
                value=bool(self.front_stage_multimodal_var.get()),
            )
            self.app_config.set(
                "deepseek",
                "semantic_adjudication_max_images",
                value=adjudication_max_images,
            )
            self.app_config.set(
                "deepseek",
                "view_thinking_enabled",
                value=bool(self.deepseek_view_thinking_var.get()),
            )
            self.app_config.set(
                "deepseek",
                "view_reasoning_effort",
                value=_gui_reasoning_effort(self.deepseek_view_effort_var.get(), "high"),
            )
            self.app_config.set(
                "deepseek",
                "adjudication_thinking_enabled",
                value=bool(self.deepseek_adjudication_thinking_var.get()),
            )
            self.app_config.set(
                "deepseek",
                "adjudication_reasoning_effort",
                value=_gui_reasoning_effort(self.deepseek_adjudication_effort_var.get(), "high"),
            )
            self.app_config.set(
                "deepseek",
                "semantic_thinking_enabled",
                value=bool(self.deepseek_semantic_thinking_var.get()),
            )
            self.app_config.set(
                "deepseek",
                "semantic_reasoning_effort",
                value=_gui_reasoning_effort(self.deepseek_semantic_effort_var.get(), "high"),
            )
            self.app_config.set(
                "deepseek",
                "modeling_thinking_enabled",
                value=bool(self.deepseek_modeling_thinking_var.get()),
            )
            self.app_config.set(
                "deepseek",
                "modeling_reasoning_effort",
                value=_gui_reasoning_effort(self.deepseek_modeling_effort_var.get(), "max"),
            )
        except Exception as e:
            messagebox.showerror("保存失败", f"保存设置时出错：\n{e}")
            return

        if self.on_saved:
            self.on_saved()
        messagebox.showinfo("设置已保存", "设置已保存，新的 API Key 和 FreeCAD 路径会在下次处理时生效。")
        self.destroy()


__all__ = ["SettingsDialog"]
