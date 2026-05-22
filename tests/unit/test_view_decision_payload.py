# -*- coding: utf-8 -*-

import json
from types import SimpleNamespace

from src.intelligent_analyzer.llm_view_analyzer import LLMViewAnalyzer
from src.intelligent_analyzer.view_decision_payload import build_view_decision_payload


def test_view_decision_payload_excludes_wide_context_and_media_policy():
    payload = build_view_decision_payload(
        geometry_data={
            "version": "R2000",
            "units": "mm",
            "entities": [
                {
                    "type": "LINE",
                    "layer": "0",
                    "start": [0, 0],
                    "end": [10, 0],
                    "handle": "raw-1",
                },
                {
                    "type": "CIRCLE",
                    "layer": "0",
                    "center": [20, 10],
                    "radius": 5,
                    "handle": "raw-2",
                },
            ],
        },
        rule_result={
            "detection_method": "projection_split",
            "total_entities": 2,
            "views": [
                {
                    "name": "main",
                    "type": "主视图",
                    "bbox": [0, 0, 10, 10],
                    "centroid": [5, 5],
                    "entity_count": 1,
                    "entities": [{"type": "LINE", "start": [0, 0], "end": [10, 0]}],
                }
            ],
            "relationships": [
                {
                    "type": "projection",
                    "views": ["main", "right"],
                    "description": "Y方向高平齐",
                }
            ],
        },
        rule_standard={
            "drawing_type": "two_view",
            "confidence": 0.72,
            "reason_summary": "本地规则初判",
            "warnings": [],
        },
        dimension_data={
            "dimensions": [
                {
                    "text": "R15",
                    "value": 15.0,
                    "type": "半径",
                    "position": [12, 4],
                    "definition_points": [[1, 2], [3, 4]],
                }
            ],
            "statistics": {"半径": 1},
        },
        file_path="examples/cad_files/螺栓二视图.dwg",
        confidence_threshold=0.6,
    )

    assert list(payload) == [
        "task",
        "file_hint",
        "local_rule_summary",
        "layout_summary",
        "candidate_views",
        "projection_evidence",
        "dimension_summary",
        "output_contract",
    ]
    assert payload["file_hint"]["name"] == "螺栓二视图.dwg"
    assert payload["file_hint"]["policy"] == "weak_evidence_only"
    assert payload["layout_summary"]["entity_count"] == 2
    assert payload["layout_summary"]["type_count"] == {"LINE": 1, "CIRCLE": 1}
    assert "entities" not in payload["candidate_views"][0]
    assert "entity_samples" not in payload["layout_summary"]
    assert "schema" not in payload
    assert "media_inputs" not in payload
    assert "video_policy" not in json.dumps(payload, ensure_ascii=False)

    dimension = payload["dimension_summary"]["dimensions"][0]
    assert dimension == {
        "text": "R15",
        "value": 15.0,
        "type": "半径",
        "position": [12, 4],
    }


def test_llm_view_prompt_uses_view_decision_payload_contract():
    analyzer = LLMViewAnalyzer.__new__(LLMViewAnalyzer)
    analyzer.confidence_threshold = 0.6

    prompt = analyzer._build_prompt(
        geometry_data={"entities": [{"type": "LINE", "start": [0, 0], "end": [1, 1]}]},
        rule_result={"views": [], "relationships": []},
        rule_standard={"drawing_type": "unknown", "confidence": 0.72},
        dimension_data={"dimensions": []},
        file_path="part.dxf",
        preview_path="preview.png",
        media_inputs={"videos": ["input.mp4"], "video_frames": ["frame.png"]},
    )

    data = json.loads(prompt)
    assert "output_contract" in data
    assert "schema" not in data
    assert "media_inputs" not in data
    assert "entity_samples" not in prompt
    assert "videos" not in prompt
    assert "内容已截断" not in prompt


def test_llm_view_multimodal_paths_ignore_video_frames():
    analyzer = LLMViewAnalyzer.__new__(LLMViewAnalyzer)
    analyzer.config = {"view_max_images": 4}

    paths = analyzer._collect_image_paths(
        preview_path="preview.png",
        media_inputs={
            "images": ["extra.png"],
            "video_frames": ["frame.png"],
            "videos": ["input.mp4"],
        },
    )

    assert paths == ["preview.png", "extra.png"]


def test_llm_view_request_uses_deepseek_json_output():
    analyzer = LLMViewAnalyzer.__new__(LLMViewAnalyzer)
    analyzer.enabled = True
    analyzer.config = {"view_disable_thinking": False}
    analyzer.model = "deepseek-v4-pro"
    analyzer.confidence_threshold = 0.6
    analyzer.enable_multimodal = False
    analyzer.validator = SimpleNamespace(validate=lambda result, geometry=None: (True, []))
    analyzer.telemetry_store = SimpleNamespace(
        start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
    )
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        content = json.dumps({
            "analysis_id": "view_test",
            "timestamp": "2026-05-22T00:00:00+00:00",
            "drawing_type": "single_view",
            "views": [],
            "relationships": [],
            "confidence": 0.9,
            "evidence": [],
            "reason_summary": "ok",
            "warnings": [],
        })
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])

    analyzer.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    analyzer.refine_view_analysis(
        geometry_data={"entities": []},
        rule_result={"views": [], "relationships": []},
    )

    assert calls[0]["response_format"] == {"type": "json_object"}
