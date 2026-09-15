#!/usr/bin/env python3
"""Focused regressions for the Sunshine Deal 4821 evaluator fixes."""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS_PATH = TESTS_DIR / "rubrics.json"
DEAL_LOG_CRITERION_IDS = (
    "5dc90497-0f2e-473c-937a-650876b57667",
    "2c9d99a3-cfba-4b27-a712-6b0a4434ee43",
)
DEAL_LOG_STATUS_ID = "2c9d99a3-cfba-4b27-a712-6b0a4434ee43"
FUNDING_COMMUNICATION_ID = "bd9dbfee-768f-4661-bc7e-392df47b15da"
TITLE_COMMUNICATION_ID = "7228f798-9013-4051-aa4f-448b7aaac722"
EXPECTED_CRITERION_IDS = {
    "5dc90497-0f2e-473c-937a-650876b57667",
    "2c9d99a3-cfba-4b27-a712-6b0a4434ee43",
    "37d3cc0f-21c2-49f0-97dd-5d7bf2acb61d",
    "bd9dbfee-768f-4661-bc7e-392df47b15da",
    "7228f798-9013-4051-aa4f-448b7aaac722",
    "R5",
}


def _load_rubrics() -> list[dict]:
    return json.loads(RUBRICS_PATH.read_text())


def _deal_log_selectors():
    rubrics_by_id = {rubric["id"]: rubric for rubric in _load_rubrics()}
    for criterion_id in DEAL_LOG_CRITERION_IDS:
        namespace: dict = {"__builtins__": __builtins__}
        code = rubrics_by_id[criterion_id]["verifier_code"]
        exec(compile(code, f"<{criterion_id}>", "exec"), namespace)
        yield criterion_id, namespace["_select_deal_log"]


def _communication_verifier(criterion_id: str):
    rubric = next(rubric for rubric in _load_rubrics() if rubric["id"] == criterion_id)
    namespace: dict = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{criterion_id}>", "exec"), namespace)
    return namespace["verify"]


def _deal_log_status_verifier():
    rubric = next(rubric for rubric in _load_rubrics() if rubric["id"] == DEAL_LOG_STATUS_ID)
    namespace: dict = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{DEAL_LOG_STATUS_ID}>", "exec"), namespace)
    return namespace["verify"]


def _base_slack() -> dict:
    def user(user_id: str, handle: str, real_name: str, email: str) -> tuple[str, dict]:
        return user_id, {
            "id": user_id,
            "name": handle,
            "real_name": real_name,
            "profile": {"display_name": handle, "real_name": real_name, "email": email},
        }

    return {
        "users": dict(
            [
                user("U003", "jasmine.patel", "Jasmine Patel", "jasmine.patel@sunshineandsetauto.com"),
                user("U004", "noah.alvarez", "Noah Alvarez", "noah.alvarez@sunshineandsetauto.com"),
                user("U005", "priya.bennett", "Priya Bennett", "priya.bennett@sunshineandsetauto.com"),
                user("U099", "wrong.person", "Wrong Person", "wrong.person@sunshineandsetauto.com"),
            ]
        ),
        "channels": {
            "C002": {"id": "C002", "name": "acct-contracts-funding", "is_channel": True},
            "C004": {"id": "C004", "name": "acct-titles-billing", "is_channel": True},
            "C099": {"id": "C099", "name": "random-chat", "is_channel": True},
        },
        "messages": {},
    }


def _slack_message(text: str, ts: str, channel: str, **extra) -> dict:
    return {"type": "message", "user": "U003", "text": text, "ts": ts, "channel": channel, **extra}


def _sent_email(to_addr: str, subject: str, body: str, email_id: str, **extra) -> dict:
    return {
        "email_id": email_id,
        "folder": "SENT",
        "from_addr": "jasmine.patel@sunshineandsetauto.com",
        "to_addr": to_addr,
        "cc_addr": None,
        "bcc_addr": None,
        "date": "2026-04-14T13:00:00-04:00",
        "message_id": f"<{email_id}@sunshineandsetauto.com>",
        "in_reply_to": None,
        "subject": subject,
        "body_text": body,
        **extra,
    }


def _run_communication_verifier(
    criterion_id: str, *, slack: dict | None = None, emails: list[dict] | None = None
) -> dict:
    verifier = _communication_verifier(criterion_id)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        external = root / "external"
        workspace.mkdir()
        external.mkdir()
        if slack is not None:
            (external / "slack_data.json").write_text(json.dumps(slack))
        if emails is not None:
            (external / "mailbox.json").write_text(json.dumps({"emails": emails}))
        return verifier(str(workspace), str(external))


