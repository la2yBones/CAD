# -*- coding: utf-8 -*-
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging

from .batch_progress import ProcessingCancelled, BatchProgressWindow
from .helpers import (
    AppConfig,
    format_stage_supervision_message,
    stage_self_correction_log_lines,
)
from .pending_panel import PendingClarificationPanel
from src.reconstruction.clarification import (
    build_candidate_clarification_summary,
    clarification_option_label,
    clarification_option_value,
    is_candidate_clarification_question,
)
from src.batch_processor.pending_view_model import (
    pending_recovery_summary,
    pending_recovery_type,
)
from src.utils.deepseek_gui_config import apply_gui_runtime_overrides

logger = logging.getLogger(__name__)

__all__ = ["ProcessingPanel"]


class ProcessingPanel(ttk.Frame):
    """处理面板 — 文件选择、参数配置、处理控制"""

    def __init__(self, parent, app_config: AppConfig, on_open_step: Callable, on_open_output: Callable,
                 on_pending_changed: Optional[Callable[[], None]] = None,
                 preview_fig=None, preview_canvas=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_config = app_config
        self.on_open_step = on_open_step
        self.on_open_output = on_open_output
        self.on_pending_changed = on_pending_changed
        self.preview_fig = preview_fig
        self.preview_canvas = preview_canvas
        self.pipeline = None
        self._processing = False
        self._awaiting_clarification = False
        self._paused = False
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        from src.batch_processor import PendingClarificationStore
        self.pending_store = PendingClarificationStore()
        self._checked_file_items = set()
        self._batch_progress_items: Dict[str, Dict[str, Any]] = {}
        self._batch_progress_window: Optional[BatchProgressWindow] = None
        self._batch_output_dir = ""
        self._batch_progress_button = None
        self._active_batch_item_id: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        self.input_dir_var = tk.StringVar(value="examples/cad_files")
        self.output_dir_var = tk.StringVar(
            value=self.app_config.get('output', 'base_dir', default="examples/output")
        )

        param_frame = ttk.LabelFrame(self, text="参数配置 / 处理控制", padding=10)
        param_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        row3 = ttk.Frame(param_frame)
        row3.pack(fill=tk.X, pady=(0, 8))
        self.height_var = tk.DoubleVar(value=self.app_config.get('processing', 'basic_default_height', default=10.0))

        control_row = ttk.Frame(param_frame)
        control_row.pack(fill=tk.X)
        control_row.grid_columnconfigure(4, weight=1, minsize=60)

        self.process_btn = ttk.Button(control_row, text="开始处理", width=12, command=self._start_processing)
        self.process_btn.grid(row=0, column=0, sticky=tk.W, padx=(0, 8))

        self.pause_btn = ttk.Button(control_row, text="暂停", width=8, command=self._toggle_pause, state="disabled")
        self.pause_btn.grid(row=0, column=1, sticky=tk.W, padx=(0, 6))

        self.cancel_btn = ttk.Button(control_row, text="取消", width=8, command=self._cancel_processing, state="disabled")
        self.cancel_btn.grid(row=0, column=2, sticky=tk.W, padx=(0, 10))

        self._batch_progress_button = ttk.Button(
            control_row,
            text="查看批量进度",
            width=14,
            command=self._show_batch_progress_window,
            state="disabled",
        )
        self._batch_progress_button.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(control_row, variable=self.progress_var, maximum=100, length=120)
        self.progress_bar.grid(row=0, column=4, sticky=tk.EW, padx=(0, 10))

        self.progress_label = tk.StringVar(value="就绪")
        ttk.Label(control_row, textvariable=self.progress_label, foreground="gray", width=12).grid(
            row=0, column=5, sticky=tk.W
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
            value=self.app_config.get('processing', 'confirm_llm_stages', default=False)
        )
        ttk.Checkbutton(
            secondary_row,
            text="逐阶段确认",
            variable=self.stage_confirmation_var,
        ).pack(side=tk.LEFT)

        list_frame = ttk.LabelFrame(self, text="图纸任务", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        input_row = ttk.Frame(list_frame)
        input_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(input_row, text="输入目录:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(input_row, textvariable=self.input_dir_var, width=42).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(input_row, text="浏览", command=self._browse_input).pack(side=tk.LEFT, padx=(5, 0))

        self.task_notebook = ttk.Notebook(list_frame)
        self.task_notebook.pack(fill=tk.BOTH, expand=True)

        cad_tab = ttk.Frame(self.task_notebook)
        pending_tab = ttk.Frame(self.task_notebook)
        self.task_notebook.add(cad_tab, text="CAD 文件")
        self.task_notebook.add(pending_tab, text="待恢复任务")

        list_toolbar = ttk.Frame(cad_tab)
        list_toolbar.pack(fill=tk.X, pady=(0, 8))
        list_toolbar.grid_columnconfigure(2, weight=1)
        ttk.Button(list_toolbar, text="全选", width=8, command=self._select_all_files).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(list_toolbar, text="清空选择", width=10, command=self._clear_file_selection).grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Button(list_toolbar, text="刷新", width=10, command=self._refresh_files).grid(row=0, column=3, sticky=tk.E, padx=(0, 8))
        ttk.Button(list_toolbar, text="预览选中", width=12, command=self._preview_selected).grid(row=0, column=4, sticky=tk.E)

        content_row = ttk.Frame(cad_tab)
        content_row.pack(fill=tk.BOTH, expand=True)

        columns = ("checked", "filename", "type", "path")
        self.file_tree = ttk.Treeview(content_row, columns=columns, show="headings", height=6, selectmode="extended")
        self.file_tree.configure(height=6)
        self.file_tree.heading("checked", text="选择")
        self.file_tree.heading("filename", text="文件名")
        self.file_tree.heading("type", text="类型")
        self.file_tree.heading("path", text="路径")
        self.file_tree.column("checked", width=34, anchor=tk.CENTER, stretch=False)
        self.file_tree.column("filename", width=120)
        self.file_tree.column("type", width=45)
        self.file_tree.column("path", width=240)

        fsb = ttk.Scrollbar(content_row, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=fsb.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fsb.pack(side=tk.LEFT, fill=tk.Y)

        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_selected)
        self.file_tree.bind("<Button-1>", self._on_file_tree_click)
        self.file_tree.bind("<Double-1>", lambda _event: self._preview_selected())

        self.pending_panel = PendingClarificationPanel(
            pending_tab,
            on_resume=self.resume_pending_item,
        )
        self.pending_panel.pack(fill=tk.BOTH, expand=True)

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
        checked_paths = {
            self.file_tree.item(item, "values")[3]
            for item in self._checked_file_items
            if item in self.file_tree.get_children()
        }
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self._checked_file_items.clear()
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
            checked = str(f) in checked_paths
            item = self.file_tree.insert("", tk.END, values=("☑" if checked else "☐", f.name, f.suffix.upper(), str(f)))
            if checked:
                self._checked_file_items.add(item)

    def _on_file_selected(self, event):
        pass

    def _on_file_tree_click(self, event):
        if self.file_tree.identify_region(event.x, event.y) != "cell":
            return
        if self.file_tree.identify_column(event.x) != "#1":
            return
        item = self.file_tree.identify_row(event.y)
        if not item:
            return "break"
        self._toggle_file_checked(item)
        return "break"

    def _toggle_file_checked(self, item: str):
        values = list(self.file_tree.item(item, "values"))
        if len(values) < 4:
            return
        if item in self._checked_file_items:
            self._checked_file_items.remove(item)
            values[0] = "☐"
        else:
            self._checked_file_items.add(item)
            values[0] = "☑"
        self.file_tree.item(item, values=values)

    def _select_all_files(self):
        children = self.file_tree.get_children()
        if children:
            self._checked_file_items = set(children)
            for item in children:
                values = list(self.file_tree.item(item, "values"))
                if values:
                    values[0] = "☑"
                    self.file_tree.item(item, values=values)

    def _clear_file_selection(self):
        for item in list(self._checked_file_items):
            if item in self.file_tree.get_children():
                values = list(self.file_tree.item(item, "values"))
                if values:
                    values[0] = "☐"
                    self.file_tree.item(item, values=values)
        self._checked_file_items.clear()
        self.file_tree.selection_remove(self.file_tree.selection())

    def _selected_file_paths(self) -> List[str]:
        paths = []
        selected_items = list(self._checked_file_items) or list(self.file_tree.selection())
        for item in selected_items:
            if item not in self.file_tree.get_children():
                continue
            values = self.file_tree.item(item, "values")
            if len(values) >= 4:
                paths.append(values[3])
        return paths

    def _save_recovery_item(self, result, output_dir: str) -> Optional[str]:
        try:
            if not getattr(result, "clarification_questions", None):
                return None
            if not getattr(result, "clarification_context", None):
                return None
            item = self.pending_store.save_recovery(
                result,
                output_dir=output_dir,
                extrude_height=float(self.height_var.get()),
            )
            if self.on_pending_changed:
                self.after(0, self.on_pending_changed)
            self.after(0, self.pending_panel.refresh)
            return item.get("pending_id")
        except Exception as pending_error:
            logger.warning(f"保存待恢复任务失败: {pending_error}")
            return None

    @staticmethod
    def _recovery_item_from_result(result) -> Dict[str, Any]:
        return {
            "source_status": getattr(getattr(result, "status", None), "value", None),
            "modeling_path": getattr(result, "modeling_path", None),
            "clarification_questions": getattr(result, "clarification_questions", []) or [],
            "clarification_context": getattr(result, "clarification_context", {}) or {},
        }

    def _recovery_type_for_result(self, result) -> str:
        return pending_recovery_type(self._recovery_item_from_result(result))

    def _recovery_summary_for_result(self, result) -> str:
        return pending_recovery_summary(self._recovery_item_from_result(result))

    def resume_pending_item(self, item: Dict[str, Any]) -> None:
        if self._processing:
            messagebox.showinfo("任务正在处理中", "请等待当前处理任务结束后再恢复该图纸。")
            return

        input_file = item.get("input_file", "")
        if not input_file:
            messagebox.showwarning("待恢复任务无效", "该待恢复任务缺少输入图纸路径。")
            return

        try:
            self._reset_processing_controls()
            config = self._load_config(confirm_llm_stages=bool(self.stage_confirmation_var.get()))
            self._attach_processing_run_id(
                config,
                item.get("pending_id") or self._new_processing_run_id(input_file),
            )
            from src.batch_processor import CADPipeline, CADProcessResult

            output_dir = item.get("output_dir") or self.output_dir_var.get()
            self.pipeline = CADPipeline(
                config=config,
                input_dir=str(Path(input_file).parent),
                output_dir=output_dir,
            )
            self.pipeline.set_output_dir(output_dir)

            result = CADProcessResult.from_pending_item(item)
            self.output_dir_var.set(output_dir)
            self.progress_label.set("等待补充")
            logger.info(f"恢复图纸任务: {Path(input_file).name} | {pending_recovery_summary(item)}")
            self._show_clarification_dialog(result, time.time(), pending_id=item.get("pending_id"))
        except Exception as e:
            logger.error(f"打开待恢复任务失败: {e}")
            messagebox.showerror("打开待恢复任务失败", f"无法恢复该图纸任务：\n{e}")

    def _preview_selected(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo(
                "请选择图纸",
                "请先在左侧 CAD 文件列表中单击选择一张 DXF 或 DWG 图纸，"
                "然后再点击\u201c预览选中\u201d。"
            )
            return
        if self.preview_fig is None or self.preview_canvas is None:
            messagebox.showinfo(
                "预览区未就绪",
                "右侧图纸预览画布还没有初始化完成，请稍等片刻后重试。"
            )
            return

        values = self.file_tree.item(selected[0], "values")
        filepath = values[3] if len(values) >= 4 else values[2]
        title = Path(filepath).stem
        preview_path = self._find_preview(filepath)

        if preview_path:
            self._show_preview_image(preview_path, title)
            return

        self._generate_and_show_preview(filepath)

    def _find_preview(self, filepath: str) -> str:
        from src.utils.preview_cache import get_preview_cache_path

        shared_preview = get_preview_cache_path(filepath)
        if shared_preview.exists() and shared_preview.stat().st_size >= 500:
            return str(shared_preview)
        return ""

    def _generate_and_show_preview(self, filepath: str):
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

    def _prepare_batch_progress(self, filepaths: List[str], output_dir: str):
        self._batch_output_dir = output_dir
        self._batch_progress_items = {}
        now = time.time()
        for filepath in filepaths:
            self._batch_progress_items[filepath] = {
                "name": Path(filepath).name,
                "path": filepath,
                "status": "排队中",
                "stage": "queued",
                "stage_text": "排队中",
                "message": "",
                "stage_started_at": now,
                "started_at": None,
                "ended_at": None,
                "finished": False,
            }
        if self._batch_progress_button is not None:
            self._batch_progress_button.configure(state="normal")
        self._show_batch_progress_window()

    def _show_batch_progress_window(self):
        if not self._batch_progress_items:
            messagebox.showinfo("暂无批量进度", "当前还没有可查看的批量处理进度。")
            return
        if self._batch_progress_window and self._batch_progress_window.exists():
            self._batch_progress_window.focus()
            return
        self._batch_progress_window = BatchProgressWindow(
            self,
            self._batch_progress_items,
            output_dir=self._batch_output_dir or self.output_dir_var.get(),
            on_closed=self._on_batch_progress_closed,
        )

    def _on_batch_progress_closed(self):
        self._batch_progress_window = None

    def _set_batch_item_stage(self, item_id: Optional[str], stage: str, status: str, text: str):
        if not item_id:
            return

        def update():
            item = self._batch_progress_items.get(item_id)
            if not item or item.get("finished"):
                return
            now = time.time()
            if item.get("stage") != stage:
                item["stage_started_at"] = now
            if item.get("started_at") is None:
                item["started_at"] = now
            item["stage"] = stage
            item["status"] = status
            item["stage_text"] = text
            item["message"] = text
            if self._batch_progress_window and self._batch_progress_window.exists():
                self._batch_progress_window.refresh_all()

        self.after(0, update)

    def _finish_batch_item(self, item_id: str, status: str, message: str):
        def update():
            item = self._batch_progress_items.get(item_id)
            if not item:
                return
            item["stage"] = "done"
            item["status"] = status
            item["stage_text"] = message
            item["message"] = message
            item["finished"] = True
            item["ended_at"] = time.time()
            if item.get("started_at") is None:
                item["started_at"] = item["ended_at"]
            if self._batch_progress_window and self._batch_progress_window.exists():
                self._batch_progress_window.refresh_all()

        self.after(0, update)

    def _cancel_unfinished_batch_items(self):
        for item_id, item in list(self._batch_progress_items.items()):
            if not item.get("finished"):
                self._finish_batch_item(item_id, "已取消", "批量处理已取消")

    def _start_processing(self):
        if self._processing:
            messagebox.showinfo(
                "任务正在处理中",
                "当前已有图纸处理任务在运行，请等待进度条完成后再开始新的任务。"
            )
            return

        selected_paths = self._selected_file_paths()
        if not selected_paths:
            messagebox.showinfo(
                "请选择要处理的图纸",
                "请先在 CAD 文件列表中选择一张或多张图纸，再点击\u201c开始处理\u201d。"
            )
            return

        file_count = len(selected_paths)
        filepath = selected_paths[0]
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
        if file_count == 1:
            logger.info(f"开始处理: {Path(filepath).name}")
        else:
            logger.info(f"开始批量处理: {file_count} 张图纸")

        output_dir = self.output_dir_var.get()
        if file_count == 1:
            confirm_llm_stages = bool(self.stage_confirmation_var.get())
            thread = threading.Thread(
                target=self._run_processing,
                args=(filepath, output_dir, confirm_llm_stages),
                daemon=True,
            )
        else:
            self._prepare_batch_progress(selected_paths, output_dir)
            thread = threading.Thread(
                target=self._run_batch_processing,
                args=(selected_paths, output_dir),
                daemon=True,
            )
        thread.start()

    def _run_batch_processing(self, filepaths: List[str], output_dir: str):
        start_time = time.time()
        totals = {
            "completed": 0,
            "partial_completed": 0,
            "failed": 0,
            "needs_clarification": 0,
            "stopped_by_user": 0,
            "stage_action_requested": 0,
        }
        try:
            config = self._load_config(confirm_llm_stages=False)
            from src.batch_processor import CADPipeline

            total = len(filepaths)
            for index, filepath in enumerate(filepaths, start=1):
                self._check_control_state(f"batch-{index}-start")
                name = Path(filepath).name
                percent = max(1, int(((index - 1) / total) * 100))
                self._update_progress(percent, f"批量 {index}/{total}")
                logger.info(f"批量处理 {index}/{total}: {name}")
                self._attach_processing_run_id(config, self._new_processing_run_id(filepath))
                self._active_batch_item_id = filepath
                self._set_batch_item_stage(filepath, "preparing", "处理中", "准备中")

                pipeline = CADPipeline(
                    config=config,
                    input_dir=str(Path(filepath).parent),
                    output_dir=output_dir,
                )
                pipeline.set_output_dir(output_dir)
                self.pipeline = pipeline

                result = pipeline.process_file_intelligent(filepath, float(self.height_var.get()))
                self._set_batch_item_stage(filepath, "finalizing", "收尾中", "保存结果")
                status_value = getattr(getattr(result, "status", None), "value", "")
                if result.success:
                    bucket = "partial_completed" if status_value == "partial_completed" else "completed"
                    totals[bucket] += 1
                    logger.info(f"批量完成: {name} | 状态: {status_value or 'completed'}")
                    if status_value == "partial_completed":
                        logger.warning(f"部分完成原因: {getattr(result, 'partial_completion_reason', '')}")
                        pending_saved = self._save_recovery_item(result, output_dir)
                        if pending_saved:
                            totals["needs_clarification"] += 1
                            self._finish_batch_item(filepath, "部分完成/待恢复", "主体模型已生成，等待补充跳过细节")
                        else:
                            self._finish_batch_item(filepath, "部分完成", getattr(result, "partial_completion_reason", "") or "主体模型已生成，部分细节跳过")
                    else:
                        self._finish_batch_item(filepath, "完成", "处理完成")
                elif status_value == "needs_clarification":
                    try:
                        saved_item = self.pending_store.save_recovery(
                            result,
                            output_dir=output_dir,
                            extrude_height=float(self.height_var.get()),
                        )
                        totals["needs_clarification"] += 1
                        summary = pending_recovery_summary(saved_item)
                        logger.info(f"已保存为待恢复任务: {name} | {summary}")
                        self._finish_batch_item(filepath, pending_recovery_type(saved_item), summary)
                        if self.on_pending_changed:
                            self.after(0, self.on_pending_changed)
                    except Exception as pending_error:
                        totals["failed"] += 1
                        logger.error(f"待恢复任务保存失败: {name} | {pending_error}")
                        self._finish_batch_item(filepath, "失败", f"待恢复任务保存失败: {pending_error}")
                elif status_value == "stopped_by_user":
                    totals["stopped_by_user"] += 1
                    logger.info(f"批量项已停止: {name} | {result.error_message}")
                    self._finish_batch_item(filepath, "已停止", result.error_message or "用户停止处理")
                elif status_value == "stage_action_requested":
                    totals["stage_action_requested"] += 1
                    label, message_text = format_stage_supervision_message(result)
                    logger.info(f"批量项请求阶段监督动作: {name} | {message_text}")
                    self._finish_batch_item(filepath, label, message_text)
                else:
                    totals["failed"] += 1
                    logger.error(f"批量失败: {name} | {result.error_message}")
                    self._finish_batch_item(filepath, "失败", result.error_message or "处理失败")
                self._active_batch_item_id = None

            elapsed = time.time() - start_time
            message = (
                f"批量处理完成，用时 {elapsed:.1f}s。\n\n"
                f"完成: {totals['completed']}\n"
                f"部分完成: {totals['partial_completed']}\n"
                f"待恢复: {totals['needs_clarification']}\n"
                f"阶段操作: {totals['stage_action_requested']}\n"
                f"失败: {totals['failed']}\n"
                f"已停止: {totals['stopped_by_user']}"
            )
            logger.info(
                "批量处理完成 | "
                f"完成 {totals['completed']} | 部分完成 {totals['partial_completed']} | "
                f"待恢复 {totals['needs_clarification']} | 失败 {totals['failed']} | "
                f"阶段操作 {totals['stage_action_requested']} | 已停止 {totals['stopped_by_user']}"
            )
            self.after(0, lambda: self.progress_var.set(100))
            self.after(0, lambda: self.progress_label.set("批量完成"))
            self.after(0, lambda m=message: messagebox.showinfo("批量处理完成", m))
            if self.on_pending_changed:
                self.after(0, self.on_pending_changed)
        except ProcessingCancelled:
            elapsed = time.time() - start_time
            logger.warning(f"批量处理已取消 | 耗时: {elapsed:.1f}s")
            self._cancel_unfinished_batch_items()
            self.after(0, lambda: self.progress_label.set("已取消"))
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"批量处理异常 | 耗时: {elapsed:.1f}s | {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._cancel_unfinished_batch_items()
            self.after(0, lambda: messagebox.showerror(
                "批量处理异常",
                f"批量处理时发生未预期错误：\n{e}"
            ))
        finally:
            self._active_batch_item_id = None
            self._processing = False
            self._paused = False
            self._pause_event.set()
            self.after(0, lambda: self.process_btn.configure(state="normal", text="开始处理"))
            self.after(0, lambda: self.pause_btn.configure(state="disabled", text="暂停"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _run_processing(self, filepath: str, output_dir: str, confirm_llm_stages: bool):
        start_time = time.time()
        try:
            self._check_control_state("start")
            config = self._load_config(confirm_llm_stages=confirm_llm_stages)
            self._attach_processing_run_id(config, self._new_processing_run_id(filepath))
            from src.batch_processor import CADPipeline

            input_dir = str(Path(filepath).parent)

            self.pipeline = CADPipeline(config=config, input_dir=input_dir, output_dir=output_dir)
            self.pipeline.set_output_dir(output_dir)

            self._update_progress(10, "解析中...")

            self._check_control_state("pipeline-ready")

            logger.info("使用统一智能处理入口")
            self.pipeline.processor.process_with_intelligent_analysis = self._wrap_intelligent(
                self.pipeline.processor.process_with_intelligent_analysis)
            self._check_control_state("before-intelligent-processing")
            result = self.pipeline.process_file_intelligent(filepath, float(self.height_var.get()))

            self._update_progress(90, "完成，正在生成报告...")

            self._check_control_state("processing-finished")
            elapsed = time.time() - start_time
            if result.success:
                status_value = getattr(getattr(result, "status", None), "value", "")
                result_mode = getattr(result, "mode", None) or "intelligent"
                result_path = getattr(result, "modeling_path", None) or "unknown"
                status_label = "部分完成" if status_value == "partial_completed" else "处理成功"
                logger.info(
                    f"{status_label} | 耗时: {elapsed:.1f}s | 实体数: {result.entity_count} | "
                    f"模式: {result_mode} | 建模路径: {result_path}"
                )
                for line in stage_self_correction_log_lines(result):
                    logger.info(line)
                if status_value == "partial_completed":
                    logger.warning(f"部分完成原因: {getattr(result, 'partial_completion_reason', '')}")
                    for feature in getattr(result, "skipped_features", []) or []:
                        logger.warning(f"跳过细节: {feature}")
                    if self._save_recovery_item(result, self.output_dir_var.get()):
                        logger.info("部分完成任务已加入待恢复列表，补充信息后可重新生成模型")
                if result.output_paths:
                    for k, v in result.output_paths.items():
                        logger.info(f"输出产物 [{k}]: {v}")
                label = "部分完成" if status_value == "partial_completed" else "完成"
                self.after(0, lambda l=label: self.progress_label.set(f"{l} ({elapsed:.1f}s)"))
                self.after(0, lambda: self.progress_var.set(100))
            elif getattr(result, "status", None) and getattr(result.status, "value", "") == "needs_clarification":
                self._awaiting_clarification = True
                recovery_summary = self._recovery_summary_for_result(result)
                logger.info(f"处理进入待恢复 | {recovery_summary} | 耗时: {elapsed:.1f}s")
                pending_id = self._save_recovery_item(result, output_dir)
                if pending_id:
                    logger.info(f"已保存为待恢复任务: {Path(filepath).name} | {self._recovery_type_for_result(result)} | {pending_id}")
                self.after(0, lambda s=self._recovery_type_for_result(result): self.progress_label.set(s))
                self.after(0, lambda r=result, s=start_time, p=pending_id: self._show_clarification_dialog(r, s, p))
                return
            elif getattr(result, "status", None) and getattr(result.status, "value", "") == "stopped_by_user":
                logger.info(f"用户停止处理 | 耗时: {elapsed:.1f}s | {result.error_message}")
                self.after(0, lambda: self.progress_label.set("已停止"))
            elif getattr(result, "status", None) and getattr(result.status, "value", "") == "stage_action_requested":
                label, message_text = format_stage_supervision_message(result)
                logger.info(f"阶段监督动作已记录 | 耗时: {elapsed:.1f}s | {message_text}")
                self.after(0, lambda l=label: self.progress_label.set(l))
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
                "详细错误已写入下方\u201c处理日志\u201d，请复制日志用于排查。"))
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

    def _show_clarification_dialog(self, result, start_time: float, pending_id: Optional[str] = None):
        questions = result.clarification_questions or []
        if not questions:
            messagebox.showwarning("需要澄清", "当前任务需要澄清，但没有可展示的问题。")
            return

        dialog = tk.Toplevel(self)
        recovery_type = self._recovery_type_for_result(result)
        dialog.title(recovery_type)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            body,
            text=f"{recovery_type}：系统需要补充信息后再继续智能建模",
            font=("", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 10))

        answer_vars = {}
        for question in questions:
            block = ttk.Frame(body)
            block.pack(fill=tk.X, pady=(0, 10))
            ttk.Label(
                block,
                text=question.get("text", "请补充信息"),
                wraplength=420,
            ).pack(anchor=tk.W)
            reason = str(question.get("reason") or "").strip()
            if reason:
                ttk.Label(
                    block,
                    text=f"为什么问：{reason}",
                    foreground="#666666",
                    wraplength=420,
                ).pack(anchor=tk.W, pady=(2, 0))
            example = str(question.get("example") or "").strip()
            if example:
                ttk.Label(
                    block,
                    text=f"示例：{example}",
                    foreground="#666666",
                    wraplength=420,
                ).pack(anchor=tk.W, pady=(2, 0))
            kind = question.get("kind")
            options = question.get("options", []) or []
            if is_candidate_clarification_question(question):
                var = tk.StringVar(value="")
                option_frame = ttk.Frame(block)
                option_frame.pack(fill=tk.X, pady=(6, 0))
                for option in options:
                    value = clarification_option_value(option)
                    label = clarification_option_label(option)
                    tk.Radiobutton(
                        option_frame,
                        text=label,
                        variable=var,
                        value=value,
                        anchor=tk.W,
                        justify=tk.LEFT,
                        wraplength=480,
                        padx=0,
                        pady=2,
                    ).pack(fill=tk.X, anchor=tk.W)
            elif kind == "single_choice" and options:
                display_to_value = {}
                values = []
                for option in options:
                    display = clarification_option_label(option)
                    value = clarification_option_value(option)
                    display_to_value[display] = value
                    values.append(display)
                var = tk.StringVar(value=values[0])
                var._cad_value_map = display_to_value
                combo = ttk.Combobox(block, textvariable=var, state="readonly", values=values, width=52)
                combo.pack(anchor=tk.W, pady=(4, 0))
            else:
                var = tk.StringVar()
                ttk.Entry(block, textvariable=var, width=28).pack(anchor=tk.W, pady=(4, 0))
            answer_vars[question.get("id")] = var

        hint_block = ttk.Frame(body)
        hint_block.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        ttk.Label(hint_block, text="补充给大模型的建模提示（可选）").pack(anchor=tk.W)
        ttk.Label(
            hint_block,
            text="可说明建模意图、细节优先级或可跳过内容；图纸事实、标注尺寸和主体外形仍优先。",
            foreground="#666666",
            wraplength=420,
        ).pack(anchor=tk.W, pady=(2, 0))
        hint_text = tk.Text(hint_block, height=4, width=52, wrap=tk.WORD)
        hint_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(4, 0))

        def submit():
            answers = {
                question_id: getattr(var, "_cad_value_map", {}).get(var.get(), var.get()).strip()
                for question_id, var in answer_vars.items()
                if question_id and var.get().strip()
            }
            hint = hint_text.get("1.0", tk.END).strip()
            required_missing = [
                question.get("id")
                for question in questions
                if question.get("required") and question.get("id") not in answers
            ]
            unanswered_candidates = [
                question.get("id")
                for question in questions
                if is_candidate_clarification_question(question) and question.get("id") not in answers
            ]
            if required_missing:
                messagebox.showinfo("还差一点", "请先回答必填问题。", parent=dialog)
                return
            if unanswered_candidates:
                messagebox.showinfo("还差一点", "请先选择候选值，或选择\u201c不确定\u201d。", parent=dialog)
                return
            if not answers and not hint:
                messagebox.showinfo("还差一点", "请回答至少一个问题，或填写给大模型的补充提示。", parent=dialog)
                return
            candidate_summary = build_candidate_clarification_summary(questions, answers)
            if candidate_summary and not messagebox.askyesno(
                "确认候选尺寸",
                f"{candidate_summary}\n\n是否按以上结果继续建模？",
                parent=dialog,
            ):
                return
            if hint:
                answers["user_modeling_hint"] = hint
            dialog.destroy()
            self._resume_after_clarification(result, answers, start_time, pending_id=pending_id)

        def cancel_dialog():
            self._awaiting_clarification = False
            self.process_btn.configure(state="normal", text="开始处理")
            self.progress_label.set("已取消澄清")
            if self.on_pending_changed:
                self.after(0, self.on_pending_changed)
            self.after(0, self.pending_panel.refresh)
            dialog.destroy()

        ttk.Button(action_row, text="继续建模", command=submit).pack(side=tk.RIGHT)
        ttk.Button(action_row, text="取消", command=cancel_dialog).pack(side=tk.RIGHT, padx=(0, 8))

        self._center_dialog(dialog)
        dialog.protocol("WM_DELETE_WINDOW", cancel_dialog)

    def _center_dialog(self, dialog: tk.Toplevel) -> None:
        from src.gui.helpers import center_window_on_parent
        center_window_on_parent(dialog, self.winfo_toplevel())

    def _confirm_llm_stage(self, stage: str, payload: Dict[str, Any]):
        from src.utils.stage_confirmation import (
            StageConfirmationResult,
            default_stage_stop_message,
            stage_display_name,
        )

        if self._cancel_event.is_set():
            return StageConfirmationResult(
                continue_processing=False,
                action="cancel",
                message=f"用户在 {stage_display_name(stage)} 阶段取消处理",
                stage=stage,
            )

        completed = threading.Event()
        outcome = {
            "decision": StageConfirmationResult.stop(default_stage_stop_message(stage))
        }
        self.after(0, lambda: self.progress_label.set("等待阶段确认"))
        self.after(
            0,
            lambda: self._show_stage_confirmation_dialog_safely(
                stage,
                payload,
                outcome,
                completed,
            ),
        )

        while not completed.wait(0.1):
            if self._cancel_event.is_set():
                return StageConfirmationResult(
                    continue_processing=False,
                    action="cancel",
                    message=f"用户在 {stage_display_name(stage)} 阶段取消处理",
                    stage=stage,
                )
        return outcome["decision"]

    def _show_stage_confirmation_dialog_safely(
        self,
        stage: str,
        payload: Dict[str, Any],
        outcome: Dict[str, Any],
        completed: threading.Event,
    ) -> None:
        try:
            self._show_stage_confirmation_dialog(stage, payload, outcome, completed)
        except Exception as error:
            from src.utils.stage_confirmation import StageConfirmationResult, stage_display_name

            logger.exception(f"阶段确认窗口创建失败: {stage}")
            outcome["decision"] = StageConfirmationResult(
                continue_processing=False,
                action="stop",
                message=f"{stage_display_name(stage)}确认窗口创建失败: {error}",
                stage=stage,
            )
            completed.set()

    def _show_stage_confirmation_dialog(
        self,
        stage: str,
        payload: Dict[str, Any],
        outcome: Dict[str, Any],
        completed: threading.Event,
    ) -> None:
        from src.utils.stage_confirmation import (
            StageConfirmationResult,
            default_stage_stop_message,
            stage_display_name,
        )

        stage_titles = {
            "view_analysis": "视图语义校正",
            "semantic_adjudication": "图纸语义裁决",
            "semantic_reconstruction": "零件语义重建",
            "modeling_generation": "建模指令生成",
        }
        title = stage_titles.get(stage, stage)

        part_semantics = payload.get("part_semantics", {})
        self_correction_log = part_semantics.get("self_correction_log", [])
        has_self_correction = bool(self_correction_log)
        all_issues_resolved = not any(
            log.get("issues") and log.get("result", "").find("仍") >= 0
            for log in self_correction_log
        )
        confidence = float(part_semantics.get("confidence") or 0.0)
        body_safety_boundary_closed = confidence >= 0.5

        if has_self_correction and all_issues_resolved:
            dialog_title = f"{title}完成（自纠已执行）"
        elif has_self_correction and not all_issues_resolved:
            dialog_title = f"{title}完成（自纠未完全解决）"
        else:
            dialog_title = f"{title}完成"

        dialog = tk.Toplevel(self)
        dialog.title(dialog_title)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.minsize(460, 280)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text=dialog_title,
            font=("", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        report_text = tk.Text(body, height=10, width=62, wrap=tk.WORD)
        report_text.pack(fill=tk.BOTH, expand=True)
        report_text.insert("1.0", self._build_stage_report(stage, payload))
        report_text.configure(state="disabled")

        hint_text = "选择\u201c停止\u201d会结束本次处理，但保留已完成阶段的结果供查看。"
        if has_self_correction and not all_issues_resolved:
            hint_text = "自纠未能完全解决校验问题。可选择\u201c重跑\u201d带部分成果重新生成，或\u201c停止\u201d结束处理。"
        ttk.Label(body, text=hint_text).pack(anchor=tk.W, pady=(10, 0))

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(10, 0))

        def continue_stage():
            outcome["decision"] = StageConfirmationResult.continue_()
            completed.set()
            dialog.destroy()

        def stop_stage():
            outcome["decision"] = StageConfirmationResult.stop(
                default_stage_stop_message(stage),
                stage=stage,
            )
            completed.set()
            dialog.destroy()

        def retry_with_partial():
            retained = self._show_retry_selection_dialog(dialog, stage, payload)
            if retained is None:
                return
            logger.info(f"{stage_display_name(stage)}阶段准备带部分成果重跑")
            self._handle_processing_stage("ai_analysis", f"重跑{stage_display_name(stage)}")
            outcome["decision"] = StageConfirmationResult.retry_with_partial(
                retained_items=retained,
                stage=stage,
            )
            completed.set()
            dialog.destroy()

        continue_button = ttk.Button(action_row, text="继续", command=continue_stage)
        continue_button.pack(side=tk.RIGHT)
        if not body_safety_boundary_closed and has_self_correction and not all_issues_resolved:
            continue_button.configure(state="disabled")

        ttk.Button(action_row, text="停止", command=stop_stage).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(action_row, text="重跑", command=retry_with_partial).pack(side=tk.LEFT)

        def close_if_cancelled():
            if completed.is_set():
                return
            if self._cancel_event.is_set():
                outcome["decision"] = StageConfirmationResult(
                    continue_processing=False,
                    action="cancel",
                    message=f"用户在 {stage_display_name(stage)} 阶段取消处理",
                    stage=stage,
                )
                completed.set()
                dialog.destroy()
                return
            dialog.after(100, close_if_cancelled)

        self._center_dialog(dialog)
        self.winfo_toplevel().lift()
        self.winfo_toplevel().attributes("-topmost", True)
        self.winfo_toplevel().after(300, lambda: self.winfo_toplevel().attributes("-topmost", False))
        dialog.lift()
        dialog.focus_force()
        dialog.after(50, lambda: dialog.attributes("-topmost", True))
        dialog.after(300, lambda: dialog.attributes("-topmost", False))
        dialog.protocol("WM_DELETE_WINDOW", stop_stage)
        dialog.after(100, close_if_cancelled)

    def _show_retry_selection_dialog(
        self,
        parent: tk.Toplevel,
        stage: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        from src.utils.stage_confirmation import stage_display_name

        selection_dialog = tk.Toplevel(parent)
        selection_dialog.title(f"选择保留的部分成果 — {stage_display_name(stage)}")
        selection_dialog.transient(parent)
        selection_dialog.grab_set()
        selection_dialog.resizable(True, True)
        selection_dialog.minsize(420, 320)

        body = ttk.Frame(selection_dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text="勾选的项目将作为重跑的约束条件，模型必须遵守已确认结果。",
            wraplength=380,
        ).pack(anchor=tk.W, pady=(0, 10))

        scroll_frame = ttk.Frame(body)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        check_vars: Dict[str, tk.BooleanVar] = {}

        def add_section(label: str, items: list, key: str):
            if not items:
                return
            ttk.Label(inner, text=label, font=("", 9, "bold")).pack(anchor=tk.W, pady=(8, 2))
            for idx, item in enumerate(items):
                if isinstance(item, str):
                    text = item
                elif key == "key_dim":
                    name = item.get("name") or item.get("kind") or ""
                    value = item.get("value") or item.get("nominal") or ""
                    unit = item.get("unit") or "mm"
                    if name and value:
                        text = f"{name}: {value}{unit}"
                    elif name:
                        text = name
                    else:
                        text = str(item)
                else:
                    parts = []
                    kind = item.get("kind", "")
                    desc = item.get("description", "")
                    dims = item.get("dimensions") or {}
                    if kind:
                        parts.append(_feature_kind_label(kind))
                    if desc:
                        parts.append(desc)
                    elif dims:
                        dim_parts = [f"{k}={v}" for k, v in list(dims.items())[:3]]
                        parts.append(", ".join(dim_parts))
                    text = " — ".join(parts) if len(parts) > 1 else (parts[0] if parts else str(item))
                var = tk.BooleanVar(value=True)
                check_vars[f"{key}_{idx}"] = var
                cb = ttk.Checkbutton(inner, text=text, variable=var)
                cb.pack(anchor=tk.W, padx=(16, 0))

        if stage == "modeling_generation":
            instructions = payload.get("modeling_instructions") or payload
            completed = instructions.get("completed_features") or []
            skipped = instructions.get("skipped_features") or []
            key_dims = instructions.get("key_dimensions") or []
            add_section("已完成特征", completed, "completed")
            add_section("跳过特征", skipped, "skipped")
            add_section("关键尺寸", key_dims, "key_dim")
        else:
            part_semantics = payload.get("part_semantics", {})
            part_type = part_semantics.get("part_type", "")
            if part_type:
                var = tk.BooleanVar(value=True)
                check_vars["part_type"] = var
                ttk.Label(inner, text="零件类型", font=("", 9, "bold")).pack(anchor=tk.W, pady=(4, 2))
                ttk.Checkbutton(inner, text=part_type, variable=var).pack(anchor=tk.W, padx=(16, 0))
            add_section("主体特征", part_semantics.get("base_features", []), "base")
            add_section("增材特征", part_semantics.get("additive_features", []), "additive")
            add_section("减材特征", part_semantics.get("subtractive_features", []), "subtractive")
            add_section("关键尺寸", part_semantics.get("key_dimensions", []), "key_dim")

        result_holder: Dict[str, Any] = {"retained": None}

        def confirm():
            retained: Dict[str, Any] = {}
            if stage == "modeling_generation":
                instructions = payload.get("modeling_instructions") or payload
                retained["completed_features"] = [
                    item for idx, item in enumerate(instructions.get("completed_features") or [])
                    if check_vars.get(f"completed_{idx}") and check_vars[f"completed_{idx}"].get()
                ]
                retained["skipped_features"] = [
                    item for idx, item in enumerate(instructions.get("skipped_features") or [])
                    if check_vars.get(f"skipped_{idx}") and check_vars[f"skipped_{idx}"].get()
                ]
                retained["key_dimensions"] = [
                    item for idx, item in enumerate(instructions.get("key_dimensions") or [])
                    if check_vars.get(f"key_dim_{idx}") and check_vars[f"key_dim_{idx}"].get()
                ]
            else:
                part_semantics = payload.get("part_semantics", {})
                part_type = part_semantics.get("part_type", "")
                if check_vars.get("part_type") and check_vars["part_type"].get():
                    retained["part_type"] = part_type
                retained["base_features"] = [
                    item for idx, item in enumerate(part_semantics.get("base_features", []))
                    if check_vars.get(f"base_{idx}") and check_vars[f"base_{idx}"].get()
                ]
                retained["additive_features"] = [
                    item for idx, item in enumerate(part_semantics.get("additive_features", []))
                    if check_vars.get(f"additive_{idx}") and check_vars[f"additive_{idx}"].get()
                ]
                retained["subtractive_features"] = [
                    item for idx, item in enumerate(part_semantics.get("subtractive_features", []))
                    if check_vars.get(f"subtractive_{idx}") and check_vars[f"subtractive_{idx}"].get()
                ]
                retained["key_dimensions"] = [
                    item for idx, item in enumerate(part_semantics.get("key_dimensions", []))
                    if check_vars.get(f"key_dim_{idx}") and check_vars[f"key_dim_{idx}"].get()
                ]
            result_holder["retained"] = retained
            selection_dialog.destroy()

        def cancel():
            selection_dialog.destroy()

        btn_row = ttk.Frame(body)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="确认重跑", command=confirm).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="取消", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        self._center_dialog(selection_dialog)
        selection_dialog.wait_window()
        return result_holder["retained"]

    def _build_stage_report(self, stage: str, payload: Dict[str, Any]) -> str:
        from src.utils.stage_report import build_stage_report

        return build_stage_report(stage, payload)

    def _resume_after_clarification(
        self,
        result,
        answers: Dict[str, str],
        start_time: float,
        pending_id: Optional[str] = None,
    ):
        self._reset_processing_controls()
        self._processing = True
        self._awaiting_clarification = False
        self.process_btn.configure(state="disabled", text="处理中...")
        self.pause_btn.configure(state="normal", text="暂停")
        self.cancel_btn.configure(state="normal")
        self.progress_label.set("根据澄清继续...")
        logger.info("已收到用户澄清，继续智能建模")

        thread = threading.Thread(
            target=self._run_clarification_resume,
            args=(result, answers, start_time, pending_id),
            daemon=True,
        )
        thread.start()

    def _reset_processing_controls(self) -> None:
        self._cancel_event.clear()
        self._paused = False
        self._pause_event.set()

    def _run_clarification_resume(
        self,
        result,
        answers: Dict[str, str],
        start_time: float,
        pending_id: Optional[str] = None,
    ):
        try:
            self._check_control_state("before-clarification-resume")
            resumed = self.pipeline.continue_file_with_clarification(result, answers)
            elapsed = time.time() - start_time
            status_value = getattr(getattr(resumed, "status", None), "value", "")
            resolved_statuses = {"completed", "partial_completed"}
            if resumed.success or status_value in resolved_statuses:
                status_label = "澄清后部分完成" if status_value == "partial_completed" else "澄清后处理成功"
                logger.info(f"{status_label} | 总耗时: {elapsed:.1f}s | 实体数: {resumed.entity_count}")
                for line in stage_self_correction_log_lines(resumed):
                    logger.info(line)
                if status_value == "partial_completed":
                    logger.warning(f"部分完成原因: {getattr(resumed, 'partial_completion_reason', '')}")
                    for feature in getattr(resumed, "skipped_features", []) or []:
                        logger.warning(f"跳过细节: {feature}")
                if resumed.output_paths:
                    for k, v in resumed.output_paths.items():
                        logger.info(f"输出产物 [{k}]: {v}")
                partial_recovery_ready = (
                    status_value == "partial_completed"
                    and getattr(resumed, "clarification_questions", None)
                    and getattr(resumed, "clarification_context", None)
                )
                if partial_recovery_ready:
                    self.pending_store.save_recovery(
                        resumed,
                        output_dir=str(self.pipeline.file_manager.base_output_dir),
                        extrude_height=float(self.height_var.get()),
                    )
                    if pending_id:
                        logger.info(f"待恢复任务已更新，仍可继续补充后重新生成: {pending_id}")
                    else:
                        logger.info("部分完成任务已加入待恢复列表，补充信息后可重新生成模型")
                    if self.on_pending_changed:
                        self.after(0, self.on_pending_changed)
                    self.after(0, self.pending_panel.refresh)
                elif pending_id:
                    resolved_item = self.pending_store.mark_resolved(pending_id)
                    if resolved_item:
                        logger.info(f"待恢复任务已标记为已解决: {pending_id}")
                    else:
                        logger.warning(f"待恢复任务标记已解决失败，未找到任务: {pending_id}")
                    if self.on_pending_changed:
                        self.after(0, self.on_pending_changed)
                    self.after(0, self.pending_panel.refresh)
                label = "部分完成" if status_value == "partial_completed" else "完成"
                self.after(0, lambda l=label: self.progress_label.set(f"{l} ({elapsed:.1f}s)"))
                self.after(0, lambda: self.progress_var.set(100))
            elif getattr(resumed, "status", None) and getattr(resumed.status, "value", "") == "needs_clarification":
                self._awaiting_clarification = True
                logger.info(f"澄清后仍进入待恢复 | {self._recovery_summary_for_result(resumed)}")
                next_pending_id = pending_id
                try:
                    saved_item = self.pending_store.save_recovery(
                        resumed,
                        output_dir=str(self.pipeline.file_manager.base_output_dir),
                        extrude_height=float(self.height_var.get()),
                    )
                    next_pending_id = saved_item.get("pending_id") or next_pending_id
                    logger.info(f"待恢复任务已更新: {pending_recovery_summary(saved_item)}")
                    if self.on_pending_changed:
                        self.after(0, self.on_pending_changed)
                    self.after(0, self.pending_panel.refresh)
                except Exception as pending_error:
                    logger.warning(f"保存待恢复任务失败: {pending_error}")
                self.after(0, lambda s=self._recovery_type_for_result(resumed): self.progress_label.set(s))
                self.after(0, lambda r=resumed, s=start_time, p=next_pending_id: self._show_clarification_dialog(r, s, p))
                return
            elif getattr(resumed, "status", None) and getattr(resumed.status, "value", "") == "stopped_by_user":
                logger.info(f"用户停止处理 | 总耗时: {elapsed:.1f}s | {resumed.error_message}")
                self.after(0, lambda: self.progress_label.set("已停止"))
            elif getattr(resumed, "status", None) and getattr(resumed.status, "value", "") == "stage_action_requested":
                label, message_text = format_stage_supervision_message(resumed)
                logger.info(f"阶段监督动作已记录 | 总耗时: {elapsed:.1f}s | {message_text}")
                self.after(0, lambda l=label: self.progress_label.set(l))
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

    def _load_config(self, *, confirm_llm_stages: bool) -> Dict:
        config = {}
        try:
            from src.utils.config import load_config
            config = load_config()
        except Exception:
            pass
        apply_gui_runtime_overrides(config, self.app_config.data)
        if confirm_llm_stages:
            from src.utils.stage_confirmation import CallbackStageConfirmation
            config.setdefault("api", {}).setdefault("deepseek", {})[
                "_stage_confirmation"
            ] = CallbackStageConfirmation(self._confirm_llm_stage)
        config["_progress_callback"] = self._handle_processing_stage
        return config

    def _handle_processing_stage(self, stage: str, text: str):
        self._set_batch_item_stage(self._active_batch_item_id, stage, "处理中", text)
        stage_progress = {
            "parsing": 10,
            "ai_analysis": 30,
            "modeling": 70,
            "self_correction": 65,
            "finalizing": 90,
        }
        if stage in stage_progress:
            self._update_progress(stage_progress[stage], f"{text}...")

    def _new_processing_run_id(self, filepath: str) -> str:
        return f"gui_{Path(filepath).stem}_{uuid.uuid4().hex[:12]}"

    def _attach_processing_run_id(self, config: Dict[str, Any], run_id: str) -> None:
        config.setdefault("api", {}).setdefault("deepseek", {})["_processing_run_id"] = run_id

    def _update_progress(self, value: float, text: str):
        self.after(0, lambda: self.progress_var.set(value))
        self.after(0, lambda: self.progress_label.set(text))


_FEATURE_KIND_LABELS = {
    "plate": "平板",
    "block": "方块",
    "cylinder": "圆柱",
    "profile_extrusion": "轮廓拉伸",
    "other": "其他",
    "boss": "凸台",
    "rib": "加强筋",
    "shoulder": "台阶",
    "through_hole": "通孔",
    "blind_hole": "盲孔",
    "counterbore": "沉孔",
    "slot": "槽",
    "cutout": "切口",
    "fillet": "圆角",
    "chamfer": "倒角",
    "hole": "孔",
    "rectangular_plate": "矩形板",
}


def _feature_kind_label(kind: str) -> str:
    return _FEATURE_KIND_LABELS.get(kind, kind)
