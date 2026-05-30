# -*- coding: utf-8 -*-

import logging
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

from src.utils.cache import AnalysisCache
from src.gui.helpers import AppConfig

logger = logging.getLogger(__name__)

__all__ = ["CacheManagerPanel"]


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
        list_frame.pack(fill=tk.X, expand=False, padx=5, pady=(0, 5))

        header_frame = ttk.Frame(list_frame)
        header_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(header_frame, text="缓存条目", font=("", 9, "bold")).pack(side=tk.LEFT)
        self.stats_summary_var = tk.StringVar(value="条目数: -- | 总大小: -- | 已过期: --")
        ttk.Label(header_frame, textvariable=self.stats_summary_var, foreground="darkblue").pack(side=tk.RIGHT)

        columns = ("source_file", "size", "timestamp", "status")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            height=5,
            selectmode="extended",
        )
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
        row.grid_columnconfigure(1, weight=1)

        cache_dir = self.app_config.get('cache', 'dir', default='.cache/analysis')
        ttk.Label(row, text="缓存目录:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Label(
            row,
            text=cache_dir,
            foreground="gray",
            anchor=tk.W,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(0, 14))

        ttk.Label(row, text="过期时间:").grid(row=0, column=2, sticky=tk.E, padx=(0, 5))
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
        ttl_combo.grid(row=0, column=3, sticky=tk.E, padx=(0, 8))
        ttk.Button(row, text="应用", command=self._apply_ttl).grid(row=0, column=4, sticky=tk.E, padx=(0, 6))
        ttk.Button(row, text="清理过期", command=self._clear_expired).grid(row=0, column=5, sticky=tk.E)

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

    def _selected_cache_entries(self):
        return [
            self._entry_by_item.get(item_id, {})
            for item_id in self.tree.selection()
        ]

    def _delete_cache_entries(self, entries) -> int:
        cache = self._get_cache()
        if cache is None:
            return 0
        count = 0
        for entry in entries:
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
        return count

    def _delete_selected(self):
        selected_entries = self._selected_cache_entries()
        if not selected_entries:
            messagebox.showinfo("提示", "请先选择要删除的缓存条目")
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(selected_entries)} 个缓存条目？"):
            return

        count = self._delete_cache_entries(selected_entries)
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
