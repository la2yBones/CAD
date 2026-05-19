# -*- coding: utf-8 -*-
import unittest

from src.reconstruction.path_clarification import (
    apply_path_clarification_answers,
    build_path_clarification_payload,
    build_path_contract_pending_result,
    needs_path_clarification,
)
from src.reconstruction.clarification_response import ClarificationResponse


class TestPathClarification(unittest.TestCase):
    def test_path_contract_pending_result_pauses_modeling_execution(self):
        result = build_path_contract_pending_result({
            "clarification_questions": [{"id": "provide_extrusion_depth"}],
        })

        self.assertTrue(result["blocked_by_clarification"])
        self.assertTrue(result["blocked_by_path_contract"])
        self.assertEqual(
            [{"id": "provide_extrusion_depth"}],
            result["clarification_questions"],
        )

    def test_detects_contract_and_preference_pauses(self):
        self.assertTrue(needs_path_clarification({"blocked_by_path_contract": True}))
        self.assertTrue(needs_path_clarification({"requires_path_preference": True}))
        self.assertFalse(needs_path_clarification({"modeling_path": "revolve"}))

    def test_payload_attaches_recovery_state(self):
        base_context = {"geometry_data": {"entities": []}}
        payload = build_path_clarification_payload(
            modeling_result={"blocked_by_path_contract": True},
            base_context=base_context,
            policy_result={"dimension_source": "annotation"},
            adjudicated_context={"context_version": "v1"},
            part_semantics={"part_type": "profile"},
            modeling_path_decision={"modeling_path": "semantic_reconstruction"},
        )

        context = payload["clarification_context"]
        self.assertEqual("modeling_path", context["clarification_stage"])
        self.assertEqual({"dimension_source": "annotation"}, context["semantic_policy"])
        self.assertEqual({"context_version": "v1"}, context["adjudicated_context"])
        self.assertEqual({"part_type": "profile"}, context["part_semantics"])
        self.assertEqual(
            {"modeling_path": "semantic_reconstruction"},
            context["modeling_path_decision"],
        )
        self.assertNotIn("clarification_stage", base_context)

    def test_payload_ignores_non_path_results(self):
        self.assertEqual(
            {},
            build_path_clarification_payload(
                modeling_result={},
                base_context={"geometry_data": {}},
                policy_result={},
                adjudicated_context={},
                part_semantics={},
                modeling_path_decision={},
            ),
        )

    def test_answers_update_explicit_semantics(self):
        original = {
            "planar_modeling_semantics": {
                "extrusion_depth": None,
                "extrusion_direction": "unknown",
            },
            "preferred_modeling_path": None,
        }

        updated = apply_path_clarification_answers(
            original,
            {
                "provide_extrusion_depth": "12.5",
                "provide_extrusion_direction": "Z",
                "select_modeling_path": "planar_extrude",
                "user_modeling_hint": "主体先拉伸，槽可以跳过。",
            },
        )

        self.assertIsNone(original["planar_modeling_semantics"]["extrusion_depth"])
        self.assertEqual(12.5, updated["planar_modeling_semantics"]["extrusion_depth"])
        self.assertEqual("Z", updated["planar_modeling_semantics"]["extrusion_direction"])
        self.assertEqual("planar_extrude", updated["preferred_modeling_path"])
        self.assertEqual("主体先拉伸，槽可以跳过。", updated["user_modeling_hint"])

    def test_answers_accept_clarification_response_object(self):
        updated = apply_path_clarification_answers(
            {"planar_modeling_semantics": {}},
            ClarificationResponse(
                answers={"provide_extrusion_depth": "8"},
                user_modeling_hint="先做主体。",
            ),
        )

        self.assertEqual(8.0, updated["planar_modeling_semantics"]["extrusion_depth"])
        self.assertEqual("先做主体。", updated["user_modeling_hint"])
        self.assertEqual(
            "drawing_facts_override_user_hint",
            updated["user_modeling_hint_policy"],
        )
