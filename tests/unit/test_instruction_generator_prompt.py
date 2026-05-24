# -*- coding: utf-8 -*-

from src.reconstruction.instruction_generator import FreeCADInstructionGenerator


def test_instruction_prompt_prioritizes_modeling_task_semantic_adjudication():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "dimensions.semantic_adjudication" in prompt
    assert "dimensions.modeling_dimensions" in prompt
    assert "SemanticAdjudicationView" in prompt
    assert "不得新增未裁决尺寸值" in prompt
    assert "不要再回头引用旧 dimension_plan" in prompt
    assert "只有 semantic_adjudication 缺失或 status=failed" in prompt
    assert "semantic_policy.dimension_plan.allowed_dimensions" not in prompt


def test_instruction_prompt_requires_freecad_edge_compatibility_helper():
    prompt = FreeCADInstructionGenerator.MODELING_SYSTEM_PROMPT

    assert "as_edge(obj)" in prompt
    assert "hasattr(obj, \"toShape\")" in prompt
    assert "不得直接链式写 `.toShape()`" in prompt
