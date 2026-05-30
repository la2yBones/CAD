# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.reconstruction.instruction_generator import FreeCADInstructionGenerator


def test_instruction_prompt_prioritizes_modeling_task_semantic_adjudication():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "dimensions.modeling_dimensions" in prompt
    assert "唯一的已裁决建模尺寸池" in prompt
    assert "不得新增未裁决尺寸值" in prompt
    assert "dimensions.modeling_dimensions 缺失时" in prompt
    assert "candidate_dimensions" in prompt
    assert "binding_status=candidate" in prompt
    assert "features 中不再包含 key_dimensions" in prompt
    assert "recovery_hints 只用于说明恢复背景" in prompt
    assert "semantic_policy.dimension_plan.allowed_dimensions" not in prompt
    assert "features.key_dimensions" not in prompt


def test_instruction_prompt_requires_freecad_edge_compatibility_helper():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "as_edge(obj)" in prompt
    assert "hasattr(obj, \"toShape\")" in prompt
    assert "不得直接链式写 `.toShape()`" in prompt


def test_instruction_prompt_uses_circle_entities_as_hole_evidence():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "CIRCLE" in prompt
    assert "可执行孔位几何证据" in prompt
    assert "不得因为缺少孔距、定位尺寸" in prompt
    assert "点划线、中心线、构造线或隐藏线" in prompt


def test_instruction_prompt_forbids_cutting_outer_diameter_as_hole():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "outer_diameter" in prompt
    assert "外径" in prompt
    assert "不是孔径" in prompt
    assert "只能切除32孔" in prompt


def test_instruction_generation_postprocesses_modeling_metadata():
    generator = FreeCADInstructionGenerator.__new__(FreeCADInstructionGenerator)
    generator.config = {
        "user_id": "cad-model",
        "stage_thinking": {
            "modeling_generation": {
                "enabled": True,
                "reasoning_effort": "max",
            }
        },
    }
    generator.model = "deepseek-v4-pro"
    generator.constraints = SimpleNamespace(retry_reason=lambda result, context, semantics: "")
    generator.telemetry_store = SimpleNamespace(
        start_call=lambda **kwargs: SimpleNamespace(finish=lambda **finish_kwargs: None)
    )
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="{}"),
                )
            ]
        )

    generator._create_chat_completion = fake_completion
    generator._extract_json = lambda content: {
        "analysis_summary": "",
        "modeling_strategy": "",
        "freecad_script": "pass",
        "instructions": [],
        "key_dimensions": [
            {"name": "extrusion_depth", "value": 16.0},
            {"name": "guessed_height", "value": 99.0},
        ],
        "completed_features": [],
        "skipped_features": [
            {
                "name": "boss",
                "kind": "boss",
                "reason": "Height dimension missing.",
            }
        ],
        "partial_completion_reason": "",
        "warnings": ["Missing boss height; model may be incomplete."],
    }

    result = generator.generate(
        geometry_data={"entities": []},
        reconstruction_context={
            "dimensions": [
                {"text": "16", "value": 16.0},
                {"text": "99", "value": 99.0},
            ],
            "semantic_policy": {
                "dimension_source": "annotation",
                "drawing_evidence_package": {
                    "dimension_candidates": [
                        {"id": "D1", "text": "16", "value": 16.0}
                    ],
                    "derived_dimension_candidates": [],
                },
                "semantic_adjudication": {
                    "status": "completed",
                    "dimension_roles": [
                        {"dimension_id": "D1", "role": "extrusion_depth"}
                    ],
                    "derived_dimensions": [],
                },
            },
        },
        modeling_task_payload={
            "object": {},
            "features": {},
            "dimensions": {},
            "constraints": {},
            "recovery_hints": {},
        },
    )

    assert result["key_dimensions"] == [{"name": "extrusion_depth", "value": 16.0}]
    assert "guessed_height" not in repr(result)
    assert "非中文说明" in result["warnings"][0]
    assert "非中文说明" in result["skipped_features"][0]["reason"]
    assert "user_id" not in calls[0]
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled", "reasoning_effort": "max"}}
