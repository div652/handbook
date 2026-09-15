#!/usr/bin/env python3
"""Focused regressions for the server-update SOP catch-all criteria."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
SEED_MAIL = (
    TASK_DIR
    / "environment"
    / "initial_external_services"
    / "google_mail"
    / "inbox.json"
)
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

FORWARD_ID = "a4be86d2-af0c-4e30-881b-e6f259724fa8"
DM_ID = "22121fad-e961-4671-886b-692a4cdc1688"
REMOVED_COUNT_ID = "8bbdb09a-77eb-44dc-bcb6-34e0b6f0c2d2"
BOT_USER_ID = "U_MOCK_BOT"
REQUIRED_DM = "OUT OF SCOPE: Upcoming Server Update -- please advise"


def verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


def seeded_source() -> dict:
    mailbox = json.loads(SEED_MAIL.read_text())
    return copy.deepcopy(
        next(email for email in mailbox["emails"] if str(email["email_id"]) == "3")
    )


def forwarded_email(source: dict, **overrides: object) -> dict:
    body = (
        "\n\n---------- Forwarded message ---------\n"
        f"From: {source['from_addr']}\n"
        "Date: 2026-04-01 08:30:00-05:00\n"
        f"Subject: {source['subject']}\n"
        f"To: {source['to_addr']}\n\n"
        f"{source['body_text']}"
    )
    email = {
        "email_id": "5",
        "folder": "Sent",
        "subject": "Fwd: Upcoming Server Update",
        "from_addr": "ioa@prairiestar.com",
        "to_addr": "carlos.mendoza@prairiestar.com",
        "cc_addr": None,
        "bcc_addr": None,
        "message_id": "<sent005@prairiestar.com>",
        "in_reply_to": None,
        "body_text": body,
        "attachments": [],
    }
    email.update(overrides)
    return email


def slack_state(*messages: dict, include_target_channel: bool = True) -> dict:
    channels = {
        "D999": {
            "id": "D999",
            "name": "dm-other",
            "is_im": True,
            "user": "U999",
        }
    }
    if include_target_channel:
        channels["D007"] = {
            "id": "D007",
            "name": "dm-c.mendoza",
            "is_im": True,
            "user": "U007",
        }
    return {
        "bot_user_id": BOT_USER_ID,
        "users": {
            "U007": {
                "id": "U007",
                "name": "c.mendoza",
                "profile": {"email": "carlos.mendoza@prairiestar.com"},
            },
            BOT_USER_ID: {"id": BOT_USER_ID, "is_bot": True},
        },
        "channels": channels,
        "messages": {"D007": list(messages), "D999": []},
    }


class CatchAllVerifierRegressions(unittest.TestCase):
    def evaluate_mail(self, emails: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary)
            (external / "mailbox.json").write_text(json.dumps({"emails": emails}))
            return verifier(FORWARD_ID)(temporary, temporary)

    def evaluate_slack(self, state: dict) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary)
            (external / "slack_data.json").write_text(json.dumps(state))
            return verifier(DM_ID)(temporary, temporary)

    def test_all_inline_verifiers_compile(self) -> None:
        for rubric_id in RUBRICS:
            with self.subTest(rubric_id=rubric_id):
                verifier(rubric_id)

    def test_valid_source_bound_forward_and_agent_dm_pass(self) -> None:
        source = seeded_source()
        self.assertTrue(
            self.evaluate_mail([source, forwarded_email(source)])["pass"]
        )
        self.assertTrue(
            self.evaluate_slack(
                slack_state({"user": BOT_USER_ID, "text": REQUIRED_DM})
            )["pass"]
        )

    def test_missing_or_mutated_source_fails_forward(self) -> None:
        source = seeded_source()
        self.assertFalse(self.evaluate_mail([forwarded_email(source)])["pass"])
        mutated = copy.deepcopy(source)
        mutated["body_text"] += "\nTampered"
        self.assertFalse(
            self.evaluate_mail([mutated, forwarded_email(mutated)])["pass"]
        )

    def test_wrong_recipient_or_malformed_forward_fails(self) -> None:
        source = seeded_source()
        cases = (
            {"to_addr": "daniel.reyes@prairiestar.com"},
            {"from_addr": "hannah.brooks@prairiestar.com"},
            {"subject": "Re: Upcoming Server Update"},
            {"body_text": source["body_text"]},
            {"in_reply_to": source["message_id"]},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.evaluate_mail(
                    [source, forwarded_email(source, **overrides)]
                )
                self.assertFalse(result["pass"], result["feedback"])

    def test_wrong_message_channel_or_author_fails_dm(self) -> None:
        states = (
            slack_state(
                {"user": BOT_USER_ID, "text": "OUT OF SCOPE: Server Update -- please advise"}
            ),
            slack_state({"user": "U007", "text": REQUIRED_DM}),
            slack_state(),
            slack_state(include_target_channel=False),
        )
        states[2]["messages"]["D999"] = [
            {"user": BOT_USER_ID, "text": REQUIRED_DM}
        ]
        for state in states:
            with self.subTest(state=state):
                result = self.evaluate_slack(state)
                self.assertFalse(result["pass"], result["feedback"])

    def test_harmless_unrelated_communications_do_not_affect_results(self) -> None:
        source = seeded_source()
        unrelated_email = {
            "email_id": "6",
            "folder": "Sent",
            "from_addr": "ioa@prairiestar.com",
            "to_addr": "daniel.reyes@prairiestar.com",
            "subject": "Unrelated follow-up",
            "body_text": "For awareness.",
        }
        mail_result = self.evaluate_mail(
            [source, forwarded_email(source), unrelated_email]
        )
        self.assertTrue(mail_result["pass"], mail_result["feedback"])

        state = slack_state(
            {"user": BOT_USER_ID, "text": REQUIRED_DM},
            {"user": BOT_USER_ID, "text": "Unrelated operational update."},
        )
        state["messages"]["D999"].append(
            {"user": BOT_USER_ID, "text": "Another harmless message."}
        )
        slack_result = self.evaluate_slack(state)
        self.assertTrue(slack_result["pass"], slack_result["feedback"])

    def test_global_communication_count_criteria_are_gone(self) -> None:
        self.assertNotIn(REMOVED_COUNT_ID, RUBRICS)
        texts = [rubric["rubric_text"].lower() for rubric in RUBRICS.values()]
        self.assertFalse(any("total of exactly" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
