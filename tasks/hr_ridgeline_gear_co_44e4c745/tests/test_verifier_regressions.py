#!/usr/bin/env python3
"""Focused regressions for QI1-QI3 from the task RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
SEED_PATH = TASK_DIR / "environment/initial_external_services/google_mail/inbox.json"
RUBRICS = {item["id"]: item for item in json.loads((TESTS_DIR / "rubrics.json").read_text())}
SEEDS = {str(item["email_id"]): item for item in json.loads(SEED_PATH.read_text())["emails"]}

FORWARD_CASES = {
    "2855c994-4284-4c55-b923-dbf46cb4729d": ("2", "teresa.vang@ridgelinegear.com"),
    "71fad417-c32d-4d55-b1bb-ba3d5422063d": ("3", "renata.okafor@ridgelinegear.com"),
    "93de8979-b995-40cc-bfff-b9a168efa522": ("5", "teresa.vang@ridgelinegear.com"),
    "591efc04-a9d4-49e2-8f8b-e3c5613f6f52": ("7", "teresa.vang@ridgelinegear.com"),
}

FAIL_CLOSED_IDS = (
    "rubric_1775874678449",
    "rubric_1775874704935",
    "rubric_1775874897463",
    "rubric_1776373502547",
)


def load_verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"], namespace


def write_mailbox(directory: Path, emails: list[dict[str, object]]) -> None:
    (directory / "mailbox.json").write_text(json.dumps({"emails": emails}), encoding="utf-8")


def mechanical_forward(source: dict[str, object], recipient: str) -> dict[str, object]:
    body = (
        "\n\n---------- Forwarded message ---------\n"
        f"From: {source['from_addr']}\n"
        "Date: 2026-04-17 09:00:00\n"
        f"Subject: {source['subject']}\n"
        f"To: {source['to_addr']}\n\n"
        f"{source['body_text']}"
    )
    return {
        "email_id": "100",
        "folder": "Sent",
        "to_addr": recipient,
        "subject": f"Fwd: {source['subject']}",
        "body_text": body,
    }


class VerifierRegressionTests(unittest.TestCase):
    def test_all_inline_verifiers_compile(self) -> None:
        for rubric_id in RUBRICS:
            with self.subTest(rubric_id=rubric_id):
                load_verifier(rubric_id)

    def test_forwards_are_bound_to_seed_source_and_required_recipient(self) -> None:
        for rubric_id, (source_id, recipient) in FORWARD_CASES.items():
            verify, _ = load_verifier(rubric_id)
            source = SEEDS[source_id]
            with self.subTest(rubric_id=rubric_id), tempfile.TemporaryDirectory() as tmp:
                services = Path(tmp)
                write_mailbox(services, [source, mechanical_forward(source, recipient)])
                result = verify(tmp, tmp)
                self.assertTrue(result["pass"], result["feedback"])

    def test_authored_summaries_and_unrelated_forwards_do_not_count(self) -> None:
        for rubric_id, (source_id, recipient) in FORWARD_CASES.items():
            verify, _ = load_verifier(rubric_id)
            source = SEEDS[source_id]
            other_source = SEEDS["7" if source_id != "7" else "2"]
            authored_summary = {
                "email_id": "100",
                "folder": "Sent",
                "to_addr": recipient,
                "subject": f"Payroll handoff for {source['from_addr']}",
                "body_text": f"Summary of request from {source['from_addr']}: {source['subject']}",
            }
            unrelated_forward = mechanical_forward(other_source, recipient)

            with self.subTest(rubric_id=rubric_id, candidate="authored summary"), tempfile.TemporaryDirectory() as tmp:
                services = Path(tmp)
                write_mailbox(services, [source, authored_summary])
                result = verify(tmp, tmp)
                self.assertFalse(result["pass"], result["feedback"])

            with self.subTest(rubric_id=rubric_id, candidate="unrelated forward"), tempfile.TemporaryDirectory() as tmp:
                services = Path(tmp)
                write_mailbox(services, [source, unrelated_forward])
                result = verify(tmp, tmp)
                self.assertFalse(result["pass"], result["feedback"])

    def test_exact_source_forward_to_wrong_recipient_does_not_count(self) -> None:
        for rubric_id, (source_id, _recipient) in FORWARD_CASES.items():
            verify, _ = load_verifier(rubric_id)
            source = SEEDS[source_id]
            with self.subTest(rubric_id=rubric_id), tempfile.TemporaryDirectory() as tmp:
                services = Path(tmp)
                write_mailbox(services, [source, mechanical_forward(source, "someone.else@ridgelinegear.com")])
                result = verify(tmp, tmp)
                self.assertFalse(result["pass"], result["feedback"])

    def test_negative_mailbox_verifiers_fail_closed(self) -> None:
        for rubric_id in FAIL_CLOSED_IDS:
            verify, _ = load_verifier(rubric_id)
            with self.subTest(rubric_id=rubric_id), tempfile.TemporaryDirectory() as tmp:
                services = Path(tmp)
                self.assertFalse(verify(tmp, None)["pass"])
                self.assertFalse(verify(tmp, tmp)["pass"])
                (services / "mailbox.json").write_text("{not valid json", encoding="utf-8")
                self.assertFalse(verify(tmp, tmp)["pass"])

    def test_template_16_requires_every_normalized_mandatory_block(self) -> None:
        rubric_id = "103266c1-74f4-479e-9171-b27adf53f33d"
        verify, _ = load_verifier(rubric_id)
        full_body = (
            "Hi Jimmy,\n\n"
            "Thank you for your question about payroll calculations. Questions about pay, benefits, deductions, "
            "premium billing, and tax matters during leave (outside the remit of simple balance check requests) "
            "are handled by our Payroll Lead, Teresa Vang.\n\n"
            "I have forwarded your question to Teresa, and she will respond to you directly within 1-2 business days. "
            "You can also reach her at teresa.vang@ridgelinegear.com.\n\n"
            "In the meantime, your leave case is moving forward as planned. Please let me know if you have any questions "
            "about the leave process itself, as opposed to pay or benefits.\n\n"
            "Best regards,\nRidgeline Gear Co. - Leave Coordinator\nleaves@ridgelinegear.com"
        )
        message = {
            "email_id": "100",
            "folder": "Sent",
            "to_addr": "jimmy.rustler@ridgelinegear.com",
            "subject": "Re: Dollars",
            "body_text": full_body,
        }

        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            write_mailbox(services, [message])
            result = verify(tmp, tmp)
            self.assertTrue(result["pass"], result["feedback"])

            incomplete = dict(message)
            incomplete["body_text"] = full_body.replace(
                "In the meantime, your leave case is moving forward as planned. ", "In the meantime, "
            )
            write_mailbox(services, [incomplete])
            result = verify(tmp, tmp)
            self.assertFalse(result["pass"], result["feedback"])
            self.assertEqual(0.0, result["score"])
            self.assertIn("leave case is moving forward", result["feedback"])


if __name__ == "__main__":
    unittest.main()
