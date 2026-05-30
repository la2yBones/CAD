# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

import tkinter as tk
from tkinter import ttk, messagebox

from src.batch_processor import PendingClarificationStore
from src.batch_processor.pending_view_model import (
    build_pending_item_detail,
    pending_recovery_type,
)

logger = logging.getLogger(__name__)

__all__ = ["PendingClarificationPanel"]


class PendingClarificationPanel(ttk.Frame):
    """GUI view for persisted batch clarification items."""

    def __init__(self, parent, on_resume: Callable[[Dict[str, Any]], None], **kwargs):
        super().__init__(parent, **kwargs)
        self.on_resume = on_resume
        self.pending_store = PendingClarificationStore()
        self._checked_pending_items = set()
        self._build_ui()

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        toolbar.grid_columnconfigure(2, weight=1)
        ttk.Button(toolbar, text="全选", width=8, command=self._select_all).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(toolbar, text="清空选择", width=10, command=self._clear_selection).grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Button(toolbar, text="刷新", width=10, command=self.refresh).grid(row=0, column=3, sticky=tk.E, padx=(0, 8))
        ttk.Button(toolbar, text="删除选中", width=12, command=self._delete_selected).grid(row=0, column=4, sticky=tk.E, padx=(0, 8))
        ttk.Button(toolbar, text="继续选中", width=12, command=self._resume_selected).grid(row=0, column=5, sticky=tk.E)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        columns = ("checked", "file", "type", "questions", "updated", "path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=6, selectmode="extended")
        self.tree.heading("checked", text="选择")
        self.tree.heading("file", text="图纸")
        self.tree.heading("type", text="恢复类型")
        self.tree.heading("questions", text="问题数")
        self.tree.heading("updated", text="更新时间")
        self.tree.heading("path", text="路径")
        self.tree.column("checked", width=34, anchor=tk.CENTER, stretch=False)
        self.tree.column("file", width=120)
        self.tree.column("type", width=95, anchor=tk.CENTER)
        self.tree.column("questions", width=55, anchor=tk.CENTER)
        self.tree.column("updated", width=130)
        self.tree.column("path", width=210)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", lambda _event: self._resume_selected())
        self.tree.bind("<Delete>", lambda _event: self._delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_detail())

        detail_frame = ttk.LabelFrame(self, text="任务详情", padding=6)
        detail_frame.pack(fill=tk.BOTH, expand=True)
        self.detail_text = tk.Text(detail_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scrollbar = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self._set_detail_text(build_pending_item_detail(None))

    def refresh(self):
        checked_ids = set(self._checked_pending_items)
        selected_ids = set(self.tree.selection())
        pending_ids = set()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._checked_pending_items.clear()
        for item in self.pending_store.list_pending():
            input_file = item.get("input_file", "")
            pending_id = item.get("pending_id")
            pending_ids.add(pending_id)
            checked = pending_id in checked_ids
            self.tree.insert(
                "",
                tk.END,
                iid=pending_id,
                values=(
                    "☑" if checked else "☐",
                    Path(input_file).name,
                    pending_recovery_type(item),
                    len(item.get("clarification_questions") or []),
                    item.get("updated_at", ""),
                    input_file,
                ),
            )
            if checked:
                self._checked_pending_items.add(pending_id)
            if pending_id in selected_ids:
                self.tree.selection_add(pending_id)
        self._checked_pending_items.intersection_update(pending_ids)
        for selected_id in selected_ids - pending_ids:
            self.tree.selection_remove(selected_id)
        self._update_detail()

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return "break"
        self._toggle_checked(item)
        return "break"

    def _toggle_checked(self, item: str):
        values = list(self.tree.item(item, "values"))
        if len(values) < 6:
            return
        if item in self._checked_pending_items:
            self._checked_pending_items.remove(item)
            values[0] = "☐"
        else:
            self._checked_pending_items.add(item)
            values[0] = "☑"
        self.tree.item(item, values=values)
        self._update_detail()

    def _select_all(self):
        children = self.tree.get_children()
        self._checked_pending_items = set(children)
        for item in children:
            values = list(self.tree.item(item, "values"))
            if values:
                values[0] = "☑"
                self.tree.item(item, values=values)

    def _clear_selection(self):
        for item in list(self._checked_pending_items):
            if item in self.tree.get_children():
                values = list(self.tree.item(item, "values"))
                if values:
                    values[0] = "☐"
                    self.tree.item(item, values=values)
        self._checked_pending_items.clear()
        self.tree.selection_remove(self.tree.selection())
        self._update_detail()

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state=tk.DISABLED)

    def _update_detail(self) -> None:
        selected = self._selected_pending_ids()
        if len(selected) != 1:
            self._set_detail_text(build_pending_item_detail(None))
            return
        item = self.pending_store.load(selected[0])
        self._set_detail_text(build_pending_item_detail(item))

    def _selected_pending_ids(self) -> List[str]:
        children = self.tree.get_children()
        checked = [item for item in children if item in self._checked_pending_items]
        if checked:
            return checked
        return [item for item in self.tree.selection() if item in children]

    def _resume_selected(self):
        selected = self._selected_pending_ids()
        if not selected:
            messagebox.showinfo("请选择待恢复任务", "请先选择一条待恢复图纸任务。")
            return
        if len(selected) > 1:
            messagebox.showinfo("一次恢复一条", "待恢复任务需要逐条补充信息，请先只选择一条任务。")
            return
        item = self.pending_store.load(selected[0])
        if not item:
            messagebox.showwarning("待恢复任务不存在", "该待恢复任务可能已被处理或移除。")
            self.refresh()
            return
        self._checked_pending_items.discard(selected[0])
        self.tree.selection_remove(selected[0])
        self.on_resume(item)

    def _delete_selected(self):
        selected = self._selected_pending_ids()
        if not selected:
            messagebox.showinfo("请选择待恢复任务", "请先选择要删除的待恢复任务。")
            return
        if not messagebox.askyesno("删除待恢复任务", f"确定删除选中的 {len(selected)} 条待恢复任务吗？"):
            return

        deleted = 0
        for pending_id in selected:
            if self.pending_store.mark_deleted(pending_id):
                deleted += 1
        self._checked_pending_items.difference_update(selected)
        self.refresh()
        messagebox.showinfo("删除完成", f"已删除 {deleted} 条待恢复任务。")
