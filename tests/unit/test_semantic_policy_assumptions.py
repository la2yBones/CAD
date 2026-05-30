# -*- coding: utf-8 -*-

from src.reconstruction.semantic_policy import (
    SemanticPolicyAssumptionBuilder,
)


def test_assumption_builder_preserves_base_assumptions_without_extra_signals():
    result = SemanticPolicyAssumptionBuilder().build(
        base_assumptions=["初始假设"],
        dimension_bindings=[],
        clarification_questions=[],
        user_modeling_hint=None,
    )

    assert result.assumptions == ["初始假设"]
    assert result.clarification_questions == []


def test_assumption_builder_adds_hint_assumption_and_unblocks_questions():
    result = SemanticPolicyAssumptionBuilder().build(
        base_assumptions=["初始假设"],
        dimension_bindings=[],
        clarification_questions=[{"id": "q1"}],
        user_modeling_hint="优先生成主体。",
    )

    assert result.clarification_questions == []
    joined = "\n".join(result.assumptions)
    assert "用户提供了补充建模提示" in joined
    assert "未结构化回答的追问不再阻塞本次局部恢复" in joined


def test_assumption_builder_adds_unresolved_linear_warning():
    result = SemanticPolicyAssumptionBuilder().build(
        base_assumptions=[],
        dimension_bindings=[
            {"semantic_role": "radius"},
            {"semantic_role": "unresolved_linear"},
        ],
        clarification_questions=[],
        user_modeling_hint=None,
    )

    assert result.assumptions == [
        "裸线性尺寸尚未完成语义绑定；在没有额外证据前，不得把它们擅自命名为总长、对边、对角、法兰直径或孔径。"
    ]
