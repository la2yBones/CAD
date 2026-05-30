# -*- coding: utf-8 -*-
import csv
import logging
import queue
import time
from datetime import datetime
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .helpers import (
    AppConfig,
    format_stage_supervision_message,
    stage_self_correction_log_lines,
)

logger = logging.getLogger(__name__)


class GuiLogHandler(logging.Handler):
    """
    GUI 日志处理器
    将所有日志记录推送到线程安全队列，GUI 定时轮询显示
    """

    def __init__(self, max_records: int = 2000):
        super().__init__()
        self.queue: queue.Queue = queue.Queue()
        self.max_records = max_records
        self.setFormatter(logging.Formatter('%(message)s'))

    def _module_label(self, logger_name: str) -> str:
        labels = {
            "__main__": "界面",
            "src.utils.cache": "缓存系统",
            "src.cad_parser.parser": "图纸解析",
            "src.batch_processor.pipeline": "处理管道",
            "src.batch_processor.processor": "文件处理",
            "src.model_generator.generator": "模型生成",
            "src.model_generator.freecad_bridge": "FreeCAD桥接",
        }
        return labels.get(logger_name, logger_name)

    def _format_message(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        module_label = self._module_label(record.name)
        if module_label and module_label not in ("root", ""):
            return f"【{module_label}】{message}"
        return message

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                'level': record.levelname,
                'name': record.name,
                'message': self._format_message(record),
                'levelno': record.levelno,
                'created': record.created,
            }
            self.queue.put(entry)
        except Exception:
            self.handleError(record)

    def drain(self) -> List[Dict]:
        records = []
        while not self.queue.empty():
            try:
                records.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return records


