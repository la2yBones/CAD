# -*- coding: utf-8 -*-

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.batch_processor import CADProcessResult, PendingClarificationStore, PipelineStatus


class TestPendingClarificationStore(unittest.TestCase):
    def test_save_load_and_list_pending_clarification_item(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="examples/cad_files/part.dxf")
            result.mark_needs_clarification(
                [
                    {
                        "id": "depth",
                        "text": "请补充拉伸深度",
                        "required": True,
                    }
                ],
                {
                    "session_id": "clar_123",
                    "semantic": {"shape": "bracket"},
                },
            )

            item = store.save(result, output_dir="examples/output", extrude_height=10.0)
            loaded = store.load(item["pending_id"])
            listed = store.list_pending()

            self.assertEqual(item["pending_id"], loaded["pending_id"])
            self.assertEqual("needs_clarification", loaded["status"])
            self.assertEqual("examples/cad_files/part.dxf", loaded["input_file"])
            self.assertEqual("examples/output", loaded["output_dir"])
            self.assertEqual(10.0, loaded["extrude_height"])
            self.assertEqual("clar_123", loaded["clarification_context"]["session_id"])
            self.assertEqual(["depth"], [q["id"] for q in loaded["clarification_questions"]])
            self.assertEqual([item["pending_id"]], [entry["pending_id"] for entry in listed])
            self.assertTrue(Path(tmpdir, f"{item['pending_id']}.json").exists())

    def test_save_uses_stable_id_for_same_input_file(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="drawing.dxf")
            result.mark_needs_clarification(
                [{"id": "main_size", "text": "请选择主尺寸"}],
                {"session_id": "clar_1"},
            )

            first = store.save(result, output_dir="out", extrude_height=10.0)
            second = store.save(result, output_dir="out", extrude_height=12.0)

            self.assertEqual(first["pending_id"], second["pending_id"])
            self.assertEqual(first["created_at"], second["created_at"])
            self.assertEqual(12.0, store.load(first["pending_id"])["extrude_height"])

    def test_mark_resolved_hides_item_from_pending_list(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="drawing.dxf")
            result.mark_needs_clarification(
                [{"id": "depth", "text": "请补充拉伸深度"}],
                {"session_id": "clar_1"},
            )

            item = store.save(result, output_dir="out", extrude_height=10.0)
            resolved = store.mark_resolved(item["pending_id"])

            self.assertEqual("resolved", resolved["status"])
            self.assertEqual([], store.list_pending())
            self.assertEqual("resolved", store.load(item["pending_id"])["status"])

    def test_save_rejects_non_clarification_result(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=True, input_file="drawing.dxf")
            result.status = PipelineStatus.COMPLETED

            with self.assertRaises(ValueError):
                store.save(result, output_dir="out", extrude_height=10.0)
