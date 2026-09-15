#!/usr/bin/env python3
"""Focused regressions for the QI1 Jira case-logging evaluator repair."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}
JIRA_DETAILS = "847ec739-0f1c-4b09-baea-e72a664b9d57"
CASE_LOGGED = "rubric_1776341102360"
PRE_EXISTING_KEYS = [f"MCA_APPEALS-{number}" for number in range(1, 6)]


def verifier(rubric_id: str):
    namespace = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


def jira_state(*, new_issues=None):
    issues = {key: {"summary": f"Legacy issue {key}"} for key in PRE_EXISTING_KEYS}
    issues.update(new_issues or {})
    return {"issues": issues}


class JiraLoggingVerifierRegressions(unittest.TestCase):
    def run_both(self, jira_data, slack_data=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            services = root / "services"
            services.mkdir()
            (services / "jira_state.json").write_text(json.dumps(jira_data))
            if slack_data is not None:
                (services / "slack_data.json").write_text(json.dumps(slack_data))
            return {
                rubric_id: verifier(rubric_id)(str(root), str(services))
                for rubric_id in (JIRA_DETAILS, CASE_LOGGED)
            }

    def test_valid_new_issue_accepts_flexible_generated_key(self):
        results = self.run_both(
            jira_state(
                new_issues={
                    "CLAIMOPS-842": {
                        "fields": {
                            "summary": "CASE-2026-00091 expedited concurrent care appeal",
                            "description": (
                                "Member MBR-2026-04471; $88,500 disputed; parity review "
                                "assigned to Dr. Ontario."
                            ),
                        }
                    }
                }
            )
        )
        for rubric_id, result in results.items():
            self.assertTrue(result["pass"], (rubric_id, result["feedback"]))
            self.assertIn("CLAIMOPS-842", result["feedback"])

    def test_wrong_business_id_fails_despite_all_terms_and_slack_post(self):
        results = self.run_both(
            jira_state(
                new_issues={
                    "MCA_APPEALS-6": {
                        "summary": "MCA_APPEALS-6 expedited concurrent care appeal",
                        "description": (
                            "Case ID: MCA_APPEALS-6; MBR-2026-04471; $88,500; "
                            "parity; Dr. Ontario"
                        ),
                    }
                }
            ),
            slack_data={
                "messages": {
                    "C001": [{"text": "New appeal logged: CASE-2026-00091"}]
                }
            },
        )
        for rubric_id, result in results.items():
            self.assertFalse(result["pass"], (rubric_id, result["feedback"]))
            self.assertIn("CASE-2026-00091", result["feedback"])

    def test_substantive_terms_remain_required_by_detailed_jira_criterion(self):
        results = self.run_both(
            jira_state(
                new_issues={
                    "OTHERPROJECT-1": {
                        "summary": "CASE-2026-00091",
                        "description": "New appeal",
                    }
                }
            )
        )
        self.assertFalse(results[JIRA_DETAILS]["pass"])
        self.assertIn("3/5 substantive terms", results[JIRA_DETAILS]["feedback"])
        self.assertTrue(results[CASE_LOGGED]["pass"], results[CASE_LOGGED]["feedback"])

    def test_case_id_and_substantive_terms_must_be_on_same_new_issue(self):
        results = self.run_both(
            jira_state(
                new_issues={
                    "FLEX-1": {"summary": "CASE-2026-00091", "description": "Appeal"},
                    "FLEX-2": {
                        "summary": "Concurrent care parity appeal",
                        "description": "MBR-2026-04471; 88500; Dr. Ontario",
                    },
                }
            )
        )
        self.assertFalse(results[JIRA_DETAILS]["pass"])
        self.assertTrue(results[CASE_LOGGED]["pass"], results[CASE_LOGGED]["feedback"])

    def test_near_match_case_id_is_rejected(self):
        for near_match in ("CASE-2026-000910", "CASE-2026-00091-EXTRA"):
            with self.subTest(near_match=near_match):
                results = self.run_both(
                    jira_state(
                        new_issues={
                            "FLEXIBLE-999": {
                                "summary": f"{near_match} concurrent care parity",
                                "description": "MBR-2026-04471; 88500; Dr. Ontario",
                            }
                        }
                    )
                )
                for rubric_id, result in results.items():
                    self.assertFalse(result["pass"], (rubric_id, result["feedback"]))

    def test_generated_issue_key_alone_is_not_the_business_case_id(self):
        results = self.run_both(
            jira_state(
                new_issues={
                    "ARBITRARY-12": {
                        "key": "CASE-2026-00091",
                        "summary": "Concurrent care parity appeal",
                        "description": "MBR-2026-04471; 88500; Dr. Ontario",
                    }
                }
            )
        )
        for rubric_id, result in results.items():
            self.assertFalse(result["pass"], (rubric_id, result["feedback"]))


if __name__ == "__main__":
    unittest.main()
