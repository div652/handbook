#!/usr/bin/env python3
"""Focused regressions for the corrected FAMLI referral contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docx import Document


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
CRITERION_ID = "df6c7406-ded9-4aee-834d-6fcbe184d505"


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


BASE_DENIAL = (
    "You are NOT currently eligible for FMLA leave for the following reason: "
    "you worked 1,038 hours, which is less than the required 1,250 hours. "
    "Please see Form WH-381 for the eligibility notice. "
)

CORRECT_FAMLI_REFERRAL = (
    "You may still qualify for leave under Colorado FAMLI. Ridgeline cannot determine "
    "your FAMLI eligibility because the State considers wages from all Colorado employers. "
    "Please file a FAMLI claim directly with CDLE at claims@famli.colorado.gov; CDLE will "
    "determine your eligibility."
)


class FamliReferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(_load_verify())

    def _verify_body(self, body: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            mailbox = {
                "emails": [
                    {
                        "email_id": 36,
                        "to_addr": "elena.vasquez@ridgelinegear.com",
                        "cc_addr": "renata.okafor@ridgelinegear.com",
                        "body_text": body,
                        "has_attachments": False,
                    }
                ]
            }
            Path(tmp, "mailbox.json").write_text(json.dumps(mailbox))
            return self.verify(tmp, tmp)

    def test_accepts_cdle_referral_without_requiring_wh381_attachment(self) -> None:
        result = self._verify_body(BASE_DENIAL + CORRECT_FAMLI_REFERRAL)
        self.assertTrue(result["pass"], result["feedback"])

    def test_rejects_superseded_internal_review_offer(self) -> None:
        body = (
            BASE_DENIAL
            + "You may still qualify for Colorado FAMLI. Please file a FAMLI claim directly "
            "with CDLE at claims@famli.colorado.gov. If you would like, I can review your "
            "FAMLI eligibility for the same leave reason."
        )
        result = self._verify_body(body)
        self.assertFalse(result["pass"])
        self.assertIn("absence of an internal FAMLI eligibility-review offer", result["feedback"])

    def test_rejects_famli_mention_without_cdle_claim_direction(self) -> None:
        result = self._verify_body(
            BASE_DENIAL + "You may still qualify for leave under Colorado FAMLI."
        )
        self.assertFalse(result["pass"])
        self.assertIn("direction to file a FAMLI claim with CDLE", result["feedback"])

    def test_template_matches_detailed_cdle_authority_rule(self) -> None:
        document = Document(
            TASK_DIR / "environment/initial_workspace/Ridgeline SOP.docx"
        )
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn(
            "Ridgeline cannot determine your FAMLI eligibility because the State "
            "considers wages from all Colorado employers.",
            text,
        )
        self.assertIn(
            "Please file a FAMLI claim directly with CDLE at claims@famli.colorado.gov",
            text,
        )
        self.assertNotIn("I can review your FAMLI eligibility", text)


if __name__ == "__main__":
    unittest.main()
