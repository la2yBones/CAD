#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent store for batch clarification items."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .processor import CADProcessResult, PipelineStatus


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
        mode: str = "intelligent",
    ) -> Dict[str, Any]:
        if result.status != PipelineStatus.NEEDS_CLARIFICATION:
            raise ValueError("only needs_clarification results can be saved as pending")
        if not result.clarification_context:
            raise ValueError("pending clarification item requires clarification_context")

        now = datetime.now().isoformat(timespec="seconds")
        pending_id = self._pending_id(result.input_file)
        existing = self.load(pending_id)
        created_at = existing.get("created_at") if existing else now
        item = {
            "pending_id": pending_id,
            "status": PipelineStatus.NEEDS_CLARIFICATION.value,
            "input_file": result.input_file,
            "output_dir": output_dir,
            "extrude_height": extrude_height,
            "mode": mode,
            "clarification_questions": result.clarification_questions,
            "clarification_context": result.clarification_context,
            "summary": self._summary_for(result),
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
                items.append(item)
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return items

    def load(self, pending_id: str) -> Optional[Dict[str, Any]]:
        path = self._path_for(pending_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def mark_resolved(self, pending_id: str) -> Optional[Dict[str, Any]]:
        item = self.load(pending_id)
        if not item:
            return None
        item["status"] = "resolved"
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._path_for(pending_id).write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return item

    def _path_for(self, pending_id: str) -> Path:
        return self.store_dir / f"{pending_id}.json"

    @staticmethod
    def _pending_id(input_file: str) -> str:
        digest = hashlib.sha256(str(input_file).encode("utf-8")).hexdigest()[:16]
        return f"pending_{digest}"

    @staticmethod
    def _summary_for(result: CADProcessResult) -> str:
        question_count = len(result.clarification_questions)
        return f"{Path(result.input_file).name} 需要补充 {question_count} 项信息"
