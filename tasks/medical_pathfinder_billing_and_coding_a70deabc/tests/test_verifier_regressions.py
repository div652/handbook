#!/usr/bin/env python3
"""Focused regressions for comprehensive-QC finding QI3."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = json.loads((TESTS_DIR / "rubrics.json").read_text())
CALENDAR_CRITERION = "6bc193bb-c945-4669-a1a4-f6c549ffd990"
SLACK_CRITERION = "b685ac26-6dc3-405a-9d4b-55f36e2d611f"
MAILBOX_CRITERION = "459b9697-95bd-4946-bad7-1e45a0cdbd94"
TARGET_SUMMARY = (
    "RCM Manager - Claim ID: CLM-2026-0048; Reason: Payer Dispute; "
    "Escalation Category: Operational"
)
SEED_SUMMARIES = (
    "CLM-2026-0005 TFL Deadline",
    "CLM-2026-0012 TFL Deadline",
    "CLM-2026-0018 TFL Deadline",
    "CLM-2026-0025 TFL Deadline",
    "CLM-2026-0052 TFL Deadline",
    "CLM-2026-0022 TFL Deadline",
    "CLM-2026-0029 TFL Deadline",
    "CLM-2026-0031 TFL Deadline",
    "CLM-2026-0033 TFL Deadline",
    "CLM-2026-0038 TFL Deadline",
    "CLM-2026-0041 TFL Deadline",
    "CLM-2026-0047 TFL Deadline",
    "CLM-2026-0048 TFL Deadline",
    "CLM-2026-0049 TFL Deadline",
)


def load_verify(criterion_id=MAILBOX_CRITERION):
    rubric = next(item for item in RUBRICS if item["id"] == criterion_id)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(rubric["verifier_code"], f"<{criterion_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


class CalendarIntervalRegressions(unittest.TestCase):
    def verify_interval(self, start_datetime: str, end_datetime: str):
        verify = load_verify(CALENDAR_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()

            events = {
                f"evt-{index}": {
                    "id": f"evt-{index}",
                    "summary": summary,
                }
                for index, summary in enumerate(SEED_SUMMARIES, start=1)
            }
            events["evt-15"] = {
                "id": "evt-15",
                "summary": TARGET_SUMMARY,
                "start": {
                    "dateTime": start_datetime,
                    "timeZone": "America/Chicago",
                },
                "end": {
                    "dateTime": end_datetime,
                    "timeZone": "America/Chicago",
                },
            }
            (services / "calendar_data.json").write_text(
                json.dumps({"events": events})
            )
            return verify(workspace, services)

    def test_exact_315_to_316_interval_passes(self):
        result = self.verify_interval(
            "2026-02-23T15:15:00-06:00",
            "2026-02-23T15:16:00-06:00",
        )

        self.assertTrue(result["pass"])
        self.assertEqual(result["score"], 1.0)
        self.assertIn("3:15 PM to 3:16 PM", result["feedback"])

    def test_zero_and_other_durations_fail(self):
        cases = (
            (
                "zero-duration",
                "2026-02-23T15:15:00-06:00",
                "2026-02-23T15:15:00-06:00",
            ),
            (
                "one-second",
                "2026-02-23T15:15:00-06:00",
                "2026-02-23T15:15:01-06:00",
            ),
            (
                "two-minute",
                "2026-02-23T15:15:00-06:00",
                "2026-02-23T15:17:00-06:00",
            ),
            (
                "shifted-one-minute",
                "2026-02-23T15:14:00-06:00",
                "2026-02-23T15:15:00-06:00",
            ),
        )
        for label, start_datetime, end_datetime in cases:
            with self.subTest(label=label):
                result = self.verify_interval(start_datetime, end_datetime)
                self.assertFalse(result["pass"])
                self.assertLess(result["score"], 1.0)
                self.assertIn("FAIL", result["feedback"])

    def test_explicit_chicago_timezone_allows_offset_free_wall_time(self):
        result = self.verify_interval(
            "2026-02-23T15:15:00",
            "2026-02-23T15:16:00",
        )

        self.assertTrue(result["pass"], result["feedback"])


class SlackContentRegressions(unittest.TestCase):
    def run_verifier(self, escalation_text: str, authorization_text: str):
        verify = load_verify(SLACK_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()
            slack = {
                "channels": {
                    "C1": {"id": "C1", "name": "escalations"},
                    "C2": {"id": "C2", "name": "special-authorization"},
                },
                "messages": {
                    "C1": [{"text": escalation_text}],
                    "C2": [{"text": authorization_text}],
                },
            }
            (services / "slack_data.json").write_text(json.dumps(slack))
            return verify(workspace, services)

    def test_required_content_with_operational_detail_passes(self):
        result = self.run_verifier(
            "RCM Manager - Claim ID: CLM-2026-0048; Reason: Payer Dispute; "
            "Escalation Category: Operational. Please review the attached recovery timeline.",
            "CLM-2026-0049 special action authorized — RA reviewed and logged.",
        )

        self.assertTrue(result["pass"], result["feedback"])

    def test_missing_required_content_fails(self):
        result = self.run_verifier(
            "RCM Manager - Claim ID: CLM-2026-0048; Reason: Payer Dispute",
            "CLM-2026-0049 special action authorized",
        )

        self.assertFalse(result["pass"])


class MailboxEvidenceRegressions(unittest.TestCase):
    def test_missing_mailbox_fails_closed(self):
        verify = load_verify()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()

            result = verify(workspace, services)

        self.assertFalse(result["pass"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("mailbox.json not found", result["feedback"])

    def test_malformed_mailbox_fails_closed(self):
        verify = load_verify()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text('{"emails": [')

            result = verify(workspace, services)

        self.assertFalse(result["pass"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("Unable to read valid mailbox.json", result["feedback"])

    def test_valid_mailbox_without_sent_email_passes(self):
        verify = load_verify()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()
            mailbox = {
                "emails": [
                    {"folder": "Inbox", "subject": "Existing message"},
                    {"folder": "Drafts", "subject": "Unsent message"},
                ]
            }
            (services / "mailbox.json").write_text(json.dumps(mailbox))

            result = verify(workspace, services)

        self.assertTrue(result["pass"])
        self.assertEqual(result["score"], 1.0)
        self.assertIn("Total emails: 2", result["feedback"])


if __name__ == "__main__":
    unittest.main()
