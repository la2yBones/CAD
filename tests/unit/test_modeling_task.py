# -*- coding: utf-8 -*-

from src.reconstruction.modeling_task import ModelingTaskBuilder


def test_modeling_task_payload_excludes_raw_context_and_entities():
    payload = ModelingTaskBuilder().build(
        part_semantics={
            "part_type": "bolt",
            "confidence": 0.91,
            "summary": "六角头螺栓",
            "base_features": [{"name": "hex_head"}],
            "key_dimensions": [{"name": "radius", "value": 15.0}],
            "path_clarification_fallback": {"missing_fields": ["radius_surface"]},
            "uncertainties": ["R15位置需保守处理"],
        },
        reconstruction_context={
            "source_entities": [{"type": "LINE"}],
            "local_geometry": {"entity_pairs": [{"a": 1, "b": 2}]},
            "view_analysis": {"views": [{"entities": [{"type": "CIRCLE"}]}]},
            "user_modeling_hint": "主体先生成，细节可以跳过。",
            "semantic_policy": {
                "dimension_source": "annotation",
                "dimension_plan": {
                    "allowed_dimensions": [
                        {"text": "R15", "value": 15.0, "role": "radius"}
                    ],
                    "unresolved_dimensions": [
                        {"text": "24", "value": 24.0, "role": "unresolved_linear"}
                    ],
                },
            },
        },
        modeling_path_decision={
            "modeling_path": "semantic_reconstruction",
            "reason": "无专用路径满足当前契约",
        },
    )

    assert set(payload) == {
        "task_version",
        "object",
        "features",
        "dimensions",
        "constraints",
        "recovery_hints",
    }
    payload_text = repr(payload)
    assert "source_entities" not in payload_text
    assert "entity_pairs" not in payload_text
    assert "'entities'" not in payload_text
    assert payload["object"]["part_type"] == "bolt"
    assert payload["dimensions"]["allowed_dimensions"][0]["text"] == "R15"
    assert payload["recovery_hints"]["user_modeling_hint"] == "主体先生成，细节可以跳过。"
