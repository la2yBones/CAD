#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD图纸3D建模 — 图形界面
支持: 文件管理 / 图纸预览 / 后台处理 / 进度追踪 / 模型打开
"""
import sys
import os
import threading
import time
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox


class CADApp:
    """CAD图纸3D建模主窗口"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CAD图纸3D建模工具 v0.3.0")
        self.root.geometry("1280x780")
        self.root.minsize(1024, 600)

        self.pipeline = None
        self.config = None
        self._cancel_flag = threading.Event()
        self._worker_thread = None
        self._selected_file = None
        self._preview_canvas = None
        self._preview_image = None
        self._preview_img_path = None
        self._preview_title = None

        self._init_config()
        self._init_matplotlib_fonts()

        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()
        self._refresh_file_list()

    def _init_config(self):
        try:
            from src.utils import load_config, setup_logging
            setup_logging(level="WARNING")
            self.config = load_config()
        except Exception:
            self.config = {}

    def _init_matplotlib_fonts(self):
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.font_manager as fm

            candidates = [
                "Microsoft YaHei", "SimHei", "SimSun",
                "KaiTi", "FangSong", "Noto Sans CJK SC",
                "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
            ]
            available = {f.name for f in fm.fontManager.ttflist}
            found = next((c for c in candidates if c in available), None)

            if found:
                matplotlib.rcParams["font.sans-serif"] = [found, "DejaVu Sans"]
            else:
                matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

    def _init_pipeline(self):
        if self.pipeline is not None:
            return
        try:
            from src.batch_processor import CADPipeline
            self.pipeline = CADPipeline(
                config=self.config or {},
                input_dir="examples/cad_files",
                output_dir="examples/output"
            )
            self._log("管道初始化成功")
        except Exception as e:
            self._log(f"管道初始化失败: {e}")

    def _build_ui(self):
        pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left_frame = ttk.Frame(pw, width=420)
        pw.add(left_frame, weight=0)
        self._build_left_panel(left_frame)

        right_frame = ttk.Frame(pw, width=600)
        pw.add(right_frame, weight=1)
        self._build_right_panel(right_frame)

        bottom_frame = ttk.Frame(self.root, height=180)
        bottom_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        bottom_frame.pack_propagate(False)
        self._build_bottom_panel(bottom_frame)

    def _build_left_panel(self, parent: ttk.Frame):
        ctrl = ttk.LabelFrame(parent, text="控制", padding=6)
        ctrl.pack(fill=tk.X, padx=2, pady=2)

        btn_frame = ttk.Frame(ctrl)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="选择文件夹", command=self._select_dir).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="刷新列表", command=self._refresh_file_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="预览选中", command=self._preview_selected).pack(side=tk.LEFT, padx=2)

        param = ttk.LabelFrame(parent, text="参数", padding=6)
        param.pack(fill=tk.X, padx=2, pady=2)

        row1 = ttk.Frame(param)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="拉伸高度(mm):").pack(side=tk.LEFT)
        self.height_var = tk.DoubleVar(value=10.0)
        ttk.Entry(row1, textvariable=self.height_var, width=8).pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(param)
        row2.pack(fill=tk.X, pady=2)
        self.analysis_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="启用 AI 智能分析", variable=self.analysis_var).pack(side=tk.LEFT)
        self.single_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="仅处理选中", variable=self.single_var).pack(side=tk.LEFT, padx=8)

        row3 = ttk.Frame(param)
        row3.pack(fill=tk.X, pady=2)
        ttk.Button(row3, text="▶ 开始处理", command=self._start_process).pack(side=tk.LEFT, padx=2)
        self._cancel_btn = ttk.Button(row3, text="✕ 取消", command=self._cancel_process, state=tk.DISABLED)
        self._cancel_btn.pack(side=tk.LEFT, padx=2)

        self._progress = ttk.Progressbar(param, mode="determinate")
        self._progress.pack(fill=tk.X, pady=(4, 2))
        self._progress_label = ttk.Label(param, text="就绪")
        self._progress_label.pack()

        flist = ttk.LabelFrame(parent, text="CAD 图纸列表", padding=4)
        flist.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        tree_frame = ttk.Frame(flist)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "entities", "status")
        self._file_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self._file_tree.heading("name", text="文件名")
        self._file_tree.heading("entities", text="实体")
        self._file_tree.heading("status", text="状态")
        self._file_tree.column("name", width=240)
        self._file_tree.column("entities", width=50, anchor=tk.CENTER)
        self._file_tree.column("status", width=70, anchor=tk.CENTER)
        self._file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._file_tree.yview)
        self._file_tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._file_tree.bind("<<TreeviewSelect>>", self._on_file_select)
        self._file_tree.bind("<Double-1>", lambda e: self._preview_selected())

    def _build_right_panel(self, parent: ttk.Frame):
        preview_frame = ttk.LabelFrame(parent, text="图纸预览", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self._preview_area = ttk.Frame(preview_frame)
        self._preview_area.pack(fill=tk.BOTH, expand=True)

        self._preview_placeholder = ttk.Label(
            self._preview_area, text="选择文件后点击「预览选中」\n或双击文件列表",
            anchor=tk.CENTER, font=("Microsoft YaHei", 11)
        )
        self._preview_placeholder.pack(fill=tk.BOTH, expand=True)

    def _build_bottom_panel(self, parent: ttk.Frame):
        log_frame = ttk.LabelFrame(parent, text="处理日志 / 分析报告", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=2)

        self._log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD,
                                                      font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)

        action_frame = ttk.Frame(log_frame)
        action_frame.pack(fill=tk.X, pady=(2, 0))
        self._open_step_btn = ttk.Button(action_frame, text="打开 STEP 模型", command=self._open_step,
                                           state=tk.DISABLED)
        self._open_step_btn.pack(side=tk.LEFT, padx=2)
        self._open_folder_btn = ttk.Button(action_frame, text="打开输出目录", command=self._open_output_dir,
                                             state=tk.DISABLED)
        self._open_folder_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(action_frame, text="清空日志", command=self._clear_log).pack(side=tk.RIGHT, padx=2)

        self._last_output_dir = None
        self._last_step_path = None

    def _log(self, message: str):
        self._log_text.insert(tk.END, message + "\n")
        self._log_text.see(tk.END)
        self.root.update_idletasks()

    def _clear_log(self):
        self._log_text.delete("1.0", tk.END)

    def _select_dir(self):
        d = filedialog.askdirectory(title="选择 CAD 文件目录")
        if d:
            self._init_pipeline()
            if self.pipeline:
                self.pipeline.set_input_dir(d)
                self._log(f"输入目录: {d}")
                self._refresh_file_list()

    def _refresh_file_list(self):
        for item in self._file_tree.get_children():
            self._file_tree.delete(item)

        self._init_pipeline()
        if not self.pipeline:
            return

        files = self.pipeline.list_available_files()
        for f in files:
            size = f"{f['size'] / 1024:.1f} KB"
            self._file_tree.insert("", tk.END, values=(f["name"], size, ""))
        self._log(f"刷新完成，共 {len(files)} 个文件")

    def _on_file_select(self, event):
        sel = self._file_tree.selection()
        if sel:
            self._selected_file = self._file_tree.item(sel[0])["values"][0]

    def _preview_selected(self):
        fname = self._selected_file
        if not fname:
            self._log("请先在文件列表中选择一个文件")
            return

        preview_path = self._find_preview(fname)
        title = Path(fname).stem
        if preview_path:
            self._show_image(preview_path, title)
        else:
            self._generate_and_show_preview(fname)

    def _generate_and_show_preview(self, fname: str):
        import tempfile
        self._init_pipeline()
        if not self.pipeline:
            self._log("管道未就绪")
            return

        from src.cad_parser import CADParser
        file_path = self.pipeline.file_manager.resolve_file_path(fname)
        if not file_path:
            self._log(f"找不到文件: {fname}")
            return

        try:
            self._log(f"正在生成预览: {fname} ...")
            parser = CADParser(str(file_path), self.config.get("dxf_parser", {}))
            parser.parse()
            if len(parser.entities) == 0:
                self._log(f"预览: {fname} 未提取到实体，图纸可能为空或格式不支持")
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            parser.visualize(tmp.name)
            self._show_image(tmp.name, Path(fname).stem)
        except Exception as e:
            self._log(f"预览失败: {e}")

    def _find_preview(self, fname: str) -> str:
        """查找已缓存的预览图（仅当文件有效且不小于 500 字节时才使用）"""
        stem = Path(fname).stem
        dirs = [
            f"examples/output/{stem}/{stem}_preview.png",
            f"examples/output/{stem}/sample_preview.png",
            f"examples/output/{stem}_preview.png",
        ]
        for d in dirs:
            p = Path(d)
            if p.exists() and p.stat().st_size >= 500:
                return str(p)
        return ""

    def _show_image(self, path: str, title: str = ""):
        try:
            import matplotlib
            matplotlib.use("TkAgg")

            for w in self._preview_area.winfo_children():
                w.destroy()

            import matplotlib.image as mpimg
            img = mpimg.imread(path)
            self._preview_image = img
            self._preview_img_path = path
            self._preview_title = title

            self._preview_area.unbind("<Configure>")
            self._preview_area.bind("<Configure>", self._on_preview_resize, add="+")
            self._draw_preview()
        except Exception as e:
            self._log(f"显示预览失败: {e}")

    def _draw_preview(self):
        if self._preview_image is None:
            return
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import matplotlib.image as mpimg

        for w in self._preview_area.winfo_children():
            w.destroy()

        img = self._preview_image
        h, w = img.shape[:2]

        area_w = self._preview_area.winfo_width()
        area_h = self._preview_area.winfo_height()
        if area_w <= 1:
            area_w = 500
        if area_h <= 1:
            area_h = 400

        title_margin_inch = 0.30
        outer_margin_inch = 0.10
        dpi = 100

        max_w_inch = area_w / dpi - outer_margin_inch * 2
        max_h_inch = area_h / dpi - title_margin_inch - outer_margin_inch * 2

        fig_w = min(w / dpi, max_w_inch)
        fig_h = fig_w * (h / w)
        if fig_h > max_h_inch:
            fig_h = max_h_inch
            fig_w = fig_h * (w / h)

        total_h = fig_h + title_margin_inch

        fig = Figure(figsize=(fig_w, total_h), dpi=dpi, facecolor="#2b2b2b")
        ax = fig.add_axes([0, 0, 1, fig_h / total_h])
        ax.axis("off")
        ax.imshow(img, aspect="equal")

        if self._preview_title:
            fig.suptitle(self._preview_title, color="white", fontsize=14,
                         y=(total_h - 0.02) / total_h, va="top")

        canvas = FigureCanvasTkAgg(fig, master=self._preview_area)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.NONE, expand=False, anchor=tk.CENTER)
        self._preview_canvas = canvas

    def _on_preview_resize(self, event):
        if event.widget == self._preview_area and self._preview_image is not None:
            if hasattr(self, "_resize_after_id"):
                self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = self.root.after(150, self._draw_preview)

    def _start_process(self):
        self._init_pipeline()
        if not self.pipeline:
            self._log("管道未就绪")
            return

        if self.single_var.get():
            fname = self._selected_file
            if not fname:
                self._log("请先选择文件")
                return
            filenames = [fname]
        else:
            files = self.pipeline.list_available_files()
            filenames = [f["name"] for f in files]
            if not filenames:
                self._log("没有可处理的文件")
                return

        self._cancel_flag.clear()
        self._cancel_btn.config(state=tk.NORMAL)
        self._worker_thread = threading.Thread(
            target=self._process_files, args=(filenames,), daemon=True
        )
        self._worker_thread.start()
        self._poll_worker()

    def _cancel_process(self):
        self._cancel_flag.set()
        self._log("正在取消...")

    def _process_files(self, filenames: list):
        total = len(filenames)
        enable_ai = self.analysis_var.get()
        height = self.height_var.get()

        for idx, fname in enumerate(filenames):
            if self._cancel_flag.is_set():
                self._log_safe("已取消")
                break

            percent = int((idx / total) * 100)
            self._update_progress(percent, f"{idx + 1}/{total} 处理: {fname}")

            status = "处理中"
            self._update_file_status(fname, status)

            try:
                if enable_ai:
                    result = self.pipeline.process_file_intelligent(fname, height)
                else:
                    result = self.pipeline.process_file(fname, height, enable_analysis=False)

                if result.success:
                    status = "✓"
                    self._log_safe(f"[{idx + 1}/{total}] ✓ {fname}  实体: {result.entity_count}")
                    for key, path in result.output_paths.items():
                        self._log_safe(f"    {key}: {path}")
                    if idx == 0:
                        self._last_output_dir = str(
                            Path(result.output_paths.get("model_step", "")).parent
                            if result.output_paths else ""
                        )
                        self._last_step_path = result.output_paths.get("model_step", "")
                else:
                    status = "✗"
                    self._log_safe(f"[{idx + 1}/{total}] ✗ {fname}: {result.error_message or '未知错误'}")
            except Exception as e:
                status = "✗"
                self._log_safe(f"[{idx + 1}/{total}] ✗ {fname}: {e}")

            self._update_file_status(fname, status)

        self._update_progress(100, f"完成: {total} 个文件")
        self._update_buttons(enable=False)
        self._log_safe("=" * 55)
        self._log_safe("处理完成")

    def _log_safe(self, msg: str):
        self.root.after(0, self._log, msg)

    def _update_progress(self, value: int, label: str):
        self.root.after(0, lambda: self._progress.configure(value=value))
        self.root.after(0, lambda: self._progress_label.configure(text=label))

    def _update_file_status(self, fname: str, status: str):
        def _do():
            for item in self._file_tree.get_children():
                if self._file_tree.item(item)["values"][0] == fname:
                    vals = list(self._file_tree.item(item)["values"])
                    vals[2] = status
                    self._file_tree.item(item, values=vals)
                    break
        self.root.after(0, _do)

    def _update_buttons(self, enable: bool):
        state = tk.NORMAL if enable else tk.DISABLED
        self.root.after(0, lambda: self._cancel_btn.config(state=tk.DISABLED))
        if self._last_step_path:
            self.root.after(0, lambda: self._open_step_btn.config(state=tk.NORMAL))
        if self._last_output_dir:
            self.root.after(0, lambda: self._open_folder_btn.config(state=tk.NORMAL))

    def _poll_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            self.root.after(300, self._poll_worker)
        else:
            self._update_buttons(enable=False)

    def _open_step(self):
        if self._last_step_path and os.path.exists(self._last_step_path):
            os.startfile(self._last_step_path)
        else:
            self._log("STEP 文件不存在")

    def _open_output_dir(self):
        if self._last_output_dir and os.path.exists(self._last_output_dir):
            os.startfile(self._last_output_dir)
        else:
            self._log("输出目录不存在")


def main():
    root = tk.Tk()
    app = CADApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
