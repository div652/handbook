#!/usr/bin/env python3
"""Focused regressions for the repaired Mojave Crest rubric verifiers."""

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

PROVIDER_SUBJECT_ID = "1cb3faea-7dcd-4223-ba22-82ef885c61ca"
PROVIDER_CONTENT_ID = "9b96be64-d380-48ad-8fa9-56149892311c"
NO_LOG_ROW_ID = "559f22cc-3db0-40a2-a652-6c39e79cafb9"
NO_ACK_ID = "13f466fd-60c9-4b1b-8f58-d34b5bbd1d92"

TARGET_SUBJECT = "Mojave Crest Request KPX658320914 - Information Needed"
COMPLETE_A2_TEXT = """Dear Dr. Avery Solis,
In order to complete our review, send the signed form within 15 calendar days.
Upload it at portal.mojavecrest.com.
Sincerely,
Ari Costa
Appeals & Grievances Coordinator
Mojave Crest Assurance Company
Phone: (702) 555-0148
"""


def _verify(rubric_id: str, workspace: Path, services: Path):
    namespace = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"](str(workspace), str(services))


def _mailbox(services: Path, emails: list[dict]) -> None:
    (services / "mailbox.json").write_text(json.dumps({"emails": emails}))


def _provider_message(**overrides):
    message = {
        "folder": "Archive",
        "from_addr": "Ari Costa <a.costa@mojavecrest.com>",
        "to_addr": "Dr. Avery Solis <asolis@griffinmedical.org>",
        "cc_addr": None,
        "bcc_addr": None,
        "subject": TARGET_SUBJECT,
        "body_text": COMPLETE_A2_TEXT,
        "attachments": [],
    }
    message.update(overrides)
    return message


class VerifierRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self.root / "workspace"
        self.services = self.root / "services"
        self.workspace.mkdir()
        self.services.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_outbound_provider_mail_uses_exact_parsed_addresses_not_folder(self):
        _mailbox(self.services, [_provider_message(folder="Filed")])
        self.assertTrue(_verify(PROVIDER_SUBJECT_ID, self.workspace, self.services)["pass"])

        _mailbox(
            self.services,
            [
                _provider_message(
                    folder="Sent",
                    from_addr=(
                        "a.costa@mojavecrest.com.evil.test, "
                        "a.costa@mojavecrest.com"
                    ),
                    to_addr=(
                        "not-asolis@griffinmedical.org, "
                        "asolis@griffinmedical.org.evil.test"
                    ),
                )
            ],
        )
        self.assertFalse(_verify(PROVIDER_SUBJECT_ID, self.workspace, self.services)["pass"])

    def test_unsent_provider_mail_does_not_satisfy_positive_criteria(self):
        for folder in ("Drafts", "Scheduled", "Trash"):
            with self.subTest(folder=folder):
                _mailbox(self.services, [_provider_message(folder=folder)])
                self.assertFalse(_verify(PROVIDER_SUBJECT_ID, self.workspace, self.services)["pass"])
                self.assertFalse(_verify(PROVIDER_CONTENT_ID, self.workspace, self.services)["pass"])

    def test_sent_or_filed_provider_mail_satisfies_positive_criteria(self):
        for folder in ("Sent", "Filed", "Archive"):
            with self.subTest(folder=folder):
                _mailbox(self.services, [_provider_message(folder=folder)])
                self.assertTrue(_verify(PROVIDER_SUBJECT_ID, self.workspace, self.services)["pass"])
                self.assertTrue(_verify(PROVIDER_CONTENT_ID, self.workspace, self.services)["pass"])

    def test_draft_acknowledgment_is_not_a_prohibited_sent_acknowledgment(self):
        acknowledgment = "Your appeal has been received and assigned Case ID KPX-2026-0512."
        _mailbox(self.services, [_provider_message(folder="Drafts", body_text=acknowledgment)])
        self.assertTrue(_verify(NO_ACK_ID, self.workspace, self.services)["pass"])

        _mailbox(self.services, [_provider_message(folder="Sent", body_text=acknowledgment)])
        self.assertFalse(_verify(NO_ACK_ID, self.workspace, self.services)["pass"])

    def test_content_requires_complete_readable_body_or_attachment(self):
        unreadable = self.workspace / "letter.pdf"
        unreadable.write_bytes(b"not a pdf")
        _mailbox(
            self.services,
            [
                _provider_message(
                    body_text="Dear Dr. Avery Solis, please see attached.",
                    attachments=[{"filename": unreadable.name}],
                )
            ],
        )
        result = _verify(PROVIDER_CONTENT_ID, self.workspace, self.services)
        self.assertFalse(result["pass"])
        self.assertIn("unreadable attachment evidence", result["feedback"])

        readable = self.workspace / "letter.txt"
        readable.write_text(COMPLETE_A2_TEXT)
        _mailbox(
            self.services,
            [
                _provider_message(
                    body_text="Please see the attached letter.",
                    attachments=[{"filename": readable.name}],
                )
            ],
        )
        self.assertTrue(_verify(PROVIDER_CONTENT_ID, self.workspace, self.services)["pass"])

        split = self.workspace / "split.txt"
        split.write_text("portal.mojavecrest.com\nAri Costa")
        _mailbox(
            self.services,
            [
                _provider_message(
                    body_text=(
                        "Dear Dr. Avery Solis. In order to complete our review, "
                        "reply within 15 calendar days."
                    ),
                    attachments=[{"filename": split.name}],
                )
            ],
        )
        self.assertFalse(_verify(PROVIDER_CONTENT_ID, self.workspace, self.services)["pass"])

    def test_missing_authoritative_workbook_fails_before_no_row_check(self):
        missing = _verify(NO_LOG_ROW_ID, self.workspace, self.services)
        self.assertFalse(missing["pass"])
        self.assertIn("Authoritative workbook", missing["feedback"])

        import openpyxl

        workbook = openpyxl.Workbook()
        workbook.active.append(["Member ID"])
        workbook.active.append(["OTHER123"])
        workbook.save(self.workspace / "appeals_log_master.xlsx")
        self.assertTrue(_verify(NO_LOG_ROW_ID, self.workspace, self.services)["pass"])

    def test_acknowledgment_scope_uses_sender_and_all_recipient_fields(self):
        internal_mention = _provider_message(
            to_addr="Appeals Team <appeals@mojavecrest.com>",
            body_text="Internal note: Jules Arden has Case ID CASE-1.",
        )
        inbound = _provider_message(
            from_addr="other@example.com",
            to_addr="Avery Solis <asolis@griffinmedical.org>",
            body_text="Your appeal has been received.",
        )
        _mailbox(self.services, [internal_mention, inbound])
        self.assertTrue(_verify(NO_ACK_ID, self.workspace, self.services)["pass"])

        for field, recipient in (
            ("to_addr", "Jules Arden <j.arden.71@gmail.com>"),
            ("cc_addr", "Jules Arden <j.arden.71@gmail.com>"),
            ("bcc_addr", "asolis@griffinmedical.org"),
        ):
            with self.subTest(field=field):
                overrides = {
                    "to_addr": "Appeals Team <appeals@mojavecrest.com>",
                    "cc_addr": None,
                    "bcc_addr": None,
                    "body_text": "Your appeal has been received. Case ID CASE-1.",
                }
                overrides[field] = recipient
                violation = _provider_message(**overrides)
                _mailbox(self.services, [violation])
                self.assertFalse(_verify(NO_ACK_ID, self.workspace, self.services)["pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
