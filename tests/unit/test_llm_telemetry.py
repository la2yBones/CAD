# -*- coding: utf-8 -*-

import unittest
from tempfile import TemporaryDirectory

from src.utils.llm_telemetry import (
    default_llm_telemetry_store,
    estimate_record_cost_cny,
    summarize_records,
)


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
            self.assertEqual(0, records[0]["tokens"]["prompt_cache_hit_tokens"])

    def test_store_records_deepseek_cache_usage_details(self):
        with TemporaryDirectory() as tmpdir:
            store = default_llm_telemetry_store({"llm_telemetry_dir": tmpdir})
            span = store.start_call(
                stage="semantic_generation",
                model="deepseek-v4-pro",
                provider="deepseek",
                request={"messages": []},
            )

            span.finish(response={
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_cache_hit_tokens": 60,
                    "prompt_cache_miss_tokens": 40,
                    "completion_tokens_details": {"reasoning_tokens": 5},
                }
            })

            record = store.read_recent()[0]
            self.assertEqual(60, record["tokens"]["prompt_cache_hit_tokens"])
            self.assertEqual(40, record["tokens"]["prompt_cache_miss_tokens"])
            self.assertNotIn("reasoning_tokens", record["tokens"])
            summary = summarize_records([record])
            self.assertEqual(60, summary["prompt_cache_hit_tokens"])
            self.assertEqual(40, summary["prompt_cache_miss_tokens"])
            self.assertEqual(0.6, summary["prompt_cache_hit_rate"])
            self.assertNotIn("reasoning_tokens", summary)
            self.assertNotIn("reasoning_tokens", summary["by_stage"]["semantic_generation"])

    def test_store_redacts_multimodal_data_urls(self):
        with TemporaryDirectory() as tmpdir:
            store = default_llm_telemetry_store({"llm_telemetry_dir": tmpdir})
            span = store.start_call(
                stage="view_analysis",
                model="kimi-k2.6",
                provider="moonshot",
                request={
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "data:image/png;base64," + "A" * 128
                                    },
                                }
                            ],
                        }
                    ]
                },
            )

            span.finish(response={"usage": {"prompt_tokens": 1}})

            record = store.read_recent()[0]
            url = record["request"]["messages"][0]["content"][0]["image_url"]["url"]
            self.assertIn("<redacted image data url", url)
            self.assertNotIn("AAAA", url)

    def test_estimates_cny_cost_from_deepseek_prices(self):
        record = {
            "model": "deepseek-v4-pro",
            "tokens": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "prompt_cache_hit_tokens": 600,
                "prompt_cache_miss_tokens": 400,
            },
        }

        self.assertEqual(0.002415, estimate_record_cost_cny(record))
        summary = summarize_records([record])
        self.assertEqual(0.002415, summary["cost_cny"])
        self.assertEqual(0.002415, summary["by_stage"]["unknown"]["cost_cny"])


if __name__ == "__main__":
    unittest.main()
