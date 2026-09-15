#!/usr/bin/env python3
"""Focused regressions for the BlueCrest follow-up Slack verifier."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "rubric_1775271368334"


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"),
        namespace,
    )
    return namespace["verify"], rubric


def _message(text: str, ts: str, **extra: object) -> dict[str, object]:
    return {
        "type": "message",
        "user": "U_MOCK_BOT",
        "text": text,
        "ts": ts,
        "team": "T001",
        **extra,
    }


INITIAL_APPEAL = _message(
    "[APPEAL FILED L1] Holloway_DOB_03141961 | DOS 12/09/2025 | "
    "BlueCrest Commercial PPO | PI-204",
    "1774265400.000000",
    user="U006",
)


def _verify_with_messages(messages: list[dict[str, object]]):
    verify, _ = _load_verify()
    state = {
        "bot_user_id": "U_MOCK_BOT",
        "channels": {"C006": {"id": "C006", "name": "billing-appeals"}},
        "messages": {"C006": messages},
    }
    with tempfile.TemporaryDirectory() as tmp:
        external = Path(tmp)
        (external / "slack_data.json").write_text(json.dumps(state))
        return verify(str(external), str(external))


class BlueCrestFollowupVerifierRegressionTests(unittest.TestCase):
    def test_accepts_clear_current_shift_update_without_followup_label(self) -> None:
        update = _message(
            "Holloway_DOB_03141961 | DOS 12/09/2025 — payer status checked; "
            "decision remains pending and the next check is 04/15/2026.",
            "1775649600.000001",
        )

        result = _verify_with_messages([INITIAL_APPEAL, update])

        self.assertTrue(result["pass"], result["feedback"])
        self.assertNotIn("FOLLOW-UP", update["text"])

    def test_accepts_current_shift_thread_reply(self) -> None:
        reply = _message(
            "Status checked for Holloway_DOB_03141961, DOS 12-09-2025; "
            "still awaiting the payer's decision.",
            "1775649600.000002",
            thread_ts="1774265400.000000",
            parent_user_id="U006",
        )

        result = _verify_with_messages([INITIAL_APPEAL, reply])

        self.assertTrue(result["pass"], result["feedback"])

    def test_initial_appeal_record_does_not_count_as_followup(self) -> None:
        result = _verify_with_messages([INITIAL_APPEAL])

        self.assertFalse(result["pass"])
        self.assertIn("found 0", result["feedback"])

    def test_current_shift_full_record_cannot_replace_seeded_record(self) -> None:
        replacement = _message(
            "[APPEAL FILED L1] Holloway_DOB_03141961 | DOS 12/09/2025 | "
            "BlueCrest Commercial PPO | PI-204",
            "1775649600.000003",
        )

        result = _verify_with_messages([replacement])

        self.assertFalse(result["pass"])
        self.assertIn("Found 0 matching message(s)", result["feedback"])

    def test_rejects_stale_case_message_outside_current_shift(self) -> None:
        stale = _message(
            "Holloway_DOB_03141961 | 12/09/2025 — payer status checked.",
            "1774351800.000000",
        )

        result = _verify_with_messages([INITIAL_APPEAL, stale])

        self.assertFalse(result["pass"])
        self.assertIn("found 0", result["feedback"])

    def test_rejects_current_shift_message_for_other_dos(self) -> None:
        other_appeal = _message(
            "Holloway_DOB_03141961 | DOS 02/14/2026 — SilverPath appeal filed.",
            "1775649600.000003",
        )

        result = _verify_with_messages([INITIAL_APPEAL, other_appeal])

        self.assertFalse(result["pass"])
        self.assertIn("found 0", result["feedback"])

    def test_rejects_current_shift_message_not_authored_by_agent(self) -> None:
        human_message = _message(
            "Holloway_DOB_03141961 | DOS 12/09/2025 — payer status checked.",
            "1775649600.000004",
            user="U006",
        )

        result = _verify_with_messages([INITIAL_APPEAL, human_message])

        self.assertFalse(result["pass"])
        self.assertIn("found 0", result["feedback"])

    def test_rejects_duplicate_current_shift_updates(self) -> None:
        first = _message(
            "Holloway_DOB_03141961 | DOS 12/09/2025 — status checked.",
            "1775649600.000005",
        )
        second = _message(
            "Holloway DOB 03/14/1961 | DOS 12.09.2025 — still pending.",
            "1775649600.000006",
        )

        result = _verify_with_messages([INITIAL_APPEAL, first, second])

        self.assertFalse(result["pass"])
        self.assertIn("found 2", result["feedback"])


if __name__ == "__main__":
    unittest.main()
