# -*- coding: utf-8 -*-

import sys
import os
import logging
from pathlib import Path
from datetime import datetime

os.environ.setdefault('MPLBACKEND', 'Agg')

try:
    import matplotlib
    matplotlib.use('Agg')
except Exception:
    pass

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .helpers import AppConfig, PROJECT_ROOT
from .log_panel import GuiLogHandler, LogPanel
from .cache_panel import CacheManagerPanel
from .telemetry_panel import LLMTelemetryPanel
from .processing_panel import ProcessingPanel
from .settings_dialog import SettingsDialog
from .pending_panel import PendingClarificationPanel

from src.batch_processor import CADPipeline
from src.utils.config import load_config
from src.utils.deepseek_gui_config import apply_gui_runtime_overrides

logger = logging.getLogger(__name__)

__all__ = ["CADApplication", "main"]


class CADApplication(tk.Tk):
    """CAD 图纸 3D 建模系统 — 主窗口"""

    def __init__(self):
        super().__init__()

        self.title("CAD 图纸 3D 建模系统")
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

        menubar.add_command(label="设置", command=self._open_settings)

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
            "关于", "CAD 图纸 3D 建模系统\n\n"
                     "支持多模型的二维工程图智能分析与三维重建系统\n\n"
                     "功能：\n"
                     "- DXF/DWG 解析与可视化\n"
                     "- AI 智能视图分析与尺寸提取\n"
                     "- FreeCAD 自动建模与 STEP/STL 导出\n"
                     "- 缓存管理与日志分析"))
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)

        self.bind_all("<Control-o>", lambda e: self._open_step_model())
        self.bind_all("<Control-d>", lambda e: self._open_output_dir())

    def _open_settings(self):
        SettingsDialog(self, self.app_config, on_saved=self._apply_settings_changed)

    def _apply_settings_changed(self):
        if hasattr(self, "processing_panel"):
            output_dir = self.app_config.get("output", "base_dir", default="examples/output")
            if hasattr(self.processing_panel, "output_dir_var"):
                self.processing_panel.output_dir_var.set(output_dir)
            if hasattr(self.processing_panel, "stage_confirmation_var"):
                self.processing_panel.stage_confirmation_var.set(
                    bool(self.app_config.get("processing", "confirm_llm_stages", default=True))
                )
        if hasattr(self, "cache_panel"):
            self.cache_panel._cache = None
            self.cache_panel.refresh()
        self._init_pipeline()

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
            on_pending_changed=self._refresh_pending,
            preview_fig=self.preview_fig,
            preview_canvas=self.preview_canvas,
        )
        self.processing_panel.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(bottom_frame)
        self.bottom_notebook = notebook
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.log_panel = LogPanel(notebook, self.log_handler, self.app_config)
        notebook.add(self.log_panel, text="处理日志")

        self.llm_telemetry_panel = LLMTelemetryPanel(notebook, self.app_config)
        notebook.add(self.llm_telemetry_panel, text="大模型调用")

        self.cache_panel = CacheManagerPanel(notebook, self.app_config)
        notebook.add(self.cache_panel, text="缓存管理")
        notebook.bind("<<NotebookTabChanged>>", self._on_bottom_tab_changed)

        self.after(100, self._set_initial_pane_sizes)
        self.after(500, self._set_initial_pane_sizes)
        self.after(1200, self._set_initial_pane_sizes)

    def _on_bottom_tab_changed(self, _event=None):
        try:
            selected = self.bottom_notebook.select()
            if selected == str(self.cache_panel):
                self.cache_panel.refresh()
            elif selected == str(self.llm_telemetry_panel):
                self.llm_telemetry_panel.refresh()
            elif selected == str(self.processing_panel.pending_panel):
                self.processing_panel.pending_panel.refresh()
        except Exception as exc:
            logger.debug(f"底部标签页刷新失败: {exc}")

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
            config = {}
            try:
                config = load_config()
            except Exception:
                pass
            apply_gui_runtime_overrides(config, self.app_config.data)
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
        self._refresh_pending()

    def _refresh_cache(self):
        self.cache_panel.refresh()

    def _refresh_pending(self):
        if hasattr(self, "processing_panel") and hasattr(self.processing_panel, "pending_panel"):
            self.processing_panel.pending_panel.refresh()

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
        from src.gui.helpers import center_window_on_parent
        center_window_on_parent(preview_win, self)

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
            confirmed_selection = False
            choice_win = tk.Toplevel(self)
            choice_win.title("选择输出子目录")
            choice_win.geometry("500x350")
            from src.gui.helpers import center_window_on_parent
            center_window_on_parent(choice_win, self)

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
                nonlocal target_dir, confirmed_selection
                sel = tree.selection()
                if sel:
                    target_dir = str(output_base / tree.item(sel[0], "values")[0])
                    confirmed_selection = True
                choice_win.destroy()

            def on_cancel():
                choice_win.destroy()

            btn_frame = ttk.Frame(choice_win)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="打开选中目录", command=on_select).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=5)
            choice_win.protocol("WM_DELETE_WINDOW", on_cancel)

            self.wait_window(choice_win)
            if not confirmed_selection:
                return

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
