# -*- coding: utf-8 -*-

import unittest
from tempfile import TemporaryDirectory

from src.utils.llm_telemetry import default_llm_telemetry_store


class TestLLMTelemetry(unittest.TestCase):
    def test_store_records_processing_run_id(self):
        with TemporaryDirectory() as tmpdir:
            store = default_llm_telemetry_store({
                "llm_telemetry_dir": tmpdir,
                "_processing_run_id": "gui_run_123",
            })
            span = store.start_call(
                stage="view_analysis",
                model="deepseek-chat",
                provider="deepseek",
                request={"messages": []},
                file_path="drawing.dxf",
            )

            span.finish(response={"usage": {"prompt_tokens": 1, "completion_tokens": 2}})

            records = store.read_recent()
            self.assertEqual(1, len(records))
            self.assertEqual("gui_run_123", records[0]["processing_run_id"])


if __name__ == "__main__":
    unittest.main()
