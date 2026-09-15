#!/usr/bin/env python3
"""Focused regressions for Jira comment and workflow-state grading."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

MARCUS = "b46d7e62-0c85-4abc-954e-fac4dcdd21f7"
PRIYA = "0d769e20-3f9e-4232-ac90-a94d44757d50"
DEREK = "4bf7d578-d098-440d-bb0c-ed41ed11cd2c"
AISHA = "e55c834e-aa4a-48f9-acb2-9005dfc9d1ed"
JIRA_MANAGER_LOOKUP = "rubric_1776104913020"
MAIL_MANAGER_LOOKUP = "rubric_1776105354420"

EXPECTED = {
    MARCUS: (
        "OPS_HR_TE-2",
        "Approved",
        ["T&E review complete—all lines supported. OPS_HR_TE-2."],
    ),
    PRIYA: (
        "OPS_HR_TE-3",
        "Rejected",
        [
            "Missing business justification. Please submit personal "
            "reimbursement for line item: 1."
        ],
    ),
    DEREK: (
        "OPS_HR_TE-4",
        "Rejected",
        [
            "Unauthorized vendor. Please submit personal reimbursement "
            "for line item: 1."
        ],
    ),
    AISHA: (
        "OPS_HR_TE-5",
        "Rejected",
        [
            "Missing business justification. Please submit personal "
            "reimbursement for line items: 2, 3."
        ],
    ),
}

B9 = {
    "email_id": "b9",
    "folder": "Sent",
    "to_addr": "people@vanguardshield.com",
    "date": "2026-04-06T12:00:00Z",
    "subject": "[Reporting Manager Lookup] Derek Washington / EMP-2287",
    "body_text": (
        "[Reporting Manager Lookup]\n"
        "Employee: Derek Washington | ID: EMP-2287\n"
        "OPS-HR-TE / expense report issue: OPS_HR_TE-4\n"
        "Need: Reporting manager name and Jira username."
    ),
}

B8_TEXT = (
    "[T&E Manager Lookup]\n"
    "Employee: Derek Washington | ID: EMP-2287\n"
    "OPS-HR-TE / expense report issue: OPS_HR_TE-4\n"
    "Directory / People search result: Reporting Manager field blank; "
    "people@vanguardshield.com returned no match\n"
    "Need: Correct manager Jira username or Slack handle for Template B-2 notification."
)


def verifier(rubric_id: str):
    namespace = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


class JiraVerifierRegressions(unittest.TestCase):
    def evaluate(
        self,
        rubric_id: str,
        *,
        status: str | None = None,
        comments: list[str] | None = None,
    ) -> dict:
        issue_key, expected_status, expected_comments = EXPECTED[rubric_id]
        issue_status = expected_status if status is None else status
        issue_comments = expected_comments if comments is None else comments
        state = {
            "issues": {
                issue_key: {
                    "id": issue_key,
                    "key": issue_key,
                    "fields": {"status": {"name": issue_status}},
                }
            },
            "comments": {issue_key: issue_comments},
        }

        with tempfile.TemporaryDirectory() as temporary:
            external_services = Path(temporary)
            (external_services / "jira_state.json").write_text(json.dumps(state))
            return verifier(rubric_id)(temporary, temporary)

    def test_valid_comments_and_required_statuses_pass(self) -> None:
        for rubric_id in EXPECTED:
            with self.subTest(rubric_id=rubric_id):
                result = self.evaluate(rubric_id)
                self.assertTrue(result["pass"], result["feedback"])

    def test_positive_jira_criteria_hard_gate_on_workflow_status(self) -> None:
        wrong_status = {
            MARCUS: "Pending Approval",
            PRIYA: "Approved",
            DEREK: "Pending Approval",
            AISHA: "Approved",
        }
        for rubric_id, status in wrong_status.items():
            with self.subTest(rubric_id=rubric_id):
                result = self.evaluate(rubric_id, status=status)
                self.assertFalse(result["pass"])
                self.assertIn("must have status", result["feedback"])

    def test_missing_justification_and_reimbursement_must_share_a_comment(self) -> None:
        result = self.evaluate(
            PRIYA,
            comments=[
                "Missing business justification.",
                "Please submit personal reimbursement for line item: 1.",
            ],
        )
        self.assertFalse(result["pass"])
        self.assertIn("requires one comment", result["feedback"])

    def test_unauthorized_vendor_and_reimbursement_must_share_a_comment(self) -> None:
        result = self.evaluate(
            DEREK,
            comments=[
                "Unauthorized vendor.",
                "Please submit personal reimbursement for line item: 1.",
            ],
        )
        self.assertFalse(result["pass"])
        self.assertIn("requires one comment", result["feedback"])

    def test_unrelated_digit_cannot_supply_reimbursement_line_number(self) -> None:
        result = self.evaluate(
            PRIYA,
            comments=[
                "Missing business justification. Please submit personal "
                "reimbursement for line item.",
                "Audit batch 1 was reviewed.",
            ],
        )
        self.assertFalse(result["pass"])

    def test_line_item_ten_does_not_match_line_item_one(self) -> None:
        for rubric_id, reason in (
            (PRIYA, "Missing business justification"),
            (DEREK, "Unauthorized vendor"),
        ):
            with self.subTest(rubric_id=rubric_id):
                result = self.evaluate(
                    rubric_id,
                    comments=[
                        f"{reason}. Please submit personal reimbursement "
                        "for line item: 10."
                    ],
                )
                self.assertFalse(result["pass"])

    def test_singleton_reimbursements_accept_singular_and_plural_forms(self) -> None:
        for rubric_id, reason in (
            (PRIYA, "Missing business justification"),
            (DEREK, "Unauthorized vendor"),
        ):
            for rendering in (
                "line item: 1",
                "line item 1",
                "line items: 1",
                "line items 1",
            ):
                with self.subTest(rubric_id=rubric_id, rendering=rendering):
                    result = self.evaluate(
                        rubric_id,
                        comments=[
                            f"{reason}. Please submit personal reimbursement "
                            f"for {rendering}."
                        ],
                    )
                    self.assertTrue(result["pass"], result["feedback"])

    def test_singleton_reimbursements_reject_non_exact_line_sets(self) -> None:
        for rubric_id, reason in (
            (PRIYA, "Missing business justification"),
            (DEREK, "Unauthorized vendor"),
        ):
            for rendering in (
                "line items: 1, 3",
                "line items: 1 and 3",
                "line items: 3 and 1",
                "line items: 1, 1",
                "line item: 3",
                "line items: 1 or 3",
                "line items: 1 / 3",
                "line items: 1; 3",
                "line items: 1 plus 3",
                "line items: 1 and item 3",
            ):
                with self.subTest(rubric_id=rubric_id, rendering=rendering):
                    result = self.evaluate(
                        rubric_id,
                        comments=[
                            f"{reason}. Please submit personal reimbursement "
                            f"for {rendering}."
                        ],
                    )
                    self.assertFalse(result["pass"], result["feedback"])

    def test_singleton_reimbursements_ignore_unrelated_number_one(self) -> None:
        for rubric_id, reason in (
            (PRIYA, "Missing business justification"),
            (DEREK, "Unauthorized vendor"),
        ):
            for instruction in (
                "line item. Audit batch 1 was reviewed.",
                "line item 3. Audit batch 1 was reviewed.",
            ):
                with self.subTest(rubric_id=rubric_id, instruction=instruction):
                    result = self.evaluate(
                        rubric_id,
                        comments=[
                            f"{reason}. Please submit personal reimbursement for "
                            f"{instruction}"
                        ],
                    )
                    self.assertFalse(result["pass"], result["feedback"])

    def test_aisha_accepts_equivalent_exact_line_item_sets(self) -> None:
        for rendering in (
            "line items: 2, 3",
            "line items 2 and 3",
            "line items: 3 & 2",
            "line items: 2, and 3",
        ):
            with self.subTest(rendering=rendering):
                result = self.evaluate(
                    AISHA,
                    comments=[
                        "Missing business justification. Please submit personal "
                        f"reimbursement for {rendering}."
                    ],
                )
                self.assertTrue(result["pass"], result["feedback"])

    def test_aisha_rejects_missing_or_extra_line_items(self) -> None:
        for rendering in (
            "line items: 2",
            "line items: 3",
            "line items: 2, 3, 4",
            "line items: 2 and 3 and 4",
            "line items: 2, 2, 3",
        ):
            with self.subTest(rendering=rendering):
                result = self.evaluate(
                    AISHA,
                    comments=[
                        "Missing business justification. Please submit personal "
                        f"reimbursement for {rendering}."
                    ],
                )
                self.assertFalse(result["pass"], result["feedback"])

    def test_aisha_does_not_take_missing_line_number_from_unrelated_text(self) -> None:
        result = self.evaluate(
            AISHA,
            comments=[
                "Missing business justification. Please submit personal "
                "reimbursement for line item 2. Audit line 3 was reviewed."
            ],
        )
        self.assertFalse(result["pass"], result["feedback"])

    def test_aisha_reason_and_reimbursement_clause_must_share_a_comment(self) -> None:
        result = self.evaluate(
            AISHA,
            comments=[
                "Missing business justification.",
                "Please submit personal reimbursement for line items 2 and 3.",
            ],
        )
        self.assertFalse(result["pass"], result["feedback"])


class ManagerLookupRegressions(unittest.TestCase):
    def evaluate(self, *, jira: dict, mail: dict) -> tuple[dict, dict]:
        with tempfile.TemporaryDirectory() as temporary:
            external_services = Path(temporary)
            (external_services / "jira_state.json").write_text(json.dumps(jira))
            (external_services / "mailbox.json").write_text(json.dumps(mail))
            return (
                verifier(JIRA_MANAGER_LOOKUP)(temporary, temporary),
                verifier(MAIL_MANAGER_LOOKUP)(temporary, temporary),
            )

    @staticmethod
    def jira_b8(created: str | None = "2026-04-06T15:00:00Z") -> dict:
        fields = {
            "summary": "Manager Lookup Needed - T&E Exception - Derek Washington/EMP-2287",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": B8_TEXT}],
                    }
                ],
            },
            "project": {"key": "HR-OPS", "name": "HR-Ops"},
        }
        if created is not None:
            fields["created"] = created
        return {"id": "20001", "key": "HR-OPS-1", "fields": fields}

    @staticmethod
    def mail_b8(date: str | None = "2026-04-06T15:00:00Z") -> dict:
        email = {
            "email_id": "b8",
            "folder": "Sent",
            "to_addr": "hrops@vanguardshield.com",
            "subject": "Manager Lookup Needed - T&E Exception",
            "body_text": B8_TEXT,
        }
        if date is not None:
            email["date"] = date
        return email

    def test_initial_b9_request_without_fallback_passes(self) -> None:
        jira_result, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": [deepcopy(B9)]},
        )
        self.assertTrue(jira_result["pass"], jira_result["feedback"])
        self.assertTrue(mail_result["pass"], mail_result["feedback"])

    def test_missing_initial_b9_evidence_fails_both_rules(self) -> None:
        jira_result, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": []},
        )
        self.assertFalse(jira_result["pass"])
        self.assertFalse(mail_result["pass"])
        self.assertIn("initial sent B-9", jira_result["feedback"])
        self.assertIn("initial sent B-9", mail_result["feedback"])

    def test_premature_task_related_fallback_fails(self) -> None:
        jira_result, _ = self.evaluate(
            jira={"issues": {"HR-OPS-1": self.jira_b8("2026-04-06T14:59:59Z")}},
            mail={"emails": [deepcopy(B9)]},
        )
        _, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": [deepcopy(B9), self.mail_b8("2026-04-06T14:59:59Z")]},
        )
        self.assertFalse(jira_result["pass"])
        self.assertFalse(mail_result["pass"])
        self.assertIn("premature", jira_result["feedback"])
        self.assertIn("premature", mail_result["feedback"])

    def test_correctly_timed_task_related_fallback_passes(self) -> None:
        jira_result, _ = self.evaluate(
            jira={"issues": {"HR-OPS-1": self.jira_b8()}},
            mail={"emails": [deepcopy(B9)]},
        )
        _, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": [deepcopy(B9), self.mail_b8()]},
        )
        self.assertTrue(jira_result["pass"], jira_result["feedback"])
        self.assertTrue(mail_result["pass"], mail_result["feedback"])

    def test_task_related_fallback_requires_hrops_channel(self) -> None:
        wrong_project = self.jira_b8()
        wrong_project["fields"]["project"] = {"key": "OPS", "name": "Operations"}
        jira_result, _ = self.evaluate(
            jira={"issues": {"OPS-20": wrong_project}},
            mail={"emails": [deepcopy(B9)]},
        )
        wrong_recipient = self.mail_b8()
        wrong_recipient["to_addr"] = "finance.ops@vanguardshield.com"
        _, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": [deepcopy(B9), wrong_recipient]},
        )
        self.assertFalse(jira_result["pass"])
        self.assertIn("not in the HR-Ops queue", jira_result["feedback"])
        self.assertFalse(mail_result["pass"])
        self.assertIn("was not sent to hrops@", mail_result["feedback"])

    def test_unrelated_manager_lookup_content_is_ignored(self) -> None:
        jira_result, mail_result = self.evaluate(
            jira={
                "issues": {
                    "HR-OPS-9": {
                        "key": "HR-OPS-9",
                        "fields": {
                            "summary": "Manager Lookup Needed - T&E Exception - Alex Lee",
                            "description": (
                                "[T&E Manager Lookup] Employee: Alex Lee | ID: EMP-9999; "
                                "unrelated cross-reference OPS_HR_TE-4"
                            ),
                        },
                    }
                }
            },
            mail={
                "emails": [
                    deepcopy(B9),
                    {
                        "email_id": "unrelated",
                        "folder": "Sent",
                        "to_addr": "hrops@vanguardshield.com",
                        "subject": "[T&E Manager Lookup] Alex Lee",
                        "body_text": (
                            "Employee: Alex Lee | ID: EMP-9999 | unrelated "
                            "cross-reference OPS_HR_TE-4"
                        ),
                    },
                ]
            },
        )
        self.assertTrue(jira_result["pass"], jira_result["feedback"])
        self.assertTrue(mail_result["pass"], mail_result["feedback"])

    def test_fallback_with_missing_timestamp_or_intervening_people_reply_fails(self) -> None:
        jira_result, _ = self.evaluate(
            jira={"issues": {"HR-OPS-1": self.jira_b8(None)}},
            mail={"emails": [deepcopy(B9)]},
        )
        self.assertFalse(jira_result["pass"])
        self.assertIn("no usable timestamp", jira_result["feedback"])

        people_reply = {
            "email_id": "reply",
            "folder": "INBOX",
            "from_addr": "people@vanguardshield.com",
            "date": "2026-04-06T13:00:00Z",
            "subject": "Re: [Reporting Manager Lookup] Derek Washington",
            "body_text": "EMP-2287 / OPS_HR_TE-4 manager identified.",
        }
        _, mail_result = self.evaluate(
            jira={"issues": {}},
            mail={"emails": [deepcopy(B9), people_reply, self.mail_b8()]},
        )
        self.assertFalse(mail_result["pass"])
        self.assertIn("People replied", mail_result["feedback"])


if __name__ == "__main__":
    unittest.main()
