#!/usr/bin/env python3
"""Focused regressions for Carlos Mendez's aggregate daily meal-cap denial."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}
LINE_RUBRIC_ID = "rubric_1776176742950"
SUMMARY_RUBRIC_ID = "rubric_1776176745296"
DAILY_CAP_KEYS = ("OPS-28", "OPS-29", "OPS-30")

LINE_ITEMS = (
    ("OPS-19", "5/5/2026", "Delta", 384.40, 384.40, 0.0, None),
    ("OPS-20", "5/5/2026", "Cosa Nostra Cucina", 46.86, 46.86, 0.0, None),
    ("OPS-21", "5/6/2026", "Bucktown Bites", 28.11, 28.11, 0.0, None),
    ("OPS-22", "5/6/2026", "Sable & Oak Kitchen", 48.23, 48.23, 0.0, None),
    (
        "OPS-23",
        "5/6/2026",
        "Art Institute of Chicago",
        32.00,
        0.0,
        32.00,
        "Missing business justification. Please submit personal reimbursement.",
    ),
    ("OPS-24", "5/7/2026", "Lincoln Square Cafe", 24.25, 24.25, 0.0, None),
    ("OPS-25", "5/7/2026", "Blackstone Chophouse", 46.86, 46.86, 0.0, None),
    ("OPS-26", "5/8/2026", "Loop Street Deli", 21.22, 21.22, 0.0, None),
    ("OPS-27", "5/8/2026", "Cosa Nostra Cucina", 43.55, 43.55, 0.0, None),
    ("OPS-28", "5/9/2026", "Gloriana Bakery", 13.73, 13.73, 0.0, None),
    ("OPS-29", "5/9/2026", "The Riverwalk Grille", 36.93, 36.93, 0.0, None),
    ("OPS-30", "5/9/2026", "Harbor Light Bistro", 43.55, 43.55, 0.0, None),
    (
        "OPS-31",
        "5/5/2026 - 5/9/2026",
        "Hyatt Regency Chicago",
        1916.99,
        1916.99,
        0.0,
        None,
    ),
)


def load_verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"]


def write_workbook(
    workspace: Path,
    meal_denials: dict[str, float] | None = None,
    unrelated_denials: dict[str, float] | None = None,
    summary_approved: float = 2649.19,
    summary_denied: float = 37.49,
) -> None:
    meal_denials = meal_denials or {}
    unrelated_denials = unrelated_denials or {}
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Carlos Mendez"
    sheet.append(
        [
            "Jira Key",
            "Date of Purchase",
            "Merchant",
            "Amount",
            "Expense Category",
            "Approved Amount",
            "Denied Amount",
            "Denial Reason",
        ]
    )

    for key, date, merchant, amount, approved, denied, reason in LINE_ITEMS:
        if key in meal_denials:
            denied = meal_denials[key]
            approved = amount - denied
            reason = "Daily $100 meal limit exceeded." if denied else None
        if key in unrelated_denials:
            denied = unrelated_denials[key]
            approved = amount - denied
            reason = "Daily $100 meal limit exceeded." if denied else None
        sheet.append(
            [key, date, merchant, amount, "Staff Expense", approved, denied, reason]
        )

    sheet.append([])
    sheet.append(["Report Summary"])
    sheet.append(["Jira Key", "OPS-32"])
    sheet.append(["Total Approved", summary_approved])
    sheet.append(["Total Denied", summary_denied])
    sheet.append(["Final Status", "Partially Approved"])
    sheet.append(["Manager Notified", "N"])
    sheet.append(["Comment", "T&E review complete. Expenses approved except where noted."])
    workbook.save(workspace / "expense_reports.xlsx")
    workbook.close()


class CarlosDailyCapVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify_lines = staticmethod(load_verifier(LINE_RUBRIC_ID))
        cls.verify_summary = staticmethod(load_verifier(SUMMARY_RUBRIC_ID))

    def verify_line_disposition(
        self,
        meal_denials: dict[str, float] | None = None,
        unrelated_denials: dict[str, float] | None = None,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_workbook(workspace, meal_denials, unrelated_denials)
            return self.verify_lines(str(workspace))

    def test_all_embedded_verifiers_compile(self) -> None:
        for rubric_id in RUBRICS:
            with self.subTest(rubric_id=rubric_id):
                load_verifier(rubric_id)

    def test_accepts_aggregate_on_any_relevant_meal_line(self) -> None:
        for key in DAILY_CAP_KEYS:
            with self.subTest(key=key):
                result = self.verify_line_disposition({key: 5.49})
                self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_split_aggregate_across_relevant_meal_lines(self) -> None:
        result = self.verify_line_disposition({"OPS-28": 2.00, "OPS-30": 3.49})
        self.assertTrue(result["pass"], result["feedback"])

    def test_rejects_missing_or_wrong_aggregate(self) -> None:
        cases = ({}, {"OPS-29": 4.49})
        for meal_denials in cases:
            with self.subTest(meal_denials=meal_denials):
                result = self.verify_line_disposition(meal_denials)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("combined daily-cap denial expected 5.49", result["feedback"])

    def test_rejects_duplicate_or_excess_aggregate(self) -> None:
        cases = (
            {"OPS-28": 5.49, "OPS-29": 5.49},
            {"OPS-30": 6.49},
        )
        for meal_denials in cases:
            with self.subTest(meal_denials=meal_denials):
                result = self.verify_line_disposition(meal_denials)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("combined daily-cap denial expected 5.49", result["feedback"])

    def test_rejects_daily_cap_denial_on_unrelated_line(self) -> None:
        result = self.verify_line_disposition(unrelated_denials={"OPS-27": 5.49})
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Row OPS-27", result["feedback"])
        self.assertIn("combined daily-cap denial expected 5.49", result["feedback"])

    def test_summary_matches_aggregate_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_workbook(workspace, {"OPS-28": 5.49})
            result = self.verify_summary(str(workspace))
            self.assertTrue(result["pass"], result["feedback"])

    def test_summary_rejects_totals_that_omit_daily_cap_denial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_workbook(
                workspace,
                {"OPS-28": 5.49},
                summary_approved=2654.68,
                summary_denied=32.00,
            )
            result = self.verify_summary(str(workspace))
            self.assertFalse(result["pass"], result["feedback"])
            self.assertIn("expected ~2649.19", result["feedback"])
            self.assertIn("expected 37.49", result["feedback"])


if __name__ == "__main__":
    unittest.main()