class ArtifactSelectionRegressionTests(unittest.TestCase):
    def test_pre_4821_backup_does_not_shadow_canonical_workbook(self):
        for criterion_id, select_deal_log in _deal_log_selectors():
            with self.subTest(criterion_id=criterion_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                canonical = root / "DealLog_April2026.xlsx"
                canonical.touch()
                (root / "DealLog_April2026_pre_4821.xlsx").touch()

                selected, error = select_deal_log(root)

                self.assertIsNone(error)
                self.assertEqual(selected, canonical)

    def test_competing_final_revisions_fail_as_ambiguous(self):
        for criterion_id, select_deal_log in _deal_log_selectors():
            with self.subTest(criterion_id=criterion_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "DealLog_April2026.xlsx").touch()
                (root / "DealLog_April2026_final.xlsx").touch()
                (root / "DealLog_April2026_approved.xlsx").touch()

                selected, error = select_deal_log(root)

                self.assertIsNone(selected)
                self.assertIn("Ambiguous deal-log revisions", error)

    def test_full_status_verifier_accepts_non_null_post_date(self):
        verify = _deal_log_status_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            workbook_path = Path(tmp) / "DealLog_April2026.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(
                ["Deal #", "Post Date", "Posted By", "Funding Status", "Title Status"]
            )
            sheet.append(
                [
                    4821,
                    datetime.date(2026, 4, 14),
                    "Jasmine Patel",
                    "Contract in Transit",
                    "In Process",
                ]
            )
            workbook.save(workbook_path)

            result = verify(tmp)

            self.assertTrue(result["pass"], result["feedback"])
            self.assertEqual(result["score"], 1.0)


class RubricRemovalRegressionTests(unittest.TestCase):
    def test_only_redundant_r2_is_removed(self):
        rubrics = _load_rubrics()
        ids = {rubric["id"] for rubric in rubrics}

        self.assertEqual(ids, EXPECTED_CRITERION_IDS)
        self.assertNotIn("R2_handoff_new", ids)

        comprehensive = next(
            rubric
            for rubric in rubrics
            if rubric["id"] == "37d3cc0f-21c2-49f0-97dd-5d7bf2acb61d"
        )
        self.assertIn("Exp. Funding Date", comprehensive["rubric_text"])
        self.assertIn("Exp. Funding Date expected April 16 2026", comprehensive["verifier_code"])


