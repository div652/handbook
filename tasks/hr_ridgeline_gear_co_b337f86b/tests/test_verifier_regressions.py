#!/usr/bin/env python3
"""Focused regressions for the confirmed QI1-QI3 evaluator defects."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

OUTGOING_ID = "rubric_1776288832903"
INTAKE_ID = "0d6543f1-5d24-49a5-a9b3-670d80174c93"
TEMPLATE_ID = "c5a28a21-868e-4357-9368-30926c48af6e"


def verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"], namespace


def evaluate_json(rubric_id: str, filename: str, state: object) -> dict:
    verify, _ = verifier(rubric_id)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / filename).write_text(json.dumps(state), encoding="utf-8")
        return verify(str(root), str(root))


def permitted_emails() -> list[dict[str, object]]:
    return [
        {
            "email_id": "27",
            "from_addr": "leaves@ridgelinegear.com",
            "to_addr": "claire.ndubisi@ridgelinegear.com",
            "folder": "FMLA Cases",
            "subject": "FMLA Eligibility Notice",
        },
        {
            "email_id": "28",
            "from_addr": "leaves@ridgelinegear.com",
            "to_addr": "greg.ostrowski@ridgelinegear.com",
            "folder": "FMLA Cases",
            "subject": "Manager Leave Notification",
        },
    ]


def slack_state(text: str) -> dict[str, object]:
    return {
        "channels": {"C001": {"name": "leave-intake"}},
        "messages": {"C001": [{"ts": "1775692800", "text": text}]},
    }


class VerifierRegressionTests(unittest.TestCase):
    def test_all_inline_verifiers_compile(self) -> None:
        for rubric_id in RUBRICS:
            with self.subTest(rubric_id=rubric_id):
                verifier(rubric_id)

    def test_qi1_requires_exactly_two_permitted_emails_in_fmla_cases(self) -> None:
        emails = permitted_emails()
        result = evaluate_json(OUTGOING_ID, "mailbox.json", {"emails": emails})
        self.assertTrue(result["pass"], result["feedback"])

        wrong_folder = json.loads(json.dumps(emails))
        wrong_folder[0]["folder"] = "Sent"
        result = evaluate_json(OUTGOING_ID, "mailbox.json", {"emails": wrong_folder})
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("expected 'FMLA Cases'", result["feedback"])

        extra = json.loads(json.dumps(emails))
        extra.append(
            {
                "email_id": "29",
                "from_addr": "leaves@ridgelinegear.com",
                "to_addr": "renata.okafor@ridgelinegear.com",
                "folder": "FMLA Cases",
            }
        )
        result = evaluate_json(OUTGOING_ID, "mailbox.json", {"emails": extra})
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("expected exactly 2", result["feedback"])
        self.assertIn("unpermitted", result["feedback"])

    def test_qi2_uses_anchored_six_field_intake_matching(self) -> None:
        exact = (
            "<@U004> FMLA INTAKE: LC-2026-0050, Claire Ndubisi, Eligible, "
            "family member's serious health condition, 04/14/2026, P2. <@U005>"
        )
        result = evaluate_json(INTAKE_ID, "slack_data.json", slack_state(exact))
        self.assertTrue(result["pass"], result["feedback"])

        whitespace_variant = exact.replace(" FMLA", "\n\nFMLA").replace(", ", ",\n  ")
        result = evaluate_json(
            INTAKE_ID, "slack_data.json", slack_state(whitespace_variant)
        )
        self.assertTrue(result["pass"], result["feedback"])

        invalid_messages = {
            "appended narrative": exact + " Certification is due 04/24/2026.",
            "seventh field": exact.replace(", P2.", ", P2, Manager notified."),
            "noncanonical tag": exact.replace("<@U005>", "<@U006>"),
            "abbreviated employee": exact.replace("Claire Ndubisi", "Claire N."),
        }
        for label, text in invalid_messages.items():
            with self.subTest(label=label):
                result = evaluate_json(
                    INTAKE_ID, "slack_data.json", slack_state(text)
                )
                self.assertFalse(result["pass"], result["feedback"])
                self.assertEqual(result["score"], 0.0)

    def test_qi3_requires_whitespace_normalized_template_2_equality(self) -> None:
        verify, namespace = verifier(TEMPLATE_ID)
        expected = namespace["EXPECTED_TEMPLATE_2"]

        def evaluate(body: str) -> dict:
            state = {
                "emails": [
                    {
                        "email_id": "27",
                        "to_addr": "claire.ndubisi@ridgelinegear.com",
                        "body_text": body,
                    }
                ]
            }
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "mailbox.json").write_text(json.dumps(state), encoding="utf-8")
                return verify(str(root), str(root))

        whitespace_variant = re.sub(r" ", "   ", expected.replace("\n", "\n\n"))
        result = evaluate(whitespace_variant)
        self.assertTrue(result["pass"], result["feedback"])

        mutations = {
            "signature hyphen": expected.replace(
                "Ridgeline Gear Co. — Leave Coordinator",
                "Ridgeline Gear Co. - Leave Coordinator",
            ),
            "extra content": expected + "\nColorado FAMLI may also apply.",
            "punctuation change": expected.replace("Case ID:", "Case ID -"),
        }
        for label, body in mutations.items():
            with self.subTest(label=label):
                result = evaluate(body)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertEqual(result["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
