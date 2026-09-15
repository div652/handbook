#!/usr/bin/env python3
"""Focused regressions for the Vanguard Shield grading hard gates."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "vanguard_sop_verifier",
    Path(__file__).with_name("sop_verifier.py"),
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def issue(key: str, status: str, **fields: object) -> dict[str, object]:
    return {
        "id": {"OPS-3": "20001", "OPS-4": "20002", "OPS-5": "20003"}.get(key, "20007"),
        "key": key,
        "fields": {"status": {"name": status}, **fields},
    }


def base_jira() -> dict[str, object]:
    return {
        "issues": {
            "OPS-3": issue("OPS-3", "Rejected"),
            "OPS-4": issue("OPS-4", "Rejected"),
            "OPS-5": issue("OPS-5", "Approved"),
        },
        "comments": {},
    }


B2_TEXT = """[T&E Review Flag] - Employee ID: EMP-3312
Expense Date: Oct 1, 2026 | Amount: $144.00
Merchant: VSM Branded Water Bottles
Details: Shopify promo purchase not found.
Action Taken: Line item rejected in Jira OPS-HR-TE workflow. Please review with your direct report."""

B8_TEXT = """[T&E Manager Lookup]
Employee: Derek Huang | ID: EMP-4507
OPS-HR-TE / expense report issue: OPS-4
Directory / People search result: Reporting Manager field blank; people@vanguardshield.com returned no match
Need: Correct manager Jira username or Slack handle for Template B-2 notification."""


class ScenarioVerifierTests(unittest.TestCase):
    def test_ops4_and_ops5_positive_rubrics_are_status_gated(self) -> None:
        jira = base_jira()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = state_dir / "jira_state.json"
            path.write_text(json.dumps(jira))
            original_pass = {"pass": True, "score": 1.0, "feedback": "inline pass"}

            jira["issues"]["OPS-4"]["fields"]["status"]["name"] = "Pending Approval"
            path.write_text(json.dumps(jira))
            gated = verifier._apply_scenario_requirements(
                "6a839ad9-3949-4bf7-9002-63258e6e5e43", original_pass, state_dir
            )
            self.assertFalse(gated["pass"])

            jira["issues"]["OPS-4"]["fields"]["status"]["name"] = "Rejected"
            jira["issues"]["OPS-5"]["fields"]["status"]["name"] = "Pending Approval"
            path.write_text(json.dumps(jira))
            self.assertTrue(
                verifier._apply_scenario_requirements(
                    "rubric_1775880280596", original_pass, state_dir
                )["pass"]
            )
            self.assertFalse(
                verifier._apply_scenario_requirements(
                    "rubric_1776019924720", original_pass, state_dir
                )["pass"]
            )

    def test_b2_requires_every_authoritative_scenario_field(self) -> None:
        jira = base_jira()
        slack = {
            "channels": {"DU002": {"id": "DU002", "is_im": True, "user": "U002"}},
            "messages": {"DU002": [{"text": B2_TEXT}]},
        }
        self.assertTrue(verifier._verify_b2(jira, slack)["pass"])

        missing_merchant = deepcopy(slack)
        missing_merchant["messages"]["DU002"][0]["text"] = B2_TEXT.replace(
            "Merchant: VSM Branded Water Bottles\n", ""
        )
        self.assertFalse(verifier._verify_b2(jira, missing_merchant)["pass"])

        missing_action = deepcopy(slack)
        missing_action["messages"]["DU002"][0]["text"] = B2_TEXT.replace(
            " Please review with your direct report.", ""
        )
        self.assertFalse(verifier._verify_b2(jira, missing_action)["pass"])

    def test_b8_requires_complete_fields_and_prior_sent_directory_email(self) -> None:
        jira = base_jira()
        jira["issues"]["OPS-7"] = issue(
            "OPS-7",
            "Open",
            summary="Manager Lookup Needed – T&E Exception – Derek Huang/EMP-4507",
            description={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": B8_TEXT}],
                    }
                ],
            },
            created="2026-10-08T12:05:00Z",
        )
        mail = {
            "emails": [
                {
                    "folder": "Sent",
                    "to_addr": "people@vanguardshield.com",
                    "date": "2026-10-08T12:00:00Z",
                    "body_text": (
                        "Please provide the reporting manager for Derek Huang "
                        "(EMP-4507) for expense report OPS-4."
                    ),
                }
            ]
        }
        self.assertTrue(verifier._verify_b8(jira, mail)["pass"])
        self.assertFalse(verifier._verify_b8(jira, {"emails": []})["pass"])

        sent_after_creation = deepcopy(mail)
        sent_after_creation["emails"][0]["date"] = "2026-10-08T12:06:00Z"
        self.assertFalse(verifier._verify_b8(jira, sent_after_creation)["pass"])

        incomplete = deepcopy(jira)
        description = incomplete["issues"]["OPS-7"]["fields"]["description"]
        description["content"][0]["content"][0]["text"] = B8_TEXT.replace(
            "Need: Correct manager Jira username or Slack handle for Template B-2 notification.",
            "Need: Please investigate.",
        )
        self.assertFalse(verifier._verify_b8(incomplete, mail)["pass"])

    def test_ops3_duplicate_representations_and_recursive_adf_are_aggregated(self) -> None:
        jira = base_jira()
        jira["issues"]["OPS-3"]["fields"]["comment"] = {
            "comments": [{"body": "Water bottles rejected."}]
        }
        jira["stale_duplicate"] = {
            "key": "OPS-3",
            "fields": {
                "comment": {
                    "comments": [
                        {
                            "body": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "bulletList",
                                        "content": [
                                            {
                                                "type": "listItem",
                                                "content": [
                                                    {
                                                        "type": "paragraph",
                                                        "content": [
                                                            {
                                                                "type": "text",
                                                                "text": (
                                                                    "Capital Grille — Missing "
                                                                    "business justification"
                                                                ),
                                                            }
                                                        ],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    ]
                }
            },
        }
        result = verifier._verify_ops3_protected_lines(jira)
        self.assertFalse(result["pass"])

        jira["stale_duplicate"]["key"] = "OPS-30"
        self.assertTrue(verifier._verify_ops3_protected_lines(jira)["pass"])

        jira["comments"]["OPS-3"] = [
            {
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Hartwell Group: Missing business justification",
                                }
                            ],
                        }
                    ],
                }
            }
        ]
        self.assertFalse(verifier._verify_ops3_protected_lines(jira)["pass"])


if __name__ == "__main__":
    unittest.main()
