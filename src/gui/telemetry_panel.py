# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk, messagebox

from src.utils.llm_telemetry import (
    LLMTelemetryStore,
    default_llm_telemetry_store,
    estimate_record_cost_cny,
    summarize_records,
)
from src.utils.config import load_config

logger = logging.getLogger(__name__)

__all__ = ["LLMTelemetryPanel"]


class LLMTelemetryPanel(ttk.Frame):
    """LLM call telemetry viewer."""

    def __init__(self, parent, app_config, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_config = app_config
        self.records: List[Dict] = []
        self._record_by_item: Dict[str, Dict] = {}
        self._records_by_group_item: Dict[str, List[Dict]] = {}
        self._last_signature = ""
        self._build_ui()
        self._poll()

    def _build_ui(self):
        summary = ttk.Frame(self)
        summary.pack(fill=tk.X, padx=5, pady=(5, 0))

        self.summary_vars = {
            "calls": tk.StringVar(value="调用次数: 0"),
            "tokens": tk.StringVar(value="总 Tokens: 0"),
            "cache": tk.StringVar(value="缓存命中: 0 / 0%"),
            "cost": tk.StringVar(value="估算费用: ¥0.0000"),
            "duration": tk.StringVar(value="总耗时: 0.0s"),
        }
        for var in self.summary_vars.values():
            ttk.Label(summary, textvariable=var, foreground="darkblue").pack(side=tk.LEFT, padx=(0, 14))
        ttk.Button(summary, text="刷新", command=self.refresh).pack(side=tk.RIGHT, padx=2)
        ttk.Button(summary, text="删除选中", command=self.delete_selected_records).pack(side=tk.RIGHT, padx=2)
        ttk.Button(summary, text="清空", command=self.clear_records).pack(side=tk.RIGHT, padx=2)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = (
            "time",
            "drawing",
            "stage",
            "model",
            "status",
            "total",
            "cache",
            "cost",
            "duration",
        )
        self.tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", height=8)
        self.tree.heading("#0", text="图纸 / 阶段")
        self.tree.column("#0", width=190, minwidth=140)
        headings = {
            "time": "时间",
            "drawing": "调用数",
            "stage": "阶段",
            "model": "模型",
            "status": "状态",
            "total": "总 Tokens",
            "cache": "缓存命中",
            "cost": "估算费用",
            "duration": "耗时(秒)",
        }
        widths = {
            "time": 155,
            "drawing": 65,
            "stage": 145,
            "model": 130,
            "status": 65,
            "total": 80,
            "cache": 80,
            "cost": 80,
            "duration": 95,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=50)
        self.tree.column("duration", minwidth=85, stretch=False)
        self.tree.column("cost", minwidth=80, stretch=False)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", self._open_record_window)
        self.tree.bind("<Delete>", lambda _event: self.delete_selected_records())

    def _telemetry_store(self):
        config = load_config()
        return default_llm_telemetry_store(config.get("api", {}).get("deepseek", {}))

    def _poll(self):
        self.refresh()
        self.after(1000, self._poll)

    def refresh(self):
        try:
            self.records = self._telemetry_store().read_recent(limit=1000)
            signature = "|".join(str(r.get("call_id", "")) for r in self.records[-200:])
            if signature != self._last_signature:
                self._last_signature = signature
                self._render_records()

            summary = summarize_records(self.records)
            self.summary_vars["calls"].set(f"调用次数: {summary.get('call_count', 0)}")
            self.summary_vars["tokens"].set(f"总 Tokens: {summary.get('total_tokens', 0):,}")
            self.summary_vars["cache"].set(
                "缓存命中: {hit:,} / {rate:.0%}".format(
                    hit=summary.get("prompt_cache_hit_tokens", 0),
                    rate=summary.get("prompt_cache_hit_rate", 0.0),
                )
            )
            self.summary_vars["cost"].set(f"估算费用: ¥{float(summary.get('cost_cny') or 0.0):.4f}")
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
            self.summary_vars["cache"].set("缓存命中: 0 / 0%")
            self.summary_vars["cost"].set("估算费用: ¥0.0000")
            self.summary_vars["duration"].set("总耗时: 0.0s")
            logger.info("大模型调用记录已清空")
        except Exception as e:
            messagebox.showerror("清空失败", f"清空大模型调用记录时出错:\n{e}")

    def _selected_records(self) -> List[Dict]:
        records: List[Dict] = []
        seen_call_ids = set()
        for item in self.tree.selection():
            item_records = []
            if item in self._record_by_item:
                item_records = [self._record_by_item[item]]
            elif item in self._records_by_group_item:
                item_records = self._records_by_group_item[item]

            for record in item_records:
                call_id = str(record.get("call_id") or id(record))
                if call_id in seen_call_ids:
                    continue
                seen_call_ids.add(call_id)
                records.append(record)
        return records

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
        self._records_by_group_item.clear()

        for group in reversed(self._build_processing_groups(self.records)):
            records = group["records"]
            latest = records[-1]
            totals = self._sum_tokens(records)
            duration = sum(float(record.get("duration_seconds") or 0.0) for record in records)
            status_values = [str(record.get("status") or "") for record in records]
            status = "error" if "error" in status_values else status_values[0]
            parent_values = (
                self._display_timestamp(latest.get("timestamp", "")),
                len(records),
                f"{len(records)} 个阶段",
                latest.get("model", ""),
                self._display_status(status),
                totals["total_tokens"],
                totals["prompt_cache_hit_tokens"],
                self._format_cost(totals["cost_cny"]),
                round(duration, 3),
            )
            parent = self.tree.insert(
                "",
                tk.END,
                text=group["label"],
                values=parent_values,
                open=False,
            )
            self._records_by_group_item[parent] = records

            for record in reversed(records):
                tokens = record.get("tokens") or {}
                values = (
                    self._display_timestamp(record.get("timestamp", "")),
                    "",
                    self._display_stage(record.get("stage", "")),
                    record.get("model", ""),
                    self._display_status(record.get("status", "")),
                    tokens.get("total_tokens", 0),
                    tokens.get("prompt_cache_hit_tokens") or tokens.get("cached_tokens", 0),
                    self._format_cost(self._record_cost_cny(record)),
                    record.get("duration_seconds", 0.0),
                )
                item = self.tree.insert(
                    parent,
                    tk.END,
                    text=self._display_stage(record.get("stage", "")),
                    values=values,
                )
                self._record_by_item[item] = record

    def _build_processing_groups(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        active_by_key: Dict[str, Dict[str, Any]] = {}
        run_groups: Dict[str, Dict[str, Any]] = {}

        for record in records:
            run_id = str(record.get("processing_run_id") or "").strip()
            group_keys = self._record_group_keys(record)
            if run_id:
                group_key = f"run:{run_id}"
                group = run_groups.get(group_key)
                if group is None:
                    group = self._new_record_group(record)
                    group["run_id"] = run_id
                    run_groups[group_key] = group
                    groups.append(group)
                group["records"].append(record)
                continue

            group = next((active_by_key.get(key) for key in group_keys if key in active_by_key), None)
            stage = str(record.get("stage") or "")
            stages_seen = set(group.get("_stages_seen", set())) if group else set()
            should_start_new = (
                group is None
                or self._record_gap_seconds(group["records"][-1], record) > 120
                or (
                    stage in stages_seen
                    and stage in {
                        "view_analysis",
                        "semantic_adjudication",
                        "semantic_reconstruction",
                        "modeling_generation",
                    }
                )
            )
            if should_start_new:
                group = self._new_record_group(record)
                groups.append(group)
                for key in group_keys:
                    active_by_key[key] = group
                stages_seen = set()
            else:
                for key in group_keys:
                    active_by_key[key] = group

            group["records"].append(record)
            if stage:
                stages_seen.add(stage)
            group["_stages_seen"] = stages_seen
        return groups

    def _new_record_group(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "label": self._display_drawing_name(record) or "未关联图纸",
            "file_path": record.get("file_path"),
            "records": [],
            "run_id": record.get("processing_run_id"),
        }

    def _record_group_keys(self, record: Dict[str, Any]) -> List[str]:
        keys: List[str] = []
        file_path = str(record.get("file_path") or "").strip()
        if file_path:
            keys.append(f"file:{self._normalize_record_file_path(file_path)}")
        drawing = self._display_drawing_name(record)
        if drawing:
            keys.append(f"drawing:{drawing.lower()}")
        return keys or ["unknown"]

    @staticmethod
    def _normalize_record_file_path(file_path: str) -> str:
        try:
            path = Path(file_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            return str(path.resolve()).lower()
        except Exception:
            return str(file_path).replace("/", "\\").lower()

    def _record_gap_seconds(self, previous: Dict[str, Any], current: Dict[str, Any]) -> float:
        previous_time = self._parse_record_time(previous.get("timestamp"))
        current_time = self._parse_record_time(current.get("timestamp"))
        if not previous_time or not current_time:
            return 0.0
        return abs((current_time - previous_time).total_seconds())

    @staticmethod
    def _parse_record_time(timestamp: Any) -> Optional[datetime]:
        raw = str(timestamp or "")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def _sum_tokens(self, records: List[Dict]) -> Dict[str, Any]:
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "cost_cny": 0.0,
        }
        for record in records:
            tokens = record.get("tokens") or {}
            totals["prompt_tokens"] += int(tokens.get("prompt_tokens") or 0)
            totals["completion_tokens"] += int(tokens.get("completion_tokens") or 0)
            totals["total_tokens"] += int(tokens.get("total_tokens") or 0)
            totals["prompt_cache_hit_tokens"] += int(
                tokens.get("prompt_cache_hit_tokens") or tokens.get("cached_tokens") or 0
            )
            totals["cost_cny"] += self._record_cost_cny(record)
        totals["cost_cny"] = round(totals["cost_cny"], 6)
        return totals

    @staticmethod
    def _group_token_rate(completion_tokens: int, duration: float) -> float:
        if duration <= 0:
            return 0.0
        return round(completion_tokens / duration, 2)

    @staticmethod
    def _record_cost_cny(record: Dict[str, Any]) -> float:
        return estimate_record_cost_cny(record)

    @staticmethod
    def _format_cost(cost_cny: float) -> str:
        return f"¥{float(cost_cny or 0.0):.4f}"

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
            "semantic_adjudication": "图纸语义裁决",
            "semantic_reconstruction": "零件语义重建",
            "semantic_generation": "零件语义重建",
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
        item = selected[0]
        record = self._record_by_item.get(item)
        if not record:
            if item in self._records_by_group_item:
                self.tree.item(item, open=not bool(self.tree.item(item, "open")))
            return

        detail_win = tk.Toplevel(self)
        detail_win.title(
            f"\u5927\u6a21\u578b\u8c03\u7528\u8be6\u60c5 - {self._display_stage(record.get('stage', ''))} - {self._display_status(record.get('status', ''))}"
        )
        detail_win.geometry("900x650")
        from src.gui.helpers import center_window_on_parent
        center_window_on_parent(detail_win, self)

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
            "processing_run_id": record.get("processing_run_id"),
            "status": record.get("status"),
            "duration_seconds": record.get("duration_seconds"),
            "tokens": record.get("tokens"),
            "cost_cny": self._record_cost_cny(record),
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

        sections.extend([
            "\u54cd\u5e94\u5bf9\u8c61\uff1a",
            json.dumps(response, ensure_ascii=False, indent=2, default=str),
        ])
        return "\n".join(sections).rstrip()

    def _format_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, indent=2, default=str)
