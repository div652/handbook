#!/usr/bin/env python3
"""Focused regressions for CLM_LIFE-4 structured AP routing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "d2411716-ed63-4513-8756-51f430561e46"
ALLOCATION_COMMENT = """Beneficiary Allocation
Policy: LC-2020-11467
Face Amount: $350,000.00
Emeka A. Okafor | Primary | 70% | $245,000.00
Chidi E. Okafor | Primary | 30% | $105,000.00
"""
NENNRWK_COMMENT = """SOP §7.2 review complete.

--- Beneficiary Allocation ---
Policy: LC-2020-11467 | Face Amount: $350,000.00
Beneficiary 1: Emeka A. Okafor | Designation: Primary | Split: 70% | Amount: $245,000.00
Beneficiary 2: Chidi E. Okafor | Designation: Primary | Split: 30% | Amount: $105,000.00
Analyst: RF | Date: 2026-04-10

CLM-910 and CLM-920 are not active. Allocation totals $350,000.00; route to AP for payout.
"""


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"),
        namespace,
    )
    return namespace["verify"]


class ClmLife4StructuredRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(_load_verify())

    def _evaluate(
        self,
        *,
        status: str = "Allocation Complete",
        transitions: list[object] | None = None,
        labels: list[str] | None = None,
        comment: str = ALLOCATION_COMMENT,
        other_issues: dict[str, object] | None = None,
        other_comments: dict[str, list[dict[str, str]]] | None = None,
    ) -> dict:
        issue = {
            "key": "CLM_LIFE-4",
            "fields": {
                "status": {"name": status},
                "labels": [] if labels is None else labels,
            },
            "transitions": [] if transitions is None else transitions,
        }
        issues = {"CLM_LIFE-4": issue}
        issues.update(other_issues or {})
        comments = {"CLM_LIFE-4": [{"body": comment}]}
        comments.update(other_comments or {})
        state = {
            "issues": issues,
            "comments": comments,
        }

        with tempfile.TemporaryDirectory() as temporary:
            external_services = Path(temporary)
            (external_services / "jira_state.json").write_text(json.dumps(state))
            return self.verify(temporary, temporary)

    def assert_not_routed(self, result: dict) -> None:
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Not routed to AP for payout", result["feedback"])

    def test_accepts_exact_structured_status(self) -> None:
        result = self._evaluate(status="Route to AP for Payout")
        self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_demonstrably_executed_structured_transition(self) -> None:
        result = self._evaluate(
            transitions=[
                {"name": "Route to AP for Payout", "executed": True}
            ],
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_cited_nennrwk_done_route_label_representation(self) -> None:
        # EV10: NENNrWK persisted CLM_LIFE-4 as Done with route-to-ap and
        # the complete allocation/routing comment after only Done/Open were exposed.
        result = self._evaluate(
            status="Done",
            labels=[
                "life-claim",
                "identity-verified",
                "allocation-complete",
                "route-to-ap",
            ],
            comment=NENNRWK_COMMENT,
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_rejects_missing_structured_routing(self) -> None:
        self.assert_not_routed(self._evaluate())

    def test_rejects_wrong_structured_routing(self) -> None:
        result = self._evaluate(
            status="Ready for Payout",
            transitions=[{"name": "Route to Claims Supervisor"}],
        )
        self.assert_not_routed(result)

    def test_rejects_route_label_without_completed_workflow(self) -> None:
        self.assert_not_routed(
            self._evaluate(status="Open", labels=["route-to-ap"])
        )

    def test_rejects_available_done_transition_before_completion(self) -> None:
        result = self._evaluate(
            status="Open",
            transitions=[
                {
                    "name": "To Done",
                    "to": {"name": "Done"},
                    "isAvailable": True,
                }
            ],
            labels=["route-to-ap"],
        )
        self.assert_not_routed(result)

    def test_rejects_available_literal_ap_transition_when_unexecuted(self) -> None:
        result = self._evaluate(
            status="Open",
            transitions=[
                {
                    "name": "Route to AP for Payout",
                    "to": {"name": "Route to AP for Payout"},
                    "isAvailable": True,
                    "executed": False,
                }
            ],
        )
        self.assert_not_routed(result)

    def test_rejects_unrelated_route_like_label(self) -> None:
        self.assert_not_routed(
            self._evaluate(status="Done", labels=["route-to-ap-review"])
        )

    def test_rejects_route_on_unrelated_issue(self) -> None:
        result = self._evaluate(
            status="Done",
            other_issues={
                "CLM_LIFE-99": {
                    "key": "CLM_LIFE-99",
                    "fields": {
                        "status": {"name": "Done"},
                        "labels": ["route-to-ap"],
                    },
                }
            },
            other_comments={
                "CLM_LIFE-99": [
                    {"body": "Allocation complete; route to AP for payout."}
                ]
            },
        )
        self.assert_not_routed(result)

    def test_rejects_prose_only_routing_claim(self) -> None:
        result = self._evaluate(
            status="Done",
            comment=(
                ALLOCATION_COMMENT
                + "Claim was routed using Route to AP for Payout.\n"
            )
        )
        self.assert_not_routed(result)

    def test_rejects_routing_evidence_without_allocation(self) -> None:
        result = self._evaluate(
            status="Done",
            labels=["route-to-ap"],
            comment="CLM-910 and CLM-920 are not active; route to AP for payout.",
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Missing 'Beneficiary Allocation'", result["feedback"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
