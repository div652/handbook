#!/usr/bin/env python3
"""Focused regressions for row-12 non-applicability values."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "bd125ee1-0a13-4442-922f-4ca62a06c996"


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


class NonApplicabilityVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(_load_verify())

    def _verify_value(self, value: object, *, cell: str = "M12") -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Leave Tracker"
            worksheet[cell] = value
            workbook.save(Path(tmp, "leave_tracker.xlsx"))
            return self.verify(tmp, tmp)

    def test_accepts_exact_and_explanatory_non_applicability_values(self) -> None:
        accepted = (
            "N/A",
            "Not Required",
            "-",
            "N — no notification required (leave not approved)",
            "No - notification not required (case denied)",
            "N/A - case denied",
            "Not required (denied at intake)",
            "Not Required - FMLA Ineligible",
        )
        for value in accepted:
            with self.subTest(value=value):
                result = self._verify_value(value)
                self.assertTrue(result["pass"], result["feedback"])

    def test_rejects_arbitrary_n_or_no_explanations(self) -> None:
        rejected = (
            "N — FAMLI Claim Pending",
            "No — pending FAMLI confirmation",
            "No notification required, but manager was notified",
            "Not required to notify the manager after approval",
            "None recorded yet",
            "Nonsense",
        )
        for value in rejected:
            with self.subTest(value=value):
                result = self._verify_value(value)
                self.assertFalse(result["pass"], value)

    def test_zero_is_allowed_only_for_hours_used(self) -> None:
        self.assertTrue(self._verify_value(0, cell="I12")["pass"])
        result = self._verify_value(0, cell="M12")
        self.assertFalse(result["pass"])
        self.assertIn("M12='0'", result["feedback"])

    def test_nonzero_hours_fail(self) -> None:
        result = self._verify_value(1, cell="I12")
        self.assertFalse(result["pass"])
        self.assertIn("I12='1'", result["feedback"])


if __name__ == "__main__":
    unittest.main()
