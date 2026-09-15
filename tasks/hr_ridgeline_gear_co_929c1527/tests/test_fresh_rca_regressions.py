#!/usr/bin/env python3
"""Regressions for fresh evaluator defects found after the corrected rerun."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
ROW_12 = "d38460f9-0c67-4cb4-93c2-b2ef1fc5618d"
NKOMO_ESCALATION = "fb332624-ccd4-4003-9dd8-d531799f342e"
RUBRICS = {
    item["id"]: item
    for item in json.loads((TESTS_DIR / "rubrics.json").read_text(encoding="utf-8"))
}


def verifier(criterion_id: str):
    namespace = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[criterion_id]["verifier_code"], f"<{criterion_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


class ExactLeaveTypeAndStatusTests(unittest.TestCase):
    def evaluate(self, leave_type: str, status: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            values = {
                "A12": "LC-2026-0321",
                "B12": "R-2317",
                "C12": "Elena Vasquez",
                "D12": leave_type,
                "E12": date(2026, 4, 20),
                "F12": date(2026, 5, 15),
                "H12": "Continuous",
                "N12": "P2",
                "O12": status,
            }
            for coordinate, value in values.items():
                sheet[coordinate] = value
            workbook.save(Path(tmp) / "leave_tracker.xlsx")
            return verifier(ROW_12)(tmp)

    def test_exact_values_pass(self) -> None:
        result = self.evaluate("FMLA", "Denied")
        self.assertTrue(result["pass"], result["feedback"])

    def test_explanatory_or_conflicting_values_fail(self) -> None:
        for leave_type, status in (
            ("FMLA and FAMLI", "Denied"),
            ("FMLA", "Denied pending review"),
            ("FMLA", "Not Denied"),
        ):
            with self.subTest(leave_type=leave_type, status=status):
                result = self.evaluate(leave_type, status)
                self.assertFalse(result["pass"], result["feedback"])


class NkomoCorrectionContextTests(unittest.TestCase):
    def evaluate(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            (services / "slack_data.json").write_text(
                json.dumps(
                    {
                        "channels": {"C-HR": {"name": "hr-escalations"}},
                        "messages": {"C-HR": [{"text": text}]},
                    }
                ),
                encoding="utf-8",
            )
            return verifier(NKOMO_ESCALATION)(tmp, tmp)

    def test_correction_of_prior_within_parameters_note_passes(self) -> None:
        result = self.evaluate(
            "Correction for James Nkomo / LC-2026-0203: the prior review said "
            "usage was within parameters. That was incorrect; the recurring issue "
            "exceeds certified frequency and is a pattern concern."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_uncorrected_within_parameters_conclusion_fails(self) -> None:
        result = self.evaluate(
            "James Nkomo / LC-2026-0203 frequency concern reviewed; usage is within "
            "certified parameters and no escalation is needed."
        )
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
