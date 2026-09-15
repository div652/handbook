#!/usr/bin/env python3
"""Focused regressions for approved task-local evaluator corrections."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
MAIL_CRITERION_ID = "e01d14aa-f4d4-4d0f-9a39-cc6346aae71a"
BENEFITS_CRITERION_ID = "c00541bc-b57a-49ed-b06d-057405c12b32"
TRACKER_CRITERION_ID = "55468c98-2909-42a3-8a51-bf5ec83a2b1a"
RUBRICS = {
    item["id"]: item
    for item in json.loads((TESTS_DIR / "rubrics.json").read_text(encoding="utf-8"))
}
TRACKER_HEADERS = [
    "Case ID",
    "Employee ID",
    "Employee Name",
    "Leave Type(s)",
    "Start Date",
    "Expected End Date",
    "Actual End Date",
    "Continuous/Intermittent",
    "Hours Used",
    "Days Used",
    "Rolling FMLA Balance (hrs)",
    "Medical Cert Status",
    "Manager Notified",
    "Case Status",
    "Notes",
]
SEEDED_NOTES = (
    "Certified for recurring migraines; up to 2 days/month. Freq: up to 2x/mo; "
    "duration: 1 day per episode. Cert expires 08/01/2026."
)
VALID_CONTINUATION = (
    "04/13/2026: Employee asked whether accrued PTO may supplement FAMLI payments; "
    "payroll question routed to Teresa Vang."
)
SEED_EMAIL_11 = {
    "email_id": "11",
    "folder": "INBOX",
    "subject": "Question about PTO + FAMLI, and time off for my mom",
    "from_addr": "rosa.gutierrez@ridgelinegear.com",
    "to_addr": "leaves@ridgelinegear.com",
    "cc_addr": None,
    "bcc_addr": None,
    "date": "2026-04-13T07:52:00-06:00",
    "message_id": "<rgutierrez.20260413.0752@ridgelinegear.com>",
    "in_reply_to": None,
    "body_text": (
        "Hi,\n\n"
        "I heard from a Gabe (who was told by Teresa Vang) that I might be able to use my PTO "
        "on top of my FAMLI pay so I don't lose as much money when I take my intermittent "
        "medical leaves. Is that true?\n\n"
        "Also, my mom passed away last night. She lived in Mexico and the funeral will be there. "
        "My manager already knows. I need to take a full week off starting April 20th.\n\n"
        "Rosa Gutierrez (E1051)\nAssistant Production Lead"
    ),
}


def load_verifier(rubric_id: str = MAIL_CRITERION_ID):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"], namespace


def evaluate(emails: list[dict]) -> dict:
    verify, _ = load_verifier()
    with tempfile.TemporaryDirectory() as tmp:
        services = Path(tmp)
        (services / "mailbox.json").write_text(
            json.dumps({"emails": emails}),
            encoding="utf-8",
        )
        return verify(tmp, tmp)


def generated_forward(to_addr: str) -> dict:
    _, namespace = load_verifier()
    subject, block = namespace["_expected_forward"](SEED_EMAIL_11)
    return {
        "email_id": "sent-1",
        "folder": "Sent",
        "to_addr": to_addr,
        "cc_addr": None,
        "bcc_addr": None,
        "subject": subject,
        "body_text": "Please review." + block,
    }


def evaluate_benefits_post(text: str) -> dict:
    verify, _ = load_verifier(BENEFITS_CRITERION_ID)
    channel_id = "C_BENEFITS"
    messages = [
        {"ts": str(index), "text": f"Seeded benefits message {index}"}
        for index in range(1, 7)
    ]
    messages.append({"ts": "7", "text": text})
    state = {
        "channels": {channel_id: {"name": "benefits-team"}},
        "messages": {channel_id: messages},
    }
    with tempfile.TemporaryDirectory() as tmp:
        services = Path(tmp)
        (services / "slack_data.json").write_text(
            json.dumps(state),
            encoding="utf-8",
        )
        return verify(tmp, tmp)


def seeded_tracker_row(notes: str | None = None) -> list[object]:
    return [
        "LC-2026-0089",
        "E1051",
        "Rosa Gutierrez",
        "FMLA + FAMLI",
        datetime(2026, 2, 2),
        datetime(2026, 8, 1),
        None,
        "Intermittent",
        24,
        3,
        456,
        "Received – Sufficient",
        datetime(2026, 2, 3),
        "Open – Intermittent",
        notes if notes is not None else SEEDED_NOTES + " | " + VALID_CONTINUATION,
    ]


def dummy_tracker_row(index: int) -> list[object]:
    return [f"LC-DUMMY-{index:04d}"] + [None] * (len(TRACKER_HEADERS) - 1)


def evaluate_tracker(rows: list[list[object]]) -> dict:
    verify, _ = load_verifier(TRACKER_CRITERION_ID)
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Leave Tracker"
        ws.append(TRACKER_HEADERS)
        for row in rows:
            ws.append(row)
        wb.save(workspace / "leave_tracker.xlsx")
        wb.close()
        return verify(tmp, None)


class EvaluatorRegressionTests(unittest.TestCase):
    def test_benefits_post_accepts_bounded_unknown_end_date_forms(self) -> None:
        prefix = (
            "BEREAVEMENT ESCALATION: Rosa Gutierrez, Bereavement, "
            "04/20/2026, "
        )
        accepted = [
            "End date to confirm",
            "end date: to confirm",
            "to be confirmed",
            "[unknown]",
            "TBD",
            (
                "full week requested (end date to confirm). "
                "Employee requested a full week."
            ),
            "end date not specified (full week requested).",
            "end date not specified (employee requested a full week).",
        ]
        for end_date in accepted:
            with self.subTest(end_date=end_date):
                result = evaluate_benefits_post(prefix + end_date)
                self.assertTrue(result["pass"], result["feedback"])

    def test_benefits_post_rejects_unrelated_confirmation_and_wrong_dates(self) -> None:
        prefix = (
            "BEREAVEMENT ESCALATION: Rosa Gutierrez, Bereavement, "
            "04/20/2026, "
        )
        rejected = [
            "confirm with Rosa",
            "confirmation pending",
            "04/30/2026 (confirm with manager)",
            "End date 04/30/2026 to confirm",
            "to confirm payroll eligibility",
            "full week requested (confirm with Rosa)",
            "full week requested (end date 04/30/2026 to confirm)",
            "employee requested a full week (confirm with manager)",
        ]
        for end_date in rejected:
            with self.subTest(end_date=end_date):
                result = evaluate_benefits_post(prefix + end_date)
                self.assertFalse(result["pass"], result["feedback"])

    def test_newly_authored_teresa_email_is_not_mislabeled_as_forward(self) -> None:
        authored = {
            "email_id": "sent-1",
            "folder": "Sent",
            "to_addr": "teresa.vang@ridgelinegear.com",
            "cc_addr": None,
            "bcc_addr": None,
            "subject": "Payroll question for Rosa Gutierrez",
            "body_text": "Can accrued PTO supplement intermittent FAMLI wage replacement?",
        }
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), authored])
        self.assertTrue(result["pass"], result["feedback"])

    def test_teresa_forward_requires_generated_subject_and_exact_block(self) -> None:
        _, namespace = load_verifier()
        subject, block = namespace["_expected_forward"](SEED_EMAIL_11)
        self.assertEqual(
            subject,
            "Fwd: Question about PTO + FAMLI, and time off for my mom",
        )
        self.assertEqual(
            block,
            "\n\n---------- Forwarded message ---------\n"
            "From: rosa.gutierrez@ridgelinegear.com\n"
            "Date: 2026-04-13 07:52:00-06:00\n"
            "Subject: Question about PTO + FAMLI, and time off for my mom\n"
            "To: leaves@ridgelinegear.com\n\n"
            + SEED_EMAIL_11["body_text"],
        )

        exact_forward = generated_forward("teresa.vang@ridgelinegear.com")
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), exact_forward])
        self.assertFalse(result["pass"])
        self.assertIn("forward(s) of email 11", result["feedback"])

        wrong_subject = copy.deepcopy(exact_forward)
        wrong_subject["subject"] = "Payroll question for Rosa Gutierrez"
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), wrong_subject])
        self.assertTrue(result["pass"], result["feedback"])

        wrong_block = copy.deepcopy(exact_forward)
        wrong_block["body_text"] = "Newly authored summary of Rosa's question."
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), wrong_block])
        self.assertTrue(result["pass"], result["feedback"])

    def test_marcus_prohibition_remains_independent_of_forward_status(self) -> None:
        manager_note = {
            "email_id": "sent-2",
            "folder": "Sent",
            "to_addr": "marcus.evans@ridgelinegear.com",
            "cc_addr": None,
            "bcc_addr": None,
            "subject": "Schedule coverage",
            "body_text": "Rosa expects to be away next week.",
        }
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), manager_note])
        self.assertFalse(result["pass"])
        self.assertIn("no manager notification", result["feedback"])

    def test_recipient_fields_include_cc_and_bcc(self) -> None:
        teresa_cc = generated_forward("renata.silva@ridgelinegear.com")
        teresa_cc["cc_addr"] = ["teresa.vang@ridgelinegear.com"]
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), teresa_cc])
        self.assertFalse(result["pass"])

        marcus_bcc = {
            "email_id": "sent-3",
            "folder": "Sent",
            "to_addr": "renata.silva@ridgelinegear.com",
            "cc_addr": None,
            "bcc_addr": ["marcus.evans@ridgelinegear.com"],
            "subject": "Review request",
            "body_text": "Please review.",
        }
        result = evaluate([copy.deepcopy(SEED_EMAIL_11), marcus_bcc])
        self.assertFalse(result["pass"])
        self.assertIn("no manager notification", result["feedback"])

    def test_tracker_accepts_dated_payroll_continuation_variants(self) -> None:
        continuations = [
            VALID_CONTINUATION,
            (
                "04/13/2026 16:45 MT: Employee asked about PTO supplementation of FAMLI "
                "wage replacement; relayed to Payroll Lead via #payroll-coordination."
            ),
            (
                "04/13/2026: Employee asked about PTO use during FAMLI; payroll/pay interaction "
                "question referred to Teresa Vang."
            ),
        ]
        for continuation in continuations:
            rows = [seeded_tracker_row(SEEDED_NOTES + " | " + continuation)]
            rows.extend(dummy_tracker_row(index) for index in range(1, 47))
            with self.subTest(continuation=continuation):
                result = evaluate_tracker(rows)
                self.assertTrue(result["pass"], result["feedback"])

    def test_tracker_rejects_unchanged_or_unrelated_notes(self) -> None:
        invalid_notes = [
            SEEDED_NOTES,
            SEEDED_NOTES + " | 04/13/2026: Employee called about an address change.",
            SEEDED_NOTES + " | 04/13/2026: Bereavement request escalated to Benefits Manager.",
        ]
        for notes in invalid_notes:
            rows = [seeded_tracker_row(notes)]
            rows.extend(dummy_tracker_row(index) for index in range(1, 47))
            with self.subTest(notes=notes):
                result = evaluate_tracker(rows)
                self.assertFalse(result["pass"])
                self.assertIn("Notes issues", result["feedback"])

    def test_tracker_rejects_removed_prior_notes_or_other_field_changes(self) -> None:
        removed_prior = [seeded_tracker_row(VALID_CONTINUATION)]
        removed_prior.extend(dummy_tracker_row(index) for index in range(1, 47))
        result = evaluate_tracker(removed_prior)
        self.assertFalse(result["pass"])
        self.assertIn("seeded Notes content was removed or changed", result["feedback"])

        changed_field = seeded_tracker_row()
        changed_field[8] = 25
        rows = [changed_field]
        rows.extend(dummy_tracker_row(index) for index in range(1, 47))
        result = evaluate_tracker(rows)
        self.assertFalse(result["pass"])
        self.assertIn("Hours Used", result["feedback"])

    def test_tracker_requires_exactly_one_target_case(self) -> None:
        missing_rows = [dummy_tracker_row(index) for index in range(1, 48)]
        result = evaluate_tracker(missing_rows)
        self.assertFalse(result["pass"])
        self.assertIn("found 0", result["feedback"])

        duplicate_rows = [seeded_tracker_row(), seeded_tracker_row()]
        duplicate_rows.extend(dummy_tracker_row(index) for index in range(1, 46))
        result = evaluate_tracker(duplicate_rows)
        self.assertFalse(result["pass"])
        self.assertIn("found 2", result["feedback"])

    def test_tracker_still_rejects_new_rosa_bereavement_case(self) -> None:
        bereavement = dummy_tracker_row(9999)
        bereavement[2] = "Rosa Gutierrez"
        bereavement[3] = "Bereavement"
        rows = [seeded_tracker_row(), bereavement]
        rows.extend(dummy_tracker_row(index) for index in range(1, 46))
        result = evaluate_tracker(rows)
        self.assertFalse(result["pass"])
        self.assertIn("unexpected bereavement case", result["feedback"])


if __name__ == "__main__":
    unittest.main()