class LogPanel(ttk.Frame):
    """日志面板 — 实时日志展示、搜索、导出"""

    LEVEL_COLORS = {
        'ERROR': '#FF0000',
        'WARNING': '#FF8C00',
        'WARN': '#FF8C00',
        'INFO': '#006400',
        'DEBUG': '#808080',
    }

    def __init__(self, parent, log_handler: GuiLogHandler, app_config: Optional[AppConfig] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.log_handler = log_handler
        self.app_config = app_config
        self.records: List[Dict] = []
        self.token_status_var = tk.StringVar(
            value="Tokens: 0 | 缓存命中: 0/0% | 费用: ¥0.0000 | 调用: 0"
        )
        self._last_token_refresh = 0.0
        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        right_toolbar = ttk.Frame(toolbar)
        right_toolbar.pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Button(right_toolbar, text="导出 .txt", command=lambda: self._export_log('txt')).pack(side=tk.RIGHT, padx=2)
        ttk.Button(right_toolbar, text="导出 .csv", command=lambda: self._export_log('csv')).pack(side=tk.RIGHT, padx=2)
        ttk.Button(right_toolbar, text="清空", command=self._clear_log).pack(side=tk.RIGHT, padx=2)

        left_toolbar = ttk.Frame(toolbar)
        left_toolbar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(left_toolbar, text="搜索:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        search_entry = ttk.Entry(left_toolbar, textvariable=self.search_var, width=24)
        search_entry.pack(side=tk.LEFT, padx=(0, 5))

        self.filter_var = tk.StringVar(value="ALL")
        filter_combo = ttk.Combobox(left_toolbar, textvariable=self.filter_var, state="readonly",
                                     values=["ALL", "INFO", "WARNING", "ERROR"], width=10)
        filter_combo.pack(side=tk.LEFT, padx=(0, 10))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Label(left_toolbar, textvariable=self.token_status_var, foreground="darkblue").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=5, pady=(4, 0))
        self.status_var = tk.StringVar(value="就绪 | 日志: 0 条")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(5, 2),
        ).pack(fill=tk.X)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("timestamp", "level", "message")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        self.tree.heading("timestamp", text="时间")
        self.tree.heading("level", text="级别")
        self.tree.heading("message", text="消息")
        self.tree.column("timestamp", width=80, minwidth=60, stretch=False)
        self.tree.column("level", width=65, minwidth=50, stretch=False)
        self.tree.column("message", width=1200, minwidth=600, stretch=False)

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        for level, color in self.LEVEL_COLORS.items():
            self.tree.tag_configure(level, foreground=color)
        self.tree.tag_configure("hidden", foreground="#CCCCCC")

    def _start_polling(self):
        self._poll_logs()

    def _poll_logs(self):
        new_records = self.log_handler.drain()
        should_scroll_to_latest = bool(new_records)
        for rec in new_records:
            self.records.append(rec)
        max_display = 2000
        if len(self.records) > max_display:
            self.records = self.records[-max_display:]

        self._render_visible(scroll_to_latest=should_scroll_to_latest)
        self._refresh_token_stats()
        self.after(200, self._poll_logs)

    def _refresh_token_stats(self):
        now = time.time()
        if now - self._last_token_refresh < 1.0:
            return
        self._last_token_refresh = now

        try:
            from src.utils.config import load_config
            from src.utils.llm_telemetry import default_llm_telemetry_store, summarize_records
            from src.utils.deepseek_gui_config import format_llm_token_status

            config = load_config()
            deepseek_config = config.get("api", {}).get("deepseek", {})
            store = default_llm_telemetry_store(deepseek_config)
            summary = summarize_records(store.read_recent(limit=1000))
            self.token_status_var.set(format_llm_token_status(summary))
        except Exception:
            self.token_status_var.set("Tokens: -- | 缓存命中: -- | 费用: -- | 调用: --")

    def _render_visible(self, scroll_to_latest: bool = False):
        search_text = self.search_var.get().lower()
        level_filter = self.filter_var.get()

        visible = []
        for rec in self.records:
            if level_filter != "ALL" and rec.get('level') != level_filter:
                continue
            if search_text and search_text not in rec.get('message', '').lower():
                continue
            visible.append(rec)

        current_ids = set(self.tree.get_children())
        desired_count = len(visible)
        current_count = len(current_ids)

        if current_count != desired_count:
            for item in current_ids:
                self.tree.delete(item)
            for rec in visible:
                level = rec.get('level', 'INFO')
                self.tree.insert("", tk.END,
                                  values=(rec.get('timestamp', ''), level, rec.get('message', '')),
                                  tags=(level,))
        else:
            for i, item_id in enumerate(self.tree.get_children()):
                if i < len(visible):
                    rec = visible[i]
                    level = rec.get('level', 'INFO')
                    self.tree.item(item_id,
                                   values=(rec.get('timestamp', ''), level, rec.get('message', '')),
                                   tags=(level,))

        if scroll_to_latest and desired_count > 0:
            last = self.tree.get_children()[-1] if self.tree.get_children() else None
            if last:
                self.tree.see(last)

        active_count = sum(
            1 for r in self.records
            if (level_filter == "ALL" or r.get('level') == level_filter)
            and (not search_text or search_text in r.get('message', '').lower())
        )
        total = len(self.records)
        self.status_var.set(f"显示: {active_count} / 总计: {total} 条"
                            f"{' | 过滤: ' + level_filter if level_filter != 'ALL' else ''}"
                            f"{' | 搜索: ' + search_text if search_text else ''}")

    def _apply_filter(self):
        self.after(50, self._render_visible)

    def _clear_log(self):
        self.records.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_var.set("就绪 | 日志: 0 条")

    def _export_log(self, fmt: str):
        if not self.records:
            messagebox.showinfo("提示", "没有可导出的日志记录")
            return

        filepath = filedialog.asksaveasfilename(
            title=f"导出日志为 .{fmt}",
            defaultextension=f".{fmt}",
            filetypes=[(f"{fmt.upper()} 文件", f"*.{fmt}")] if fmt == 'txt' else [("CSV 文件", "*.csv")],
            initialfile=f"cad_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        if not filepath:
            return

        try:
            search_text = self.search_var.get().lower()
            level_filter = self.filter_var.get()
            filtered = [
                r for r in self.records
                if (level_filter == "ALL" or r.get('level') == level_filter)
                and (not search_text or search_text in r.get('message', '').lower())
            ]

            if fmt == 'csv':
                with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['时间', '级别', '消息'])
                    for r in filtered:
                        writer.writerow([r.get('timestamp', ''), r.get('level', ''), r.get('message', '')])
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("CAD 处理日志\n")
                    f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                    for r in filtered:
                        f.write(f"[{r.get('timestamp', '')}] [{r.get('level', '')}] {r.get('message', '')}\n")

            messagebox.showinfo("导出成功", f"已导出 {len(filtered)} 条日志到:\n{filepath}")
        except Exception as e:
            messagebox.showerror("导出失败", f"导出日志时出错:\n{e}")


__all__ = ["GuiLogHandler", "LogPanel"]
