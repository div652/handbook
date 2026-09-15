#!/usr/bin/env python3
"""Focused regression coverage for the Cascade reply verifier."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


CRITERION_ID = "78ef4e7c-fe51-4573-b827-3ce3baea02ea"
TESTS_DIR = Path(__file__).resolve().parent
CASCADE_BODY = """Dear Brian Choi,

We received credit memo CM-38720 dated September 11, 2025 for $2,000.00.
This amount exceeds the original invoice INV-38720 totaling $1,950.00.
We are unable to apply this credit until clarification is received.
Please provide a corrected credit memo or written explanation.

Meridian Partners Accounts Payable"""


def load_verifier():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


def sent_email(to_addr: str, in_reply_to: str, body: str = CASCADE_BODY) -> dict:
    return {
        "folder": "Sent",
        "to_addr": to_addr,
        "in_reply_to": in_reply_to,
        "body_text": body,
    }


def run_verifier(emails: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        services = Path(temp_dir)
        (services / "mailbox.json").write_text(json.dumps({"emails": emails}))
        return load_verifier()("", str(services))


class CascadeReplyVerifierTests(unittest.TestCase):
    def test_content_checks_only_exactly_addressed_and_threaded_candidates(self) -> None:
        wrong_thread = sent_email("ar@cascadeit.com", "<other@cascadeit.com>", "Incomplete")
        valid = sent_email("ar@cascadeit.com", "<cm-38720@cascadeit.com>")
        result = run_verifier([wrong_thread, valid])
        self.assertTrue(result["pass"], result["feedback"])

    def test_recipient_superstring_is_not_a_candidate(self) -> None:
        result = run_verifier([
            sent_email("ar@cascadeit.com.invalid", "<cm-38720@cascadeit.com>"),
        ])
        self.assertFalse(result["pass"], result["feedback"])

    def test_reply_id_superstring_is_not_a_candidate(self) -> None:
        result = run_verifier([
            sent_email("ar@cascadeit.com", "<prefix-cm-38720@cascadeit.com>"),
        ])
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
