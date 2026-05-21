# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from src.utils.cache import AnalysisCache
from src.utils.config import get_analysis_cache_settings


class TestAnalysisCache(unittest.TestCase):
    def test_cache_key_ignores_legacy_extrude_height(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.dxf"
            source.write_text("sample", encoding="utf-8")
            cache = AnalysisCache(cache_dir=str(Path(temp_dir) / "cache"))

            low = cache._generate_cache_key(str(source), 5.0, {"analysis_version": "v1"})
            high = cache._generate_cache_key(str(source), 25.0, {"analysis_version": "v1"})

            self.assertEqual(low, high)

    def test_cache_entries_do_not_expose_extrude_height(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.dxf"
            source.write_text("sample", encoding="utf-8")
            cache = AnalysisCache(cache_dir=str(Path(temp_dir) / "cache"))
            cache.set(str(source), None, {"ok": True}, analysis_params={"analysis_version": "v1"})

            entries = cache.list_entries()

            self.assertEqual(1, len(entries))
            self.assertNotIn("extrude_height", entries[0])

    def test_cache_settings_prefer_canonical_nested_config(self):
        settings = get_analysis_cache_settings({
            "cache": {
                "enable": False,
                "cache_dir": ".cache/from-nested",
                "default_ttl": 123,
            },
            "cache_dir": ".cache/from-legacy",
            "cache_ttl": 456,
        })

        self.assertFalse(settings["enabled"])
        self.assertEqual(".cache/from-nested", settings["cache_dir"])
        self.assertEqual(123, settings["default_ttl"])

    def test_cache_settings_keep_legacy_top_level_fallback(self):
        settings = get_analysis_cache_settings({
            "cache_dir": ".cache/from-legacy",
            "cache_ttl": 456,
        })

        self.assertTrue(settings["enabled"])
        self.assertEqual(".cache/from-legacy", settings["cache_dir"])
        self.assertEqual(456, settings["default_ttl"])


if __name__ == "__main__":
    unittest.main()
