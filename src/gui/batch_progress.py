# -*- coding: utf-8 -*-
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict

import tkinter as tk
from tkinter import messagebox, ttk

logger = logging.getLogger(__name__)

__all__ = ["ProcessingCancelled", "BatchProgressWindow"]


class ProcessingCancelled(RuntimeError):
    """Raised when the GUI user requests cooperative cancellation."""


class BatchProgressWindow:
    """Non-modal batch progress board for the current GUI session."""

    STAGE_RANGES = {
        "queued": (0, 0, 1.0),
        "preparing": (0, 10, 4.0),
        "parsing": (10, 25, 8.0),
        "ai_analysis": (25, 75, 300.0),
        "modeling": (75, 90, 20.0),
        "finalizing": (90, 95, 5.0),
        "done": (100, 100, 1.0),
    }

    def __init__(
        self,
        parent,
        items: Dict[str, Dict[str, Any]],
        *,
        output_dir: str,
        on_closed: Callable[[], None],
    ):
        self.parent = parent
        self.items = items
        self.output_dir = output_dir
        self.on_closed = on_closed
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.window = tk.Toplevel(parent)
        self.window.title("批量处理进度")
        self.window.geometry("860x420")
        self.window.minsize(760, 320)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        from src.gui.helpers import center_window_on_parent
        center_window_on_parent(self.window, parent)
        self._build_ui()
        self.refresh_all()
        self._tick()

    def _build_ui(self):
        header = ttk.Frame(self.window, padding=(10, 10, 10, 6))
        header.pack(fill=tk.X)
        ttk.Label(header, text="批量处理进度", font=("", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="打开输出目录", width=14, command=self._open_output_dir).pack(side=tk.RIGHT)
        ttk.Button(header, text="关闭", width=10, command=self.close).pack(side=tk.RIGHT, padx=(0, 8))

        columns = ttk.Frame(self.window, padding=(10, 0, 10, 0))
        columns.pack(fill=tk.X)
        for index, width in enumerate((180, 90, 210, 230, 80)):
            columns.grid_columnconfigure(index, minsize=width)
        ttk.Label(columns, text="图纸").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(columns, text="状态").grid(row=0, column=1, sticky=tk.W)
        ttk.Label(columns, text="进度").grid(row=0, column=2, sticky=tk.W)
        ttk.Label(columns, text="当前阶段 / 结果").grid(row=0, column=3, sticky=tk.W)
        ttk.Label(columns, text="耗时").grid(row=0, column=4, sticky=tk.W)

        body = ttk.Frame(self.window, padding=(10, 4, 10, 10))
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.rows_frame = ttk.Frame(self.canvas)
        self.rows_frame.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_all(self):
        for item_id in list(self.items):
            self._ensure_row(item_id)
        self.refresh()

    def refresh(self):
        for item_id, row in self.rows.items():
            item = self.items.get(item_id)
            if not item:
                continue
            row["status"].set(item.get("status", ""))
            row["stage"].set(item.get("message") or item.get("stage_text", ""))
            row["elapsed"].set(self._elapsed_text(item))
            row["progress"].set(self._progress_for(item))

    def _ensure_row(self, item_id: str):
        if item_id in self.rows:
            return
        item = self.items[item_id]
        row_index = len(self.rows)
        frame = ttk.Frame(self.rows_frame)
        frame.grid(row=row_index, column=0, sticky="ew", pady=2)
        for index, width in enumerate((180, 90, 210, 230, 80)):
            frame.grid_columnconfigure(index, minsize=width)

        status_var = tk.StringVar(value=item.get("status", ""))
        stage_var = tk.StringVar(value=item.get("stage_text", ""))
        elapsed_var = tk.StringVar(value="0.0s")
        progress_var = tk.DoubleVar(value=0.0)

        ttk.Label(frame, text=item.get("name", ""), width=22).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(frame, textvariable=status_var, width=10).grid(row=0, column=1, sticky=tk.W)
        ttk.Progressbar(frame, variable=progress_var, maximum=100, length=190).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(frame, textvariable=stage_var, width=28).grid(row=0, column=3, sticky=tk.W)
        ttk.Label(frame, textvariable=elapsed_var, width=9).grid(row=0, column=4, sticky=tk.W)
        self.rows[item_id] = {
            "status": status_var,
            "stage": stage_var,
            "elapsed": elapsed_var,
            "progress": progress_var,
        }

    def _progress_for(self, item: Dict[str, Any]) -> float:
        if item.get("finished"):
            return 100.0
        stage = item.get("stage", "queued")
        start, end, expected = self.STAGE_RANGES.get(stage, self.STAGE_RANGES["queued"])
        if start == end:
            return float(start)
        elapsed = max(time.time() - float(item.get("stage_started_at") or time.time()), 0.0)
        ratio = min(elapsed / expected, 0.98)
        return round(start + (end - start) * ratio, 1)

    @staticmethod
    def _elapsed_text(item: Dict[str, Any]) -> str:
        started_at = item.get("started_at")
        ended_at = item.get("ended_at")
        if not started_at:
            return ""
        end = float(ended_at or time.time())
        return f"{max(end - float(started_at), 0.0):.1f}s"

    def _tick(self):
        if not self.exists():
            return
        self.refresh()
        self.window.after(500, self._tick)

    def _open_output_dir(self):
        try:
            path = Path(self.output_dir or ".")
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except Exception as e:
            messagebox.showerror("打开输出目录失败", f"无法打开输出目录：\n{e}", parent=self.window)

    def exists(self) -> bool:
        return bool(getattr(self, "window", None)) and self.window.winfo_exists()

    def focus(self):
        if self.exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self):
        if self.exists():
            self.window.destroy()
        self.on_closed()
