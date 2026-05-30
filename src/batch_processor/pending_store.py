#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent store for batch clarification items."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .processor import CADProcessResult, CADProcessor, PipelineStatus
from .pending_view_model import pending_recovery_summary

import logging
logger = logging.getLogger(__name__)


class PendingClarificationStore:
    """Stores paused batch items that can be resumed after GUI restart."""

    def __init__(self, store_dir: str = ".cache/batch_pending"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        result: CADProcessResult,
        *,
        output_dir: str,
        extrude_height: float,
    ) -> Dict[str, Any]:
        if result.status != PipelineStatus.NEEDS_CLARIFICATION:
            raise ValueError("only needs_clarification results can be saved as pending")
        if not result.clarification_context:
            raise ValueError("pending clarification item requires clarification_context")

        now = datetime.now().isoformat(timespec="seconds")
        pending_id = self._pending_id(result.input_file)
        existing = self.load(pending_id)
        created_at = existing.get("created_at") if existing else now
        clarification_questions = CADProcessor._deduplicate_clarification_questions(
            result.clarification_questions
        )
        item = {
            "pending_id": pending_id,
            "status": PipelineStatus.NEEDS_CLARIFICATION.value,
            "input_file": result.input_file,
            "output_dir": output_dir,
            "extrude_height": extrude_height,
            "modeling_path": result.modeling_path,
            "clarification_questions": clarification_questions,
            "clarification_context": result.clarification_context,
            "output_paths": result.output_paths,
            "summary": self._summary_for(result, clarification_questions),
            "created_at": created_at,
            "updated_at": now,
        }
        self._path_for(pending_id).write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return item

    def save_recovery(
        self,
        result: CADProcessResult,
        *,
        output_dir: str,
        extrude_height: float,
    ) -> Dict[str, Any]:
        if result.status == PipelineStatus.NEEDS_CLARIFICATION:
            return self.save(
                result,
                output_dir=output_dir,
                extrude_height=extrude_height,
            )
        if result.status != PipelineStatus.PARTIAL_COMPLETED:
            raise ValueError("only clarification or partial results can be saved for recovery")
        if not result.clarification_context or not result.clarification_questions:
            raise ValueError("partial recovery item requires clarification questions and context")

        now = datetime.now().isoformat(timespec="seconds")
        pending_id = self._pending_id(result.input_file)
        existing = self.load(pending_id)
        created_at = existing.get("created_at") if existing else now
        clarification_questions = CADProcessor._deduplicate_clarification_questions(
            result.clarification_questions
        )
        item = {
            "pending_id": pending_id,
            "status": PipelineStatus.NEEDS_CLARIFICATION.value,
            "source_status": PipelineStatus.PARTIAL_COMPLETED.value,
            "input_file": result.input_file,
            "output_dir": output_dir,
            "extrude_height": extrude_height,
            "modeling_path": result.modeling_path,
            "clarification_questions": clarification_questions,
            "clarification_context": result.clarification_context,
            "completed_features": result.completed_features,
            "skipped_features": result.skipped_features,
            "partial_completion_reason": result.partial_completion_reason,
            "output_paths": result.output_paths,
            "summary": self._summary_for(result, clarification_questions),
            "created_at": created_at,
            "updated_at": now,
        }
        self._path_for(pending_id).write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return item

    def list_pending(self) -> List[Dict[str, Any]]:
        items = []
        for path in self.store_dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if item.get("status") == PipelineStatus.NEEDS_CLARIFICATION.value:
                self._normalize_item(item)
                items.append(item)
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return items

    def load(self, pending_id: str) -> Optional[Dict[str, Any]]:
        path = self._path_for(pending_id)
        if not path.exists():
            return None
        item = json.loads(path.read_text(encoding="utf-8"))
        self._normalize_item(item)
        return item

    def mark_resolved(self, pending_id: str) -> Optional[Dict[str, Any]]:
        item = self.load(pending_id)
        if not item:
            return None
        item["status"] = "resolved"
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self._path_for(pending_id)
        try:
            path.unlink()
            logger.info("待恢复任务已解决并删除磁盘文件: %s", pending_id)
        except OSError as e:
            logger.warning("删除已解决的待恢复任务文件失败: %s: %s", pending_id, e)
        return item

    def mark_deleted(self, pending_id: str) -> Optional[Dict[str, Any]]:
        item = self.load(pending_id)
        if not item:
            return None
        item["status"] = "deleted"
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self._path_for(pending_id)
        try:
            path.unlink()
            logger.info("待恢复任务已删除磁盘文件: %s", pending_id)
        except OSError as e:
            logger.warning("删除待恢复任务文件失败: %s: %s", pending_id, e)
        return item

    def _path_for(self, pending_id: str) -> Path:
        return self.store_dir / f"{pending_id}.json"

    @staticmethod
    def _pending_id(input_file: str) -> str:
        digest = hashlib.sha256(str(input_file).encode("utf-8")).hexdigest()[:16]
        return f"pending_{digest}"

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> None:
        item["clarification_questions"] = CADProcessor._deduplicate_clarification_questions(
            item.get("clarification_questions") or []
        )
        if item.get("input_file"):
            item["summary"] = f"{Path(item['input_file']).name} {pending_recovery_summary(item)}"

    @staticmethod
    def _summary_for(
        result: CADProcessResult,
        clarification_questions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        question_count = len(
            clarification_questions
            if clarification_questions is not None
            else result.clarification_questions
        )
        context = result.clarification_context or {}
        if context.get("script_quality_recovery"):
            reason = "脚本质量恢复"
        elif context.get("partial_modeling_recovery") or result.status == PipelineStatus.PARTIAL_COMPLETED:
            reason = "部分建模恢复"
        elif context.get("pre_modeling_recovery"):
            reason = "建模前澄清"
        elif context.get("clarification_stage") == "modeling_path":
            reason = "路径澄清"
        else:
            reason = "语义澄清"
        return f"{Path(result.input_file).name} {reason}，需要补充 {question_count} 项信息"