class CommunicationIdentityRegressionTests(unittest.TestCase):
    def test_structured_email_recipient_establishes_identity_without_body_name(self):
        scenarios = (
            (
                FUNDING_COMMUNICATION_ID,
                _sent_email(
                    "noah.alvarez@sunshineandsetauto.com",
                    "Funding package — Deal 4821",
                    "The complete package is ready for CIT follow-up.",
                    "funding-recipient-only",
                ),
            ),
            (
                TITLE_COMMUNICATION_ID,
                _sent_email(
                    "priya.bennett@sunshineandsetauto.com",
                    "Deal 4821 title packet kickoff",
                    "Please begin title processing in parallel.",
                    "title-recipient-only",
                ),
            ),
        )
        for criterion_id, email in scenarios:
            with self.subTest(criterion_id=criterion_id):
                result = _run_communication_verifier(criterion_id, emails=[email])
                self.assertTrue(result["pass"], result["feedback"])

    def test_slack_dm_membership_establishes_identity_without_body_name(self):
        scenarios = (
            (FUNDING_COMMUNICATION_ID, "U004", "Deal 4821 funding package is ready for CIT follow-up."),
            (TITLE_COMMUNICATION_ID, "U005", "Deal 4821 title packet is ready to start."),
        )
        for criterion_id, target_user, text in scenarios:
            with self.subTest(criterion_id=criterion_id):
                slack = _base_slack()
                slack["channels"]["D001"] = {
                    "id": "D001",
                    "name": "direct-message",
                    "is_im": True,
                    "members": ["U003", target_user],
                    "user": target_user,
                }
                slack["messages"]["D001"] = [
                    _slack_message(text, "1776183000.000001", "D001")
                ]
                result = _run_communication_verifier(criterion_id, slack=slack)
                self.assertTrue(result["pass"], result["feedback"])

    def test_parent_thread_author_establishes_identity_for_relevant_reply(self):
        scenarios = (
            (FUNDING_COMMUNICATION_ID, "C002", "U004", "Deal 4821 funding package is ready."),
            (TITLE_COMMUNICATION_ID, "C004", "U005", "Deal 4821 title work is starting."),
        )
        for criterion_id, channel, target_user, reply_text in scenarios:
            with self.subTest(criterion_id=criterion_id):
                slack = _base_slack()
                parent_ts = "1776182000.000001"
                parent = {
                    "type": "message",
                    "user": target_user,
                    "text": "What is the status?",
                    "ts": parent_ts,
                    "channel": channel,
                }
                reply = _slack_message(
                    reply_text,
                    "1776183000.000002",
                    channel,
                    thread_ts=parent_ts,
                    parent_user_id=target_user,
                )
                slack["messages"][channel] = [parent, reply]
                result = _run_communication_verifier(criterion_id, slack=slack)
                self.assertTrue(result["pass"], result["feedback"])

    def test_topic_and_identity_in_separate_communications_do_not_join(self):
        slack = _base_slack()
        slack["messages"]["C004"] = [
            _slack_message("Deal 4821 title packet is ready.", "1776183000.000001", "C004"),
            _slack_message("Priya, thanks for your help.", "1776183001.000002", "C004"),
        ]
        title_result = _run_communication_verifier(TITLE_COMMUNICATION_ID, slack=slack)
        self.assertFalse(title_result["pass"], title_result["feedback"])

        emails = [
            _sent_email(
                "priya.bennett@sunshineandsetauto.com",
                "Quick question",
                "Thanks for your help.",
                "identity-only",
            ),
            _sent_email(
                "wrong.person@sunshineandsetauto.com",
                "Deal 4821 title packet",
                "Please begin title work.",
                "topic-only",
            ),
        ]
        email_result = _run_communication_verifier(TITLE_COMMUNICATION_ID, emails=emails)
        self.assertFalse(email_result["pass"], email_result["feedback"])

    def test_wrong_email_recipient_and_wrong_public_channel_fail(self):
        email = _sent_email(
            "wrong.person@sunshineandsetauto.com",
            "Deal 4821 funding package",
            "Noah, the CIT package is ready for you.",
            "wrong-recipient",
        )
        email_result = _run_communication_verifier(FUNDING_COMMUNICATION_ID, emails=[email])
        self.assertFalse(email_result["pass"], email_result["feedback"])

        slack = _base_slack()
        slack["messages"]["C099"] = [
            _slack_message(
                "Deal 4821 funding package is ready for <@U004>.",
                "1776183000.000001",
                "C099",
            )
        ]
        slack_result = _run_communication_verifier(FUNDING_COMMUNICATION_ID, slack=slack)
        self.assertFalse(slack_result["pass"], slack_result["feedback"])

    def test_unrelated_messages_to_the_correct_people_fail(self):
        scenarios = (
            (FUNDING_COMMUNICATION_ID, "U004", "Deal 4821 title work is now in process."),
            (TITLE_COMMUNICATION_ID, "U005", "Deal 4821 gross is $5,640 and has been posted."),
        )
        for criterion_id, target_user, text in scenarios:
            with self.subTest(criterion_id=criterion_id):
                slack = _base_slack()
                slack["channels"]["D001"] = {
                    "id": "D001",
                    "name": "direct-message",
                    "is_im": True,
                    "members": ["U003", target_user],
                    "user": target_user,
                }
                slack["messages"]["D001"] = [
                    _slack_message(text, "1776183000.000001", "D001")
                ]
                result = _run_communication_verifier(criterion_id, slack=slack)
                self.assertFalse(result["pass"], result["feedback"])

    def test_existing_correct_public_channel_routes_remain_valid(self):
        slack = _base_slack()
        slack["bot_user_id"] = "U_BOT"
        slack["users"]["U_BOT"] = {
            "id": "U_BOT",
            "name": "slackbot",
            "real_name": "Mock Bot",
            "profile": {"display_name": "slackbot"},
            "is_bot": True,
        }
        slack["messages"]["C002"] = [
            _slack_message(
                "Deal 4821 is ready for <@U004>.",
                "1776183000.000001",
                "C002",
                user="U_BOT",
            )
        ]
        funding_result = _run_communication_verifier(FUNDING_COMMUNICATION_ID, slack=slack)
        self.assertTrue(funding_result["pass"], funding_result["feedback"])

        slack = _base_slack()
        slack["messages"]["C004"] = [
            _slack_message(
                "Deal 4821 title work is ready for <@U005>.",
                "1776183000.000001",
                "C004",
            )
        ]
        title_result = _run_communication_verifier(TITLE_COMMUNICATION_ID, slack=slack)
        self.assertTrue(title_result["pass"], title_result["feedback"])


if __name__ == "__main__":
    unittest.main()
