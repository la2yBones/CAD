#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD 图纸 3D 建模系统 - 增强版 GUI
功能：图纸预览、智能分析、模型生成、缓存管理、日志面板
"""

import sys
import os
import json
import csv
import threading
import time
import queue
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
            'auto_scroll': True,
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


class CacheManagerPanel(ttk.Frame):
    """缓存管理面板"""

    TTL_OPTIONS = [
        ('1 小时', 3600),
        ('6 小时', 21600),
        ('12 小时', 43200),
        ('1 天', 86400),
        ('3 天', 259200),
        ('7 天', 604800),
        ('14 天', 1209600),
        ('30 天', 2592000),
    ]

    def __init__(self, parent, app_config: AppConfig, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_config = app_config
        self._cache = None
        self._entry_by_item = {}
        self._build_ui()
        self._refresh_lock = threading.Lock()

    def _get_cache(self):
        if self._cache is None:
            try:
                from src.utils.cache import AnalysisCache
                cache_config = self.app_config.data.get('cache', {})
                self._cache = AnalysisCache(
                    cache_dir=cache_config.get('dir', '.cache/analysis'),
                    default_ttl=cache_config.get('default_ttl_days', 7) * 86400,
                )
            except Exception as e:
                logger.warning(f"缓存系统初始化失败: {e}")
        return self._cache

    def _build_ui(self):
        # 缓存条目列表
        list_frame = ttk.LabelFrame(self, text="缓存条目", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        header_frame = ttk.Frame(list_frame)
        header_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(header_frame, text="缓存条目", font=("", 9, "bold")).pack(side=tk.LEFT)
        self.stats_summary_var = tk.StringVar(value="条目数: -- | 总大小: -- | 已过期: --")
        ttk.Label(header_frame, textvariable=self.stats_summary_var, foreground="darkblue").pack(side=tk.RIGHT)

        columns = ("source_file", "size", "timestamp", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        self.tree.heading("source_file", text="源文件")
        self.tree.heading("size", text="大小")
        self.tree.heading("timestamp", text="时间")
        self.tree.heading("status", text="状态")
        self.tree.column("source_file", width=200)
        self.tree.column("size", width=80)
        self.tree.column("timestamp", width=140)
        self.tree.column("status", width=60)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_entry_double_click)

        # 操作按钮行
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

        ttk.Button(btn_frame, text="刷新", command=self.refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="删除选中", command=self._delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="清理过期", command=self._clear_expired).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="清空", command=self._clear_all).pack(side=tk.LEFT, padx=2)

        # 缓存策略配置
        config_frame = ttk.LabelFrame(self, text="缓存策略", padding=5)
        config_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        row = ttk.Frame(config_frame)
        row.pack(fill=tk.X)

        ttk.Label(row, text="过期时间 (TTL):").pack(side=tk.LEFT, padx=(0, 5))
        self.ttl_var = tk.StringVar()
        current_ttl = self.app_config.get('cache', 'default_ttl_days', default=7) * 86400
        ttl_combo = ttk.Combobox(row, textvariable=self.ttl_var, state="readonly", width=10)
        ttl_combo['values'] = [opt[0] for opt in self.TTL_OPTIONS]
        default_idx = 5
        for i, (_, seconds) in enumerate(self.TTL_OPTIONS):
            if seconds == current_ttl:
                default_idx = i
                break
        ttl_combo.current(default_idx)
        ttl_combo.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row, text="应用", command=self._apply_ttl).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="立即清理过期", command=self._clear_expired).pack(side=tk.LEFT, padx=10)

        cache_dir = self.app_config.get('cache', 'dir', default='.cache/analysis')
        ttk.Label(config_frame, text=f"缓存目录: {cache_dir}", foreground="gray").pack(
            anchor=tk.W, pady=(5, 0))

    def refresh(self):
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            cache = self._get_cache()
            if cache is None:
                return

            stats = cache.get_stats()
            entries = cache.list_entries()

            exp_count = sum(1 for e in entries if e.get('expired'))
            total_size = stats.get('total_size_mb', 0)
            self.stats_summary_var.set(
                f"条目数: {stats.get('total_count', 0)} | 总大小: {total_size:.2f} MB | 已过期: {exp_count}"
            )

            for item in self.tree.get_children():
                self.tree.delete(item)
            self._entry_by_item.clear()

            for entry in entries:
                src = entry.get('source_file', '')
                if len(src) > 50:
                    src = "..." + src[-47]
                size_kb = entry.get('size_bytes', 0) / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                ts = datetime.fromtimestamp(entry.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M')
                status = "已过期" if entry.get('expired') else "有效"
                tags = ("expired",) if entry.get('expired') else ("active",)
                item_id = self.tree.insert("", tk.END, values=(src, size_str, ts, status), tags=tags)
                self._entry_by_item[item_id] = entry

            self.tree.tag_configure("expired", foreground="red")
            self.tree.tag_configure("active", foreground="green")
        finally:
            self._refresh_lock.release()

    def _delete_selected(self):
        cache = self._get_cache()
        if cache is None:
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的缓存条目")
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(selected)} 个缓存条目？"):
            return

        count = 0
        for item_id in selected:
            entry = self._entry_by_item.get(item_id, {})
            cache_path = entry.get('cache_path')
            if cache_path:
                try:
                    if cache.delete_entry(cache_path):
                        count += 1
                except Exception as e:
                    logger.warning(f"删除缓存文件失败: {cache_path}: {e}")
            else:
                src_file = entry.get('source_file')
                if src_file:
                    count += cache.invalidate(src_file)
        try:
            cache.clear_expired()
        except Exception:
            pass
        messagebox.showinfo("完成", f"已删除 {count} 个缓存条目")
        self.refresh()

    def _clear_expired(self):
        cache = self._get_cache()
        if cache is None:
            return
        count = cache.clear_expired()
        messagebox.showinfo("完成", f"已清理 {count} 个过期缓存")
        self.refresh()

    def _clear_all(self):
        if not messagebox.askyesno("确认", "确定清空所有缓存？此操作不可恢复！"):
            return
        cache = self._get_cache()
        if cache is None:
            return
        count = cache.clear_all()
        messagebox.showinfo("完成", f"已清空 {count} 个缓存条目")
        self.refresh()

    def _apply_ttl(self):
        selected = self.ttl_var.get()
        for label, seconds in self.TTL_OPTIONS:
            if label == selected:
                days = seconds // 86400
                self.app_config.set('cache', 'default_ttl_days', value=days)
                cache = self._get_cache()
                if cache:
                    cache.default_ttl = seconds
                messagebox.showinfo("完成", f"缓存过期时间已设置为: {label}")
                return

    def _on_entry_double_click(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if values and len(values) >= 4:
            entry = self._entry_by_item.get(selected[0], {})
            source_file = entry.get('source_file') or values[0]
            cache_path = entry.get('cache_path', '')
            detail = (
                f"源文件: {source_file}\n"
                f"缓存文件: {cache_path}\n"
                f"大小: {values[1]}\n"
                f"时间: {values[2]}\n"
                f"状态: {values[3]}"
            )
            messagebox.showinfo("缓存详情", detail)


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
        self.auto_scroll = tk.BooleanVar(value=True)
        self.token_status_var = tk.StringVar(value="Tokens: 0 | 输入: 0 | 输出: 0 | 调用: 0")
        self._last_token_refresh = 0.0
        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        # 工具栏
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        ttk.Label(toolbar, text="搜索:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(0, 5))

        self.filter_var = tk.StringVar(value="ALL")
        filter_combo = ttk.Combobox(toolbar, textvariable=self.filter_var, state="readonly",
                                     values=["ALL", "INFO", "WARNING", "ERROR"], width=10)
        filter_combo.pack(side=tk.LEFT, padx=(0, 10))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Label(toolbar, textvariable=self.token_status_var, foreground="darkblue").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Checkbutton(toolbar, text="自动滚动", variable=self.auto_scroll).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(toolbar, text="导出 .txt", command=lambda: self._export_log('txt')).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="导出 .csv", command=lambda: self._export_log('csv')).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="清空", command=self._clear_log).pack(side=tk.RIGHT, padx=2)

        # 日志统计行放在日志区块内部，避免被窗口底部边缘挤压
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

        # 日志列表
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
        for rec in new_records:
            self.records.append(rec)
        max_display = 2000
        if len(self.records) > max_display:
            self.records = self.records[-max_display:]

        self._render_visible()
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

            config = load_config()
            deepseek_config = config.get("api", {}).get("deepseek", {})
            store = default_llm_telemetry_store(deepseek_config)
            summary = summarize_records(store.read_recent(limit=1000))
            self.token_status_var.set(
                "Tokens: {total:,} | 输入: {prompt:,} | 输出: {completion:,} | 调用: {calls}".format(
                    total=summary.get("total_tokens", 0),
                    prompt=summary.get("prompt_tokens", 0),
                    completion=summary.get("completion_tokens", 0),
                    calls=summary.get("call_count", 0),
                )
            )
        except Exception:
            self.token_status_var.set("Tokens: -- | 输入: -- | 输出: -- | 调用: --")

    def _render_visible(self):
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

        if self.auto_scroll.get() and desired_count > 0:
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


class LLMTelemetryPanel(ttk.Frame):
    """LLM call telemetry viewer."""

    def __init__(self, parent, app_config: AppConfig, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_config = app_config
        self.records: List[Dict] = []
        self._record_by_item: Dict[str, Dict] = {}
        self._last_signature = ""
        self._build_ui()
        self._poll()

    def _build_ui(self):
        summary = ttk.Frame(self)
        summary.pack(fill=tk.X, padx=5, pady=(5, 0))

        self.summary_vars = {
            "calls": tk.StringVar(value="调用次数: 0"),
            "tokens": tk.StringVar(value="总 Tokens: 0"),
            "prompt": tk.StringVar(value="输入 Tokens: 0"),
            "completion": tk.StringVar(value="输出 Tokens: 0"),
            "rate": tk.StringVar(value="生成速率: 0 Tokens/s"),
            "duration": tk.StringVar(value="总耗时: 0.0s"),
        }
        for var in self.summary_vars.values():
            ttk.Label(summary, textvariable=var, foreground="darkblue").pack(side=tk.LEFT, padx=(0, 14))
        ttk.Button(summary, text="刷新", command=self.refresh).pack(side=tk.RIGHT, padx=2)
        ttk.Button(summary, text="删除选中", command=self.delete_selected_records).pack(side=tk.RIGHT, padx=2)
        ttk.Button(summary, text="清空", command=self.clear_records).pack(side=tk.RIGHT, padx=2)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("time", "drawing", "stage", "model", "status", "prompt", "completion", "total", "rate", "duration")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        headings = {
            "time": "时间",
            "drawing": "图纸名称",
            "stage": "阶段",
            "model": "模型",
            "status": "状态",
            "prompt": "输入 Tokens",
            "completion": "输出 Tokens",
            "total": "总 Tokens",
            "rate": "Tokens/s",
            "duration": "耗时(秒)",
        }
        widths = {
            "time": 155,
            "drawing": 150,
            "stage": 145,
            "model": 130,
            "status": 65,
            "prompt": 80,
            "completion": 95,
            "total": 80,
            "rate": 70,
            "duration": 70,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=50)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", self._open_record_window)
        self.tree.bind("<Delete>", lambda _event: self.delete_selected_records())

    def _telemetry_store(self):
        from src.utils.config import load_config
        from src.utils.llm_telemetry import default_llm_telemetry_store

        config = load_config()
        return default_llm_telemetry_store(config.get("api", {}).get("deepseek", {}))

    def _poll(self):
        self.refresh()
        self.after(1000, self._poll)

    def refresh(self):
        try:
            from src.utils.llm_telemetry import summarize_records

            self.records = self._telemetry_store().read_recent(limit=1000)
            signature = "|".join(str(r.get("call_id", "")) for r in self.records[-200:])
            if signature != self._last_signature:
                self._last_signature = signature
                self._render_records()

            summary = summarize_records(self.records)
            self.summary_vars["calls"].set(f"调用次数: {summary.get('call_count', 0)}")
            self.summary_vars["tokens"].set(f"总 Tokens: {summary.get('total_tokens', 0):,}")
            self.summary_vars["prompt"].set(f"输入 Tokens: {summary.get('prompt_tokens', 0):,}")
            self.summary_vars["completion"].set(f"输出 Tokens: {summary.get('completion_tokens', 0):,}")
            self.summary_vars["rate"].set(
                f"生成速率: {summary.get('completion_tokens_per_second', 0.0):.2f} Tokens/s"
            )
            self.summary_vars["duration"].set(f"总耗时: {summary.get('duration_seconds', 0.0):.1f}s")
        except Exception as e:
            logger.warning(f"LLM 调用记录不可用: {e}")

    def clear_records(self):
        if not messagebox.askyesno("清空大模型调用记录", "确定要清空所有大模型调用记录吗？"):
            return
        try:
            store = self._telemetry_store()
            if store.log_path.exists():
                store.log_path.write_text("", encoding="utf-8")
            self.records = []
            self._last_signature = ""
            self._render_records()
            self.summary_vars["calls"].set("调用次数: 0")
            self.summary_vars["tokens"].set("总 Tokens: 0")
            self.summary_vars["prompt"].set("输入 Tokens: 0")
            self.summary_vars["completion"].set("输出 Tokens: 0")
            self.summary_vars["rate"].set("生成速率: 0 Tokens/s")
            self.summary_vars["duration"].set("总耗时: 0.0s")
            logger.info("大模型调用记录已清空")
        except Exception as e:
            messagebox.showerror("清空失败", f"清空大模型调用记录时出错:\n{e}")

    def _selected_records(self) -> List[Dict]:
        return [
            self._record_by_item[item]
            for item in self.tree.selection()
            if item in self._record_by_item
        ]

    def delete_selected_records(self):
        selected_records = self._selected_records()
        if not selected_records:
            messagebox.showinfo("请选择记录", "请先选择一条或多条大模型调用记录。")
            return

        if not messagebox.askyesno(
            "删除选中记录",
            f"确定要删除选中的 {len(selected_records)} 条大模型调用记录吗？"
        ):
            return

        selected_call_ids = {
            str(record.get("call_id"))
            for record in selected_records
            if record.get("call_id")
        }
        if not selected_call_ids:
            messagebox.showwarning("无法删除", "选中记录缺少 call_id，无法安全定位。")
            return

        try:
            store = self._telemetry_store()
            if not store.log_path.exists():
                return

            kept_lines = []
            removed_count = 0
            for line in store.log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    kept_lines.append(line)
                    continue

                if str(record.get("call_id")) in selected_call_ids:
                    removed_count += 1
                    continue
                kept_lines.append(line)

            content = "\n".join(kept_lines)
            store.log_path.write_text((content + "\n") if content else "", encoding="utf-8")
            self.records = [r for r in self.records if str(r.get("call_id")) not in selected_call_ids]
            self._last_signature = ""
            self._render_records()
            self.refresh()
            logger.info(f"已删除 {removed_count} 条大模型调用记录")
        except Exception as e:
            messagebox.showerror("删除失败", f"删除大模型调用记录时出错:\n{e}")

    def _render_records(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._record_by_item.clear()

        for record in reversed(self.records):
            tokens = record.get("tokens") or {}
            values = (
                self._display_timestamp(record.get("timestamp", "")),
                self._display_drawing_name(record),
                self._display_stage(record.get("stage", "")),
                record.get("model", ""),
                self._display_status(record.get("status", "")),
                tokens.get("prompt_tokens", 0),
                tokens.get("completion_tokens", 0),
                tokens.get("total_tokens", 0),
                record.get("token_rate_completion_per_second", 0.0),
                record.get("duration_seconds", 0.0),
            )
            item = self.tree.insert("", tk.END, values=values)
            self._record_by_item[item] = record

    def _display_timestamp(self, timestamp: Any) -> str:
        raw = str(timestamp or "")
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return raw[:19]

    def _display_drawing_name(self, record: Dict[str, Any]) -> str:
        file_path = record.get("file_path")
        if file_path:
            try:
                return Path(str(file_path)).stem
            except Exception:
                return str(file_path)
        return ""

    def _display_stage(self, stage: str) -> str:
        labels = {
            "view_analysis": "视图语义校正",
            "semantic_reconstruction": "零件语义重建",
            "modeling_generation": "建模指令生成",
            "self_test": "自测",
        }
        return labels.get(str(stage), str(stage))

    def _display_status(self, status: str) -> str:
        labels = {
            "ok": "成功",
            "error": "失败",
        }
        return labels.get(str(status), str(status))

    def _open_record_window(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        record = self._record_by_item.get(selected[0])
        if not record:
            return

        detail_win = tk.Toplevel(self)
        detail_win.title(
            f"\u5927\u6a21\u578b\u8c03\u7528\u8be6\u60c5 - {self._display_stage(record.get('stage', ''))} - {self._display_status(record.get('status', ''))}"
        )
        detail_win.geometry("900x650")

        header = ttk.Frame(detail_win)
        header.pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Label(
            header,
            text=f"\u6a21\u578b: {record.get('model', '')} | \u72b6\u6001: {self._display_status(record.get('status', ''))} | \u8c03\u7528\u65f6\u95f4: {self._display_timestamp(record.get('timestamp', ''))}",
        ).pack(side=tk.LEFT)

        text_frame = ttk.Frame(detail_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        text_widget = tk.Text(text_frame, wrap=tk.NONE, font=("Consolas", 9))
        vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        hsb = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=text_widget.xview)
        text_widget.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        text_widget.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)
        text_widget.insert(tk.END, self._format_record_detail(record))
        text_widget.configure(state="disabled")

    def _format_record_detail(self, record: Dict[str, Any]) -> str:
        metadata = {
            "call_id": record.get("call_id"),
            "timestamp": self._display_timestamp(record.get("timestamp")),
            "timestamp_raw": record.get("timestamp"),
            "drawing_name": self._display_drawing_name(record),
            "stage": self._display_stage(record.get("stage", "")),
            "stage_key": record.get("stage"),
            "provider": record.get("provider"),
            "model": record.get("model"),
            "file_path": record.get("file_path"),
            "status": record.get("status"),
            "duration_seconds": record.get("duration_seconds"),
            "tokens": record.get("tokens"),
            "token_rate_completion_per_second": record.get("token_rate_completion_per_second"),
            "error": record.get("error"),
        }
        sections = [
            "\u3010\u5143\u4fe1\u606f\u3011",
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
            "",
            "\u3010\u539f\u59cb\u8bf7\u6c42\u3011",
            self._format_request_detail(record.get("request")),
            "",
            "\u3010\u539f\u59cb\u54cd\u5e94\u3011",
            self._format_response_detail(record.get("response")),
        ]
        return "\n".join(sections)

    def _format_request_detail(self, request: Any) -> str:
        if not isinstance(request, dict):
            return json.dumps(request, ensure_ascii=False, indent=2, default=str)

        sections: List[str] = []
        request_meta = {key: value for key, value in request.items() if key != "messages"}
        if request_meta:
            sections.extend([
                "\u8bf7\u6c42\u53c2\u6570\uff1a",
                json.dumps(request_meta, ensure_ascii=False, indent=2, default=str),
                "",
            ])

        messages = request.get("messages")
        if not isinstance(messages, list):
            sections.append(json.dumps(request, ensure_ascii=False, indent=2, default=str))
            return "\n".join(sections)

        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                sections.extend([f"\u6d88\u606f {index}\uff1a", str(message), ""])
                continue
            role = message.get("role", "unknown")
            content = message.get("content", "")
            sections.append(f"\u6d88\u606f {index} [{role}]\uff1a")
            sections.append(self._format_message_content(content))
            sections.append("")
        return "\n".join(sections).rstrip()

    def _format_response_detail(self, response: Any) -> str:
        if not isinstance(response, dict):
            return json.dumps(response, ensure_ascii=False, indent=2, default=str)

        sections: List[str] = []
        choices = response.get("choices")
        if isinstance(choices, list):
            for index, choice in enumerate(choices, start=1):
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if content:
                    sections.extend([f"\u56de\u590d {index}\uff1a", self._format_message_content(content), ""])
                reasoning_content = message.get("reasoning_content")
                if reasoning_content:
                    sections.extend([f"\u63a8\u7406\u5185\u5bb9 {index}\uff1a", self._format_message_content(reasoning_content), ""])

        sections.extend([
            "\u54cd\u5e94\u5bf9\u8c61\uff1a",
            json.dumps(response, ensure_ascii=False, indent=2, default=str),
        ])
        return "\n".join(sections).rstrip()

    def _format_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, indent=2, default=str)


class ProcessingCancelled(RuntimeError):
    """Raised when the GUI user requests cooperative cancellation."""


class ProcessingPanel(ttk.Frame):
    """处理面板 — 文件选择、参数配置、处理控制"""

    def __init__(self, parent, app_config: AppConfig, on_open_step: Callable, on_open_output: Callable,
                 preview_fig=None, preview_canvas=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_config = app_config
        self.on_open_step = on_open_step
        self.on_open_output = on_open_output
        self.preview_fig = preview_fig
        self.preview_canvas = preview_canvas
        self.pipeline = None
        self._processing = False
        self._awaiting_clarification = False
        self._paused = False
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._build_ui()

    def _build_ui(self):
        # 文件选择
        top_frame = ttk.LabelFrame(self, text="文件选择", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        row1 = ttk.Frame(top_frame)
        row1.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(row1, text="输入目录:").pack(side=tk.LEFT, padx=(0, 5))
        self.input_dir_var = tk.StringVar(value="examples/cad_files")
        ttk.Entry(row1, textvariable=self.input_dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row1, text="浏览", command=self._browse_input).pack(side=tk.LEFT, padx=(5, 0))

        row2 = ttk.Frame(top_frame)
        row2.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(row2, text="输出目录:").pack(side=tk.LEFT, padx=(0, 5))
        self.output_dir_var = tk.StringVar(value="examples/output")
        ttk.Entry(row2, textvariable=self.output_dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="浏览", command=self._browse_output).pack(side=tk.LEFT, padx=(5, 0))

        # 参数配置与处理控制
        param_frame = ttk.LabelFrame(self, text="参数配置 / 处理控制", padding=10)
        param_frame.pack(fill=tk.X, padx=10, pady=5)

        row3 = ttk.Frame(param_frame)
        row3.pack(fill=tk.X, pady=(0, 8))
        self.height_label = ttk.Label(row3, text="基础模式拉伸高度 (mm):")
        self.height_label.pack(side=tk.LEFT, padx=(0, 5))
        self.height_var = tk.DoubleVar(value=self.app_config.get('processing', 'basic_default_height', default=10.0))
        self.height_spinbox = ttk.Spinbox(
            row3,
            from_=0.5,
            to=200,
            increment=0.5,
            textvariable=self.height_var,
            width=8,
        )
        self.height_spinbox.pack(side=tk.LEFT)

        ttk.Label(row3, text="处理模式:").pack(side=tk.LEFT, padx=(20, 5))
        self.mode_var = tk.StringVar(value="intelligent")
        self.mode_hint_var = tk.StringVar()
        ttk.Radiobutton(row3, text="智能模式", variable=self.mode_var, value="intelligent").pack(side=tk.LEFT)
        ttk.Radiobutton(row3, text="基础模式", variable=self.mode_var, value="basic").pack(side=tk.LEFT, padx=(10, 0))
        self.mode_var.trace_add("write", self._sync_height_controls)
        self._sync_height_controls()

        self.mode_hint_label = ttk.Label(param_frame, textvariable=self.mode_hint_var, foreground="gray")
        self.mode_hint_label.pack(fill=tk.X, pady=(4, 0))
        self._sync_mode_hint()

        control_row = ttk.Frame(param_frame)
        control_row.pack(fill=tk.X)
        control_row.grid_columnconfigure(3, weight=1, minsize=60)

        self.process_btn = ttk.Button(control_row, text="开始处理", width=12, command=self._start_processing)
        self.process_btn.grid(row=0, column=0, sticky=tk.W, padx=(0, 8))

        self.pause_btn = ttk.Button(control_row, text="暂停", width=8, command=self._toggle_pause, state="disabled")
        self.pause_btn.grid(row=0, column=1, sticky=tk.W, padx=(0, 6))

        self.cancel_btn = ttk.Button(control_row, text="取消", width=8, command=self._cancel_processing, state="disabled")
        self.cancel_btn.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(control_row, variable=self.progress_var, maximum=100, length=120)
        self.progress_bar.grid(row=0, column=3, sticky=tk.EW, padx=(0, 10))

        self.progress_label = tk.StringVar(value="就绪")
        ttk.Label(control_row, textvariable=self.progress_label, foreground="gray", width=12).grid(
            row=0, column=4, sticky=tk.W
        )

        secondary_row = ttk.Frame(param_frame)
        secondary_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(secondary_row, text="打开STEP模型", width=14, command=self.on_open_step).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(secondary_row, text="打开输出目录", width=14, command=self.on_open_output).pack(
            side=tk.RIGHT
        )
        self.stage_confirmation_var = tk.BooleanVar(
            value=self.app_config.get('processing', 'confirm_llm_stages', default=True)
        )
        ttk.Checkbutton(
            secondary_row,
            text="逐阶段确认",
            variable=self.stage_confirmation_var,
        ).pack(side=tk.LEFT)

        # 文件列表
        list_frame = ttk.LabelFrame(self, text="CAD 文件列表", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        list_toolbar = ttk.Frame(list_frame)
        list_toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(list_toolbar, text="预览选中", width=12, command=self._preview_selected).pack(
            side=tk.RIGHT
        )
        ttk.Button(list_toolbar, text="刷新列表", width=12, command=self._refresh_files).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        content_row = ttk.Frame(list_frame)
        content_row.pack(fill=tk.BOTH, expand=True)

        columns = ("filename", "type", "path")
        self.file_tree = ttk.Treeview(content_row, columns=columns, show="headings", height=6)
        self.file_tree.configure(height=6)
        self.file_tree.heading("filename", text="文件名")
        self.file_tree.heading("type", text="类型")
        self.file_tree.heading("path", text="路径")
        self.file_tree.column("filename", width=120)
        self.file_tree.column("type", width=45)
        self.file_tree.column("path", width=240)

        fsb = ttk.Scrollbar(content_row, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=fsb.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fsb.pack(side=tk.LEFT, fill=tk.Y)

        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_selected)
        self.file_tree.bind("<Double-1>", lambda _event: self._preview_selected())

    def _browse_input(self):
        path = filedialog.askdirectory(title="选择输入目录", initialdir=self.input_dir_var.get())
        if path:
            self.input_dir_var.set(path)
            self._refresh_files()

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir_var.get())
        if path:
            self.output_dir_var.set(path)

    def _refresh_files(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        input_dir = Path(self.input_dir_var.get())
        if not input_dir.exists():
            return

        seen_paths = set()
        cad_files = []
        for f in input_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in {".dxf", ".dwg"}:
                continue
            file_key = str(f.resolve()).lower()
            if file_key in seen_paths:
                continue
            seen_paths.add(file_key)
            cad_files.append(f)

        for f in sorted(cad_files, key=lambda path: path.name.lower()):
            self.file_tree.insert("", tk.END, values=(f.name, f.suffix.upper(), str(f)))

    def _on_file_selected(self, event):
        pass

    def _preview_selected(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo(
                "请选择图纸",
                "请先在左侧 CAD 文件列表中单击选择一张 DXF 或 DWG 图纸，"
                "然后再点击“预览选中”。"
            )
            return
        if self.preview_fig is None or self.preview_canvas is None:
            messagebox.showinfo(
                "预览区未就绪",
                "右侧图纸预览画布还没有初始化完成，请稍等片刻后重试。"
            )
            return

        filepath = self.file_tree.item(selected[0], "values")[2]
        title = Path(filepath).stem
        preview_path = self._find_preview(filepath)

        if preview_path:
            self._show_preview_image(preview_path, title)
            return

        self._generate_and_show_preview(filepath)

    def _find_preview(self, filepath: str) -> str:
        """查找统一预览缓存目录中的 PNG；旧 output 位置仅作兼容读取。"""
        from src.utils.preview_cache import get_preview_cache_path

        shared_preview = get_preview_cache_path(filepath)
        if shared_preview.exists() and shared_preview.stat().st_size >= 500:
            return str(shared_preview)
        return ""

    def _generate_and_show_preview(self, filepath: str):
        """通过 CADParser.visualize() 生成 PNG，再显示到右侧预览画布。"""
        try:
            from src.cad_parser import CADParser
            from src.utils import load_config
            from src.utils.preview_cache import get_preview_cache_path

            config = load_config()
            dxf_config = dict(config.get("dxf_parser", {}))
            dxf_config["output_dir"] = str(get_preview_cache_path(filepath).parent)

            logger.info(f"正在生成预览: {Path(filepath).name} ...")
            parser = CADParser(filepath, dxf_config)
            parser.parse()

            if len(getattr(parser, "entities", [])) == 0:
                logger.warning(f"预览: {Path(filepath).name} 未提取到实体，图纸可能为空或格式不支持")
                messagebox.showinfo(
                    "无法生成预览",
                    "这张图纸没有提取到可显示的实体。\n\n"
                    "可能原因：\n"
                    "1. 图纸为空或只包含暂不支持的实体类型。\n"
                    "2. DWG 转换未成功。\n"
                    "3. 图纸内容在布局空间而不是模型空间。\n\n"
                    "建议：先确认图纸能在 CAD 软件中正常打开，或尝试换一张 DXF 文件预览。"
                )
                return

            stem = Path(filepath).stem
            preview_path = get_preview_cache_path(filepath)

            parser.visualize(str(preview_path))
            self._show_preview_image(str(preview_path), stem)
            logger.info(f"预览已更新: {Path(filepath).name} -> {preview_path}")
        except Exception as e:
            logger.error(f"预览失败: {e}")
            messagebox.showerror(
                "图纸预览失败",
                f"生成图纸预览时发生错误：\n{e}\n\n"
                "请检查：\n"
                "1. 文件路径是否存在。\n"
                "2. DXF/DWG 文件是否损坏。\n"
                "3. 如果是 DWG，LibreDWG 路径是否已正确配置。"
            )

    def _show_preview_image(self, path: str, title: str = ""):
        """在增强版 GUI 的现有 Tk 画布中显示缓存/生成的 PNG 预览图。"""
        try:
            import matplotlib.image as mpimg

            img = mpimg.imread(path)
            self.preview_fig.clf()

            ax = self.preview_fig.add_axes([0, 0, 1, 0.94])
            ax.axis("off")
            ax.imshow(img, aspect="equal")

            if title:
                self.preview_fig.suptitle(title, fontsize=11, y=0.98)

            self.preview_canvas.draw()
        except Exception as e:
            logger.error(f"显示预览失败: {e}")
            messagebox.showerror(
                "预览图片显示失败",
                f"预览图片已生成，但显示到界面时出错：\n{e}\n\n"
                "可以到输出目录中查看对应的 PNG 预览图。"
            )

    def _toggle_pause(self):
        if not self._processing:
            return
        if self._paused:
            self._paused = False
            self._pause_event.set()
            self.pause_btn.configure(text="暂停")
            self.progress_label.set("继续处理中...")
            logger.info("处理已继续")
        else:
            self._paused = True
            self._pause_event.clear()
            self.pause_btn.configure(text="继续")
            self.progress_label.set("已暂停")
            logger.info("处理已暂停，当前阶段结束后会停在下一步")

    def _cancel_processing(self):
        if not self._processing:
            return
        if not messagebox.askyesno("取消处理", "确定要取消当前图纸处理任务吗？当前正在执行的外部调用会在返回后停止后续步骤。"):
            return
        self._cancel_event.set()
        self._paused = False
        self._pause_event.set()
        self.pause_btn.configure(text="暂停", state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.progress_label.set("正在取消...")
        logger.warning("已请求取消处理，等待当前阶段结束")

    def _check_control_state(self, stage: str = ""):
        while not self._pause_event.is_set():
            if self._cancel_event.is_set():
                raise ProcessingCancelled("处理已取消")
            time.sleep(0.1)
        if self._cancel_event.is_set():
            raise ProcessingCancelled("处理已取消")
        if stage:
            logger.debug(f"继续处理阶段: {stage}")

    def _start_processing(self):
        if self._processing:
            messagebox.showinfo(
                "任务正在处理中",
                "当前已有图纸处理任务在运行，请等待进度条完成后再开始新的任务。"
            )
            return

        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo(
                "请选择要处理的图纸",
                "请先在 CAD 文件列表中选择一张图纸，再点击“开始处理”。"
            )
            return

        filepath = self.file_tree.item(selected[0], "values")[2]
        mode = self.mode_var.get()
        height = self.height_var.get()

        self._processing = True
        self._awaiting_clarification = False
        self._paused = False
        self._cancel_event.clear()
        self._pause_event.set()
        self.process_btn.configure(state="disabled", text="处理中...")
        self.pause_btn.configure(state="normal", text="暂停")
        self.cancel_btn.configure(state="normal")
        self.progress_var.set(0)
        self.progress_label.set("准备中...")
        if mode == "basic":
            logger.info(f"开始处理: {Path(filepath).name} (模式: {mode}, 拉伸高度: {height}mm)")
        else:
            logger.info(f"开始处理: {Path(filepath).name} (模式: {mode})")

        thread = threading.Thread(target=self._run_processing, args=(filepath, mode, height), daemon=True)
        thread.start()

    def _run_processing(self, filepath: str, mode: str, height: float):
        start_time = time.time()
        try:
            self._check_control_state("start")
            config = self._load_config()
            from src.batch_processor import CADPipeline

            input_dir = str(Path(filepath).parent)
            output_dir = self.output_dir_var.get()

            self.pipeline = CADPipeline(config=config, input_dir=input_dir, output_dir=output_dir)
            self.pipeline.set_output_dir(output_dir)

            self._update_progress(10, "解析中...")

            self._check_control_state("pipeline-ready")

            if mode != "basic":
                if mode != "intelligent":
                    logger.warning(f"未知处理模式 {mode!r}，默认使用智能模式")
                logger.info("使用智能分析模式（AI视图校正 + AI脚本建模）")
                self.pipeline.processor.process_with_intelligent_analysis = self._wrap_intelligent(
                    self.pipeline.processor.process_with_intelligent_analysis)
                self._check_control_state("before-intelligent-processing")
                result = self.pipeline.process_file_intelligent(filepath)
            else:
                logger.info("使用基础模式（直接按平面图拉伸，不调用 AI 脚本建模）")
                self._check_control_state("before-basic-processing")
                result = self.pipeline.process_file(filepath, height, enable_analysis=False)

            self._update_progress(90, "完成，正在生成报告...")

            self._check_control_state("processing-finished")
            elapsed = time.time() - start_time
            if result.success:
                result_mode = getattr(result, "mode", None) or mode
                result_path = getattr(result, "modeling_path", None) or "unknown"
                logger.info(
                    f"处理成功 | 耗时: {elapsed:.1f}s | 实体数: {result.entity_count} | "
                    f"模式: {result_mode} | 建模路径: {result_path}"
                )
                if result.output_paths:
                    for k, v in result.output_paths.items():
                        logger.info(f"输出产物 [{k}]: {v}")
                self.after(0, lambda: self.progress_label.set(f"完成 ({elapsed:.1f}s)"))
                self.after(0, lambda: self.progress_var.set(100))
            elif getattr(result, "status", None) and getattr(result.status, "value", "") == "needs_clarification":
                self._awaiting_clarification = True
                logger.info(f"处理需要澄清 | 耗时: {elapsed:.1f}s | 问题数: {len(result.clarification_questions)}")
                self.after(0, lambda: self.progress_label.set("等待澄清"))
                self.after(0, lambda r=result, s=start_time: self._show_clarification_dialog(r, s))
                return
            elif getattr(result, "status", None) and getattr(result.status, "value", "") == "stopped_by_user":
                logger.info(f"用户停止处理 | 耗时: {elapsed:.1f}s | {result.error_message}")
                self.after(0, lambda: self.progress_label.set("已停止"))
            else:
                logger.error(f"处理失败 | 耗时: {elapsed:.1f}s | 错误: {result.error_message}")
                self.after(0, lambda: self.progress_label.set("失败"))
                self.after(0, lambda: messagebox.showerror(
                    "图纸处理失败",
                    f"文件处理失败：\n{result.error_message}\n\n"
                    "建议检查：\n"
                    "1. FreeCAD 是否可用。\n"
                    "2. 输出目录是否可写。\n"
                    "3. 图纸是否包含可建模的封闭轮廓。"))
        except ProcessingCancelled:
            elapsed = time.time() - start_time
            logger.warning(f"处理已取消 | 耗时: {elapsed:.1f}s")
            self.after(0, lambda: self.progress_label.set("已取消"))
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"处理异常 | 耗时: {elapsed:.1f}s | {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror(
                "处理过程出现异常",
                f"程序在处理图纸时遇到未预期错误：\n{e}\n\n"
                "详细错误已写入下方“处理日志”，请复制日志用于排查。"))
        finally:
            if self._awaiting_clarification:
                self._processing = False
                self._paused = False
                self._pause_event.set()
                self.after(0, lambda: self.pause_btn.configure(state="disabled", text="暂停"))
                self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
                return
            self._processing = False
            self._paused = False
            self._pause_event.set()
            self.after(0, lambda: self.process_btn.configure(state="normal", text="开始处理"))
            self.after(0, lambda: self.pause_btn.configure(state="disabled", text="暂停"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _show_clarification_dialog(self, result, start_time: float):
        questions = result.clarification_questions or []
        if not questions:
            messagebox.showwarning("需要澄清", "当前任务需要澄清，但没有可展示的问题。")
            return

        dialog = tk.Toplevel(self)
        dialog.title("需要用户澄清")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text="系统需要先确认以下信息，才能继续智能建模：",
            font=("", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 10))

        answer_vars = {}
        for question in questions:
            block = ttk.Frame(body)
            block.pack(fill=tk.X, pady=(0, 10))
            ttk.Label(block, text=question.get("text", "请补充信息")).pack(anchor=tk.W)
            kind = question.get("kind")
            options = question.get("options", []) or []
            if kind == "single_choice" and options:
                display_to_value = {}
                values = []
                for option in options:
                    if isinstance(option, dict):
                        display = str(option.get("label") or option.get("value"))
                        value = str(option.get("value"))
                    else:
                        display = str(option)
                        value = display
                    display_to_value[display] = value
                    values.append(display)
                var = tk.StringVar(value=values[0])
                var._cad_value_map = display_to_value
                combo = ttk.Combobox(block, textvariable=var, state="readonly", values=values, width=36)
                combo.pack(anchor=tk.W, pady=(4, 0))
            else:
                var = tk.StringVar()
                ttk.Entry(block, textvariable=var, width=28).pack(anchor=tk.W, pady=(4, 0))
            answer_vars[question.get("id")] = var

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(4, 0))

        def submit():
            answers = {
                question_id: getattr(var, "_cad_value_map", {}).get(var.get(), var.get()).strip()
                for question_id, var in answer_vars.items()
                if question_id and var.get().strip()
            }
            if len(answers) != len(answer_vars):
                messagebox.showinfo("还差一点", "请先回答所有问题。", parent=dialog)
                return
            dialog.destroy()
            self._resume_after_clarification(result, answers, start_time)

        def cancel_dialog():
            self._awaiting_clarification = False
            self.process_btn.configure(state="normal", text="开始处理")
            self.progress_label.set("已取消澄清")
            dialog.destroy()

        ttk.Button(action_row, text="继续建模", command=submit).pack(side=tk.RIGHT)
        ttk.Button(action_row, text="取消", command=cancel_dialog).pack(side=tk.RIGHT, padx=(0, 8))

        self._center_dialog(dialog)
        dialog.protocol("WM_DELETE_WINDOW", cancel_dialog)

    def _center_dialog(self, dialog: tk.Toplevel) -> None:
        """Center a child dialog over the main application window."""
        dialog.update_idletasks()
        parent = self.winfo_toplevel()
        parent.update_idletasks()

        width = max(dialog.winfo_width(), dialog.winfo_reqwidth())
        height = max(dialog.winfo_height(), dialog.winfo_reqheight())
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
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _confirm_llm_stage(self, stage: str, payload: Dict[str, Any]) -> bool:
        """Worker-thread bridge for modal stage review in Tk's main thread."""
        if not getattr(self, "stage_confirmation_var", None) or not self.stage_confirmation_var.get():
            return True
        if self._cancel_event.is_set():
            return False

        completed = threading.Event()
        outcome = {"continue": False}
        self.after(0, lambda: self._show_stage_confirmation_dialog(stage, payload, outcome, completed))

        while not completed.wait(0.1):
            if self._cancel_event.is_set():
                return False
        return bool(outcome["continue"])

    def _show_stage_confirmation_dialog(
        self,
        stage: str,
        payload: Dict[str, Any],
        outcome: Dict[str, bool],
        completed: threading.Event,
    ) -> None:
        stage_titles = {
            "view_analysis": "视图语义校正",
            "semantic_reconstruction": "零件语义重建",
        }
        title = stage_titles.get(stage, stage)

        dialog = tk.Toplevel(self)
        dialog.title(f"{title}完成")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.minsize(520, 360)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text=f"{title}已完成，请查看汇报后继续。",
            font=("", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        report_text = tk.Text(body, height=14, width=72, wrap=tk.WORD)
        report_text.pack(fill=tk.BOTH, expand=True)
        report_text.insert("1.0", self._build_stage_report(stage, payload))
        report_text.configure(state="disabled")

        ttk.Label(
            body,
            text="选择“停止”会结束本次处理，但保留已完成阶段的结果供查看。",
        ).pack(anchor=tk.W, pady=(10, 0))

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(10, 0))

        def continue_stage():
            outcome["continue"] = True
            completed.set()
            dialog.destroy()

        def stop_stage():
            outcome["continue"] = False
            completed.set()
            dialog.destroy()

        ttk.Button(action_row, text="继续", command=continue_stage).pack(side=tk.RIGHT)
        ttk.Button(action_row, text="停止", command=stop_stage).pack(side=tk.RIGHT, padx=(0, 8))
        self._center_dialog(dialog)
        dialog.protocol("WM_DELETE_WINDOW", stop_stage)

    def _build_stage_report(self, stage: str, payload: Dict[str, Any]) -> str:
        if stage == "view_analysis":
            return self._build_view_stage_report(payload)
        if stage == "semantic_reconstruction":
            return self._build_semantic_stage_report(payload)
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    def _build_view_stage_report(self, payload: Dict[str, Any]) -> str:
        view = payload.get("view_analysis") or {}
        dimensions = payload.get("dimension_data") or {}
        policy = payload.get("semantic_policy") or {}
        questions = policy.get("clarification_questions") or []

        lines = [
            "阶段：视图语义校正",
            f"图纸类型：{view.get('drawing_type', 'unknown')}",
            f"置信度：{view.get('confidence', 'unknown')}",
            f"识别视图数：{len(view.get('views') or [])}",
            f"尺寸标注数：{len(dimensions.get('dimensions') or dimensions.get('extracted_dimensions') or [])}",
        ]
        if questions:
            lines.append(f"继续后将先补充信息：{len(questions)} 个追问")
            lines.append("建议动作：继续后先回答追问，再决定是否进入下一阶段。")

        warnings = view.get("warnings") or []
        if warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {item}" for item in warnings[:8])

        views = view.get("views") or []
        if views:
            lines.extend(["", "视图摘要:"])
            for item in views[:8]:
                name = item.get("name") or item.get("view_name") or "unknown"
                view_type = item.get("type") or item.get("view_type") or item.get("projection_type") or "unknown"
                confidence = item.get("confidence", "unknown")
                lines.append(f"- {name}: {view_type}, confidence={confidence}")

        if questions:
            lines.extend(["", "即将追问:"])
            for question in questions[:5]:
                lines.append(f"- {question.get('text', '请补充信息')}")
        return "\n".join(lines)

    def _build_semantic_stage_report(self, payload: Dict[str, Any]) -> str:
        semantics = payload.get("part_semantics") or {}
        policy = payload.get("semantic_policy") or {}
        confidence = semantics.get("confidence", "unknown")
        lines = [
            "阶段：零件语义重建",
            f"零件类型：{semantics.get('part_type', 'unknown')}",
            f"置信度：{confidence}",
            f"摘要：{semantics.get('summary', '')}",
            f"尺寸来源：{semantics.get('dimension_source') or policy.get('dimension_source', 'unknown')}",
        ]
        try:
            if float(confidence) < 0.7:
                lines.append("建议动作：当前置信度较低，建议先检查汇报再决定是否继续。")
        except (TypeError, ValueError):
            pass

        for title, key in (
            ("关键尺寸", "key_dimensions"),
            ("基础特征", "base_features"),
            ("增材特征", "additive_features"),
            ("减材特征", "subtractive_features"),
            ("不确定点", "uncertainties"),
            ("Warnings", "warnings"),
        ):
            items = semantics.get(key) or []
            if not items:
                continue
            lines.extend(["", f"{title}:"])
            for item in items[:8]:
                if isinstance(item, dict):
                    lines.append(f"- {json.dumps(item, ensure_ascii=False, default=str)}")
                else:
                    lines.append(f"- {item}")
        return "\n".join(lines)

    def _resume_after_clarification(self, result, answers: Dict[str, str], start_time: float):
        self._processing = True
        self._awaiting_clarification = False
        self.process_btn.configure(state="disabled", text="处理中...")
        self.pause_btn.configure(state="normal", text="暂停")
        self.cancel_btn.configure(state="normal")
        self.progress_label.set("根据澄清继续...")
        logger.info("已收到用户澄清，继续智能建模")

        thread = threading.Thread(
            target=self._run_clarification_resume,
            args=(result, answers, start_time),
            daemon=True,
        )
        thread.start()

    def _run_clarification_resume(self, result, answers: Dict[str, str], start_time: float):
        try:
            self._check_control_state("before-clarification-resume")
            resumed = self.pipeline.continue_file_with_clarification(result, answers)
            elapsed = time.time() - start_time
            if resumed.success:
                logger.info(f"澄清后处理成功 | 总耗时: {elapsed:.1f}s | 实体数: {resumed.entity_count}")
                if resumed.output_paths:
                    for k, v in resumed.output_paths.items():
                        logger.info(f"输出产物 [{k}]: {v}")
                self.after(0, lambda: self.progress_label.set(f"完成 ({elapsed:.1f}s)"))
                self.after(0, lambda: self.progress_var.set(100))
            elif getattr(resumed, "status", None) and getattr(resumed.status, "value", "") == "needs_clarification":
                self._awaiting_clarification = True
                logger.info("澄清后仍需补充信息")
                self.after(0, lambda: self.progress_label.set("等待澄清"))
                self.after(0, lambda r=resumed, s=start_time: self._show_clarification_dialog(r, s))
                return
            elif getattr(resumed, "status", None) and getattr(resumed.status, "value", "") == "stopped_by_user":
                logger.info(f"用户停止处理 | 总耗时: {elapsed:.1f}s | {resumed.error_message}")
                self.after(0, lambda: self.progress_label.set("已停止"))
            else:
                logger.error(f"澄清后处理失败 | 总耗时: {elapsed:.1f}s | 错误: {resumed.error_message}")
                self.after(0, lambda: self.progress_label.set("失败"))
                self.after(0, lambda: messagebox.showerror(
                    "澄清后处理失败",
                    f"系统已收到补充信息，但继续建模仍失败：\n{resumed.error_message}"
                ))
        except ProcessingCancelled:
            elapsed = time.time() - start_time
            logger.warning(f"澄清后处理已取消 | 总耗时: {elapsed:.1f}s")
            self.after(0, lambda: self.progress_label.set("已取消"))
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"澄清后处理异常 | 总耗时: {elapsed:.1f}s | {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror(
                "澄清后处理异常",
                f"继续建模时发生未预期错误：\n{e}"
            ))
        finally:
            if self._awaiting_clarification:
                self._processing = False
                self._paused = False
                self._pause_event.set()
                self.after(0, lambda: self.pause_btn.configure(state="disabled", text="暂停"))
                self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
                return
            self._processing = False
            self._paused = False
            self._pause_event.set()
            self.after(0, lambda: self.process_btn.configure(state="normal", text="开始处理"))
            self.after(0, lambda: self.pause_btn.configure(state="disabled", text="暂停"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _wrap_intelligent(self, original_fn):
        def wrapped(file_path, output_structure, extrude_height):
            self._update_progress(30, "AI 分析中...")
            result = original_fn(file_path, output_structure, extrude_height)
            self._update_progress(70, "建模中...")
            return result
        return wrapped

    def _sync_height_controls(self, *_args):
        visible = self.mode_var.get() == "basic"
        if visible:
            self.height_label.pack(side=tk.LEFT, padx=(0, 5))
            self.height_spinbox.pack(side=tk.LEFT)
        else:
            self.height_label.pack_forget()
            self.height_spinbox.pack_forget()
        self._sync_mode_hint()

    def _sync_mode_hint(self):
        if self.mode_var.get() == "basic":
            self.mode_hint_var.set("基础模式仅负责平面拉伸；多视图或复杂图纸请使用智能模式。")
        else:
            self.mode_hint_var.set("智能模式负责识别图纸类型并选择建模路径。")

    def _load_config(self) -> Dict:
        config = {}
        try:
            from src.utils.config import load_config
            config = load_config()
        except Exception:
            pass
        config['cache_dir'] = self.app_config.get('cache', 'dir', default='.cache/analysis')
        config['cache_ttl'] = self.app_config.get('cache', 'default_ttl_days', default=7) * 86400
        if getattr(self, "stage_confirmation_var", None) and self.stage_confirmation_var.get():
            from src.utils.stage_confirmation import CallbackStageConfirmation
            config.setdefault("api", {}).setdefault("deepseek", {})[
                "_stage_confirmation"
            ] = CallbackStageConfirmation(self._confirm_llm_stage)
        return config

    def _update_progress(self, value: float, text: str):
        self.after(0, lambda: self.progress_var.set(value))
        self.after(0, lambda: self.progress_label.set(text))


class CADApplication(tk.Tk):
    """CAD 图纸 3D 建模系统 — 主窗口"""

    def __init__(self):
        super().__init__()

        self.title("CAD 图纸 3D 建模系统 v2.0")
        self.geometry("1100x850")
        self.minsize(900, 700)

        self.app_config = AppConfig()

        self.log_handler = GuiLogHandler(max_records=2000)
        self.log_handler.setLevel(logging.DEBUG)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self.log_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root_logger.addHandler(console_handler)

        self._build_menu()
        self._build_ui()
        self._init_pipeline()

        self.after(500, self._refresh_all)

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开 STEP 模型...", command=self._open_step_model, accelerator="Ctrl+O")
        file_menu.add_command(label="打开输出目录...", command=self._open_output_dir, accelerator="Ctrl+D")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="刷新缓存面板", command=self._refresh_cache)
        menubar.add_cascade(label="视图", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=lambda: messagebox.showinfo(
            "关于", "CAD 图纸 3D 建模系统 v2.0\n\n"
                     "基于 DeepSeek AI 的二维工程图智能分析与三维重建系统\n\n"
                     "功能：\n"
                     "- DXF/DWG 解析与可视化\n"
                     "- AI 智能视图分析与尺寸提取\n"
                     "- FreeCAD 自动建模与 STEP/STL 导出\n"
                     "- 缓存管理与日志分析"))
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)

        self.bind_all("<Control-o>", lambda e: self._open_step_model())
        self.bind_all("<Control-d>", lambda e: self._open_output_dir())

    def _build_ui(self):
        main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.main_paned = main_paned
        main_paned.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main_paned)
        main_paned.add(top_frame, weight=4)

        bottom_frame = ttk.Frame(main_paned, height=320)
        bottom_frame.pack_propagate(False)
        main_paned.add(bottom_frame, weight=1)

        top_paned = ttk.PanedWindow(top_frame, orient=tk.HORIZONTAL)
        top_paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(top_paned, width=480)
        top_paned.add(left_frame, weight=1)

        right_frame = ttk.Frame(top_paned, width=620)
        top_paned.add(right_frame, weight=1)

        preview_frame = ttk.LabelFrame(right_frame, text="图纸预览", padding=5)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'KaiTi', 'DejaVu Sans']
        matplotlib.rcParams['axes.unicode_minus'] = False

        self.preview_fig = plt.figure(figsize=(6, 5), dpi=100)
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, master=preview_frame)
        self.preview_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.processing_panel = ProcessingPanel(
            left_frame,
            self.app_config,
            on_open_step=self._open_step_model,
            on_open_output=self._open_output_dir,
            preview_fig=self.preview_fig,
            preview_canvas=self.preview_canvas,
        )
        self.processing_panel.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(bottom_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.log_panel = LogPanel(notebook, self.log_handler, self.app_config)
        notebook.add(self.log_panel, text="处理日志")

        self.llm_telemetry_panel = LLMTelemetryPanel(notebook, self.app_config)
        notebook.add(self.llm_telemetry_panel, text="大模型调用")

        self.cache_panel = CacheManagerPanel(notebook, self.app_config)
        notebook.add(self.cache_panel, text="缓存管理")

        self.after(100, self._set_initial_pane_sizes)
        self.after(500, self._set_initial_pane_sizes)
        self.after(1200, self._set_initial_pane_sizes)

    def _set_initial_pane_sizes(self):
        try:
            height = self.main_paned.winfo_height()
            if height > 0:
                self.main_paned.sashpos(0, max(360, height - 320))
        except Exception:
            pass

    def _apply_initial_pane_sizes(self):
        return

    def _init_pipeline(self):
        try:
            from src.batch_processor import CADPipeline
            config = {}
            try:
                from src.utils.config import load_config
                config = load_config()
            except Exception:
                pass
            self.pipeline = CADPipeline(
                config=config,
                input_dir=self.processing_panel.input_dir_var.get(),
                output_dir=self.processing_panel.output_dir_var.get(),
            )
            logger.info("处理管道初始化完成")
            logger.info(f"输入目录: {self.processing_panel.input_dir_var.get()}")
            logger.info(f"输出目录: {self.processing_panel.output_dir_var.get()}")
        except Exception as e:
            logger.warning(f"管道初始化失败（部分功能可能不可用）: {e}")

    def _refresh_all(self):
        self.processing_panel._refresh_files()
        self.cache_panel.refresh()

    def _refresh_cache(self):
        self.cache_panel.refresh()

    def _open_step_model(self):
        """打开 STEP 模型文件"""
        filepath = filedialog.askopenfilename(
            title="打开 STEP 模型",
            filetypes=[
                ("STEP 文件", "*.step *.stp *.STEP *.STP"),
                ("所有文件", "*.*"),
            ],
            initialdir=self.processing_panel.output_dir_var.get() or ".",
        )

        if not filepath:
            return

        filepath = os.path.abspath(filepath)
        logger.info(f"打开 STEP 模型: {filepath}")

        file_size = Path(filepath).stat().st_size
        logger.info(f"文件大小: {file_size / 1024:.1f} KB")

        try:
            lines = []
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f):
                    if i >= 200:
                        lines.append("... (文件较长，仅显示前 200 行)")
                        break
                    lines.append(line.rstrip())

            self._show_step_preview(lines, filepath)
        except Exception as e:
            logger.error(f"读取 STEP 文件失败: {e}")
            messagebox.showerror(
                "STEP 文件读取失败",
                f"无法读取所选 STEP 文件：\n{filepath}\n\n错误信息：\n{e}\n\n"
                "请确认文件没有被其他程序占用，并且文件内容是有效的 STEP 文本。"
            )

    def _show_step_preview(self, lines: list, filepath: str):
        preview_win = tk.Toplevel(self)
        preview_win.title(f"STEP 模型预览 - {Path(filepath).name}")
        preview_win.geometry("900x650")

        info_frame = ttk.Frame(preview_win)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(info_frame, text=f"文件: {filepath}", font=("", 9)).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text=f"大小: {Path(filepath).stat().st_size / 1024:.1f} KB  |  总行数: {len(lines)}",
            foreground="gray",
        ).pack(anchor=tk.W)

        text_frame = ttk.Frame(preview_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))

        text_widget = tk.Text(text_frame, wrap=tk.NONE, font=("Consolas", 9))
        vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        hsb = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=text_widget.xview)
        text_widget.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        text_widget.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        for line in lines:
            text_widget.insert(tk.END, line + "\n")
            if "CLOSED_SHELL" in line or "MANIFOLD_SOLID_BREP" in line or "ADVANCED_BREP_SHAPE_REPRESENTATION" in line:
                end_idx = text_widget.index(tk.END + "-2l")
                text_widget.tag_add("highlight", end_idx + " linestart", end_idx + " lineend")
        text_widget.tag_configure("highlight", background="#FFFF99", foreground="darkblue")
        text_widget.configure(state="disabled")

        ttk.Button(
            preview_win, text="关闭", command=preview_win.destroy
        ).pack(pady=(0, 10))

    def _open_output_dir(self):
        output_base = Path(self.processing_panel.output_dir_var.get() or "examples/output")
        if not output_base.exists():
            msg = (f"输出根目录不存在:\n{output_base.absolute()}\n\n"
                   "可能原因:\n"
                   "  • 尚未处理任何文件\n"
                   "  • 输出目录配置错误\n\n"
                   "是否手动选择目录？")
            if messagebox.askyesno("目录不存在", msg):
                path = filedialog.askdirectory(title="选择输出目录")
                if path:
                    self.processing_panel.output_dir_var.set(path)
                    output_base = Path(path)
                else:
                    return
            else:
                return

        subdirs = sorted(
            [d for d in output_base.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        if not subdirs:
            if messagebox.askyesno(
                    "提示",
                    f"输出目录下没有子文件夹:\n{output_base.absolute()}\n\n是否手动选择？",
            ):
                path = filedialog.askdirectory(title="选择输出目录")
                if path:
                    self.processing_panel.output_dir_var.set(path)
                    logger.info(f"输出目录已手动设置为: {path}")
            return

        latest = subdirs[0]
        target_dir = str(latest)

        if len(subdirs) > 1:
            choice_win = tk.Toplevel(self)
            choice_win.title("选择输出子目录")
            choice_win.geometry("500x350")

            ttk.Label(
                choice_win,
                text=f"共有 {len(subdirs)} 个输出目录，最近的是:",
                padding=10,
            ).pack()

            list_frame = ttk.Frame(choice_win)
            list_frame.pack(fill=tk.BOTH, expand=True, padx=10)

            tree = ttk.Treeview(list_frame, columns=("name", "mtime"), show="headings", height=10)
            tree.heading("name", text="目录名")
            tree.heading("mtime", text="修改时间")
            tree.column("name", width=300)
            tree.column("mtime", width=150)
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            for d in subdirs:
                mtime_str = datetime.fromtimestamp(d.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                tree.insert("", tk.END, values=(d.name, mtime_str))

            tree.selection_set(tree.get_children()[0])

            def on_select():
                nonlocal target_dir
                sel = tree.selection()
                if sel:
                    target_dir = str(output_base / tree.item(sel[0], "values")[0])
                choice_win.destroy()

            btn_frame = ttk.Frame(choice_win)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="打开选中目录", command=on_select).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="取消", command=choice_win.destroy).pack(side=tk.LEFT, padx=5)

            self.wait_window(choice_win)

        if target_dir:
            try:
                os.startfile(target_dir)
                logger.info(f"已打开输出目录: {target_dir}")
            except Exception as e:
                logger.error(f"打开目录失败: {e}")
                messagebox.showerror(
                    "输出目录打开失败",
                    f"无法打开输出目录：\n{target_dir}\n\n错误信息：\n{e}\n\n"
                    "请确认目录仍然存在，并且当前用户有访问权限。"
                )

    def _open_output_dir_manual(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.processing_panel.output_dir_var.set(path)
            logger.info(f"输出目录已设置为: {path}")


def main():
    app = CADApplication()
    app.mainloop()


if __name__ == "__main__":
    main()
