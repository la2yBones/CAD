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
            result.modeling_path = "semantic_reconstruction"
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
            result.output_paths = {
                "geometry": "examples/output/part/part_geometry.json",
                "analysis_full": "examples/output/part/part_full.json",
                "analysis_report": "examples/output/part/part_report.txt",
            }

            item = store.save(result, output_dir="examples/output", extrude_height=10.0)
            loaded = store.load(item["pending_id"])
            listed = store.list_pending()

            self.assertEqual(item["pending_id"], loaded["pending_id"])
            self.assertEqual("needs_clarification", loaded["status"])
            self.assertEqual("examples/cad_files/part.dxf", loaded["input_file"])
            self.assertEqual("examples/output", loaded["output_dir"])
            self.assertEqual(10.0, loaded["extrude_height"])
            self.assertEqual("semantic_reconstruction", loaded["modeling_path"])
            self.assertEqual("clar_123", loaded["clarification_context"]["session_id"])
            self.assertEqual(
                "examples/output/part/part_full.json",
                loaded["output_paths"]["analysis_full"],
            )
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

    def test_load_deduplicates_existing_pending_questions(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="drawing.dxf")
            result.mark_needs_clarification(
                [
                    {"id": "depth", "text": "请补充拉伸深度"},
                    {"id": "depth", "text": "请补充拉伸深度"},
                ],
                {"session_id": "clar_1"},
            )

            item = store.save(result, output_dir="out", extrude_height=10.0)
            loaded = store.load(item["pending_id"])

            self.assertEqual(["depth"], [q["id"] for q in loaded["clarification_questions"]])
            self.assertEqual("drawing.dxf 需要补充 1 项信息", loaded["summary"])

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

    def test_save_recovery_accepts_partial_completed_result(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="drawing.dxf")
            result.modeling_path = "semantic_reconstruction"
            result.mark_partial_completed(
                skipped_features=[{"name": "R15", "reason": "need user hint"}],
                reason="主体模型已生成，R15 跳过",
            )
            result.clarification_questions = [
                {"id": "user_modeling_hint", "text": "请补充 R15 建模要求"}
            ]
            result.clarification_context = {"partial_modeling_recovery": True}
            result.output_paths = {"model_step": "out/drawing.step"}

            item = store.save_recovery(result, output_dir="out", extrude_height=10.0)
            loaded = store.load(item["pending_id"])

            self.assertEqual("needs_clarification", loaded["status"])
            self.assertEqual("partial_completed", loaded["source_status"])
            self.assertEqual("semantic_reconstruction", loaded["modeling_path"])
            self.assertEqual("R15", loaded["skipped_features"][0]["name"])
            self.assertEqual("out/drawing.step", loaded["output_paths"]["model_step"])
            self.assertEqual([item["pending_id"]], [entry["pending_id"] for entry in store.list_pending()])

    def test_mark_deleted_hides_item_without_removing_file(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=False, input_file="drawing.dxf")
            result.mark_needs_clarification(
                [{"id": "depth", "text": "请补充拉伸深度"}],
                {"session_id": "clar_1"},
            )

            item = store.save(result, output_dir="out", extrude_height=10.0)
            deleted = store.mark_deleted(item["pending_id"])

            self.assertEqual("deleted", deleted["status"])
            self.assertEqual([], store.list_pending())
            self.assertTrue(Path(tmpdir, f"{item['pending_id']}.json").exists())

    def test_save_rejects_non_clarification_result(self):
        with TemporaryDirectory() as tmpdir:
            store = PendingClarificationStore(tmpdir)
            result = CADProcessResult(success=True, input_file="drawing.dxf")
            result.status = PipelineStatus.COMPLETED

            with self.assertRaises(ValueError):
                store.save(result, output_dir="out", extrude_height=10.0)
