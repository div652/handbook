#!/usr/bin/env python3
"""Focused regressions for comprehensive-QC findings QI1 and QI2."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
WORKSPACE = TASK_DIR / "environment" / "initial_workspace"
RUBRICS = json.loads((TESTS_DIR / "rubrics.json").read_text())

CLAIM_CRITERION = "rubric_1775705546419"
RA_CASES = {
    "rubric_1775705946912": ("CLM-2026-0892", "PAT-1042"),
    "rubric_1775705963295": ("CLM-2026-1105", "PAT-1058"),
}

CLAIM_ROW = [
    "CLM-2026-1106",
    "PAT-1042",
    "Michael Torres",
    "03/15/2026",
    "Dr. Sarah Chen",
    "1234567890",
    "1122334455",
    "BlueCross TX",
    "BCTX1",
    "99214",
    "E11.65",
    None,
    7,
    "CLM-2026-0892",
    "Submitted",
    285,
    0,
    0,
    0,
    None,
    None,
    None,
    None,
]


def load_verify(criterion_id: str):
    rubric = next(item for item in RUBRICS if item["id"] == criterion_id)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{criterion_id}>", "exec"), namespace)
    return namespace["verify"]


def copy_workbook(workspace: Path, filename: str) -> Path:
    target = workspace / filename
    shutil.copy2(WORKSPACE / filename, target)
    return target


def write_row(path: Path, sheet_name: str, row_number: int, values: list[object]) -> None:
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[sheet_name]
    for column, value in enumerate(values, start=1):
        sheet.cell(row=row_number, column=column).value = value
    workbook.save(path)


def ra_row(claim_id: str, patient_id: str, status: str, resolution_date: object) -> list[object]:
    return [
        "RA-2026-0031",
        "04/24/2026",
        claim_id,
        patient_id,
        "ERA Processing",
        "Anything",
        "Maria Santos",
        status,
        resolution_date,
    ]


class ClaimReplacementRegressions(unittest.TestCase):
    def verify_row(self, row: list[object]):
        verify = load_verify(CLAIM_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, row)
            return verify(workspace)

    def test_exact_23_of_23_row_passes(self):
        verify = load_verify(CLAIM_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, CLAIM_ROW)
            self.assertTrue(verify(workspace)["pass"])

    def test_plain_numeric_frequency_and_currency_strings_pass(self):
        verify = load_verify(CLAIM_CRITERION)
        row = list(CLAIM_ROW)
        row[12] = "7.0"
        row[15:19] = ["$285.00", "$0.00", "$0.00", "$0.00"]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, row)
            self.assertTrue(verify(workspace)["pass"])

    def test_standard_plain_numeric_representations_pass(self):
        for frequency in (7, 7.0, "7", "7.0"):
            with self.subTest(frequency=frequency):
                row = list(CLAIM_ROW)
                row[12] = frequency
                self.assertTrue(self.verify_row(row)["pass"])

    def test_malformed_plain_numeric_strings_fail(self):
        malformed = ("$7", "_7", "7_", "__7__", "7_0", "7.0.0", "7,0", "7e0")
        for frequency in malformed:
            with self.subTest(frequency=frequency):
                row = list(CLAIM_ROW)
                row[12] = frequency
                result = self.verify_row(row)
                self.assertFalse(result["pass"])
                self.assertIn("col 13", result["feedback"])

    def test_conventional_currency_representations_pass(self):
        for charge in (285, 285.0, "285", "285.00", "$285", "$285.00"):
            with self.subTest(charge=charge):
                row = list(CLAIM_ROW)
                row[15] = charge
                self.assertTrue(self.verify_row(row)["pass"])

    def test_malformed_currency_strings_fail(self):
        malformed = (
            "$$285",
            "2$85",
            "2,8,5",
            "28,5",
            "285,",
            "_285",
            "285_",
            "2_85",
            "285.000",
            "$+285.00",
            "$285.",
            "$285.0.0",
        )
        for charge in malformed:
            with self.subTest(charge=charge):
                row = list(CLAIM_ROW)
                row[15] = charge
                result = self.verify_row(row)
                self.assertFalse(result["pass"])
                self.assertIn("col 16", result["feedback"])

    def test_currency_formatted_frequency_fails(self):
        verify = load_verify(CLAIM_CRITERION)
        row = list(CLAIM_ROW)
        row[12] = "$7"
        row[15:19] = ["$285.00", "$0.00", "$0.00", "$0.00"]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, row)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertEqual(result["score"], 0.0)
            self.assertIn("22/23", result["feedback"])
            self.assertIn("col 13", result["feedback"])

    def test_22_of_23_row_fails(self):
        verify = load_verify(CLAIM_CRITERION)
        row = list(CLAIM_ROW)
        row[14] = "Resubmitted"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, row)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertEqual(result["score"], 0.0)
            self.assertIn("22/23", result["feedback"])
            self.assertIn("col 15", result["feedback"])

    def test_numeric_near_miss_fails(self):
        verify = load_verify(CLAIM_CRITERION)
        row = list(CLAIM_ROW)
        row[15] = 284
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_Claim_Register.xlsx")
            write_row(target, "Claim Register", 39, row)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("col 16", result["feedback"])


class RAQueueRegressions(unittest.TestCase):
    def run_case(self, criterion_id: str, status: str, resolution_date: object):
        claim_id, patient_id = RA_CASES[criterion_id]
        verify = load_verify(criterion_id)
        temp = tempfile.TemporaryDirectory()
        workspace = Path(temp.name)
        target = copy_workbook(workspace, "PBC_RA_Queue.xlsx")
        write_row(target, "RA Queue", 9, ra_row(claim_id, patient_id, status, resolution_date))
        return temp, verify(workspace)

    def test_resolved_with_resolution_date_passes(self):
        for criterion_id in RA_CASES:
            with self.subTest(criterion_id=criterion_id):
                temp, result = self.run_case(criterion_id, "Resolved", "04/24/2026")
                try:
                    self.assertTrue(result["pass"])
                finally:
                    temp.cleanup()

    def test_open_with_blank_resolution_date_passes(self):
        for criterion_id in RA_CASES:
            with self.subTest(criterion_id=criterion_id):
                temp, result = self.run_case(criterion_id, "Open", None)
                try:
                    self.assertTrue(result["pass"])
                finally:
                    temp.cleanup()

    def test_invalid_status_fails(self):
        for criterion_id in RA_CASES:
            with self.subTest(criterion_id=criterion_id):
                temp, result = self.run_case(criterion_id, "Resubmitted", None)
                try:
                    self.assertFalse(result["pass"])
                    self.assertIn("Status / Resolution Date", result["feedback"])
                finally:
                    temp.cleanup()

    def test_mixed_status_date_combinations_fail(self):
        for criterion_id in RA_CASES:
            for status, resolution_date in (("Resolved", None), ("Open", "04/24/2026")):
                with self.subTest(
                    criterion_id=criterion_id,
                    status=status,
                    resolution_date=resolution_date,
                ):
                    temp, result = self.run_case(criterion_id, status, resolution_date)
                    try:
                        self.assertFalse(result["pass"])
                    finally:
                        temp.cleanup()

    def test_claim_id_near_miss_fails(self):
        criterion_id = "rubric_1775705946912"
        claim_id, patient_id = RA_CASES[criterion_id]
        verify = load_verify(criterion_id)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_workbook(workspace, "PBC_RA_Queue.xlsx")
            row = ra_row(f"{claim_id}-extra", patient_id, "Resolved", "04/24/2026")
            write_row(target, "RA Queue", 9, row)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Claim ID", result["feedback"])


if __name__ == "__main__":
    unittest.main()
