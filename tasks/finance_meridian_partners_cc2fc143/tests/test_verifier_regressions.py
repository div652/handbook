#!/usr/bin/env python3
"""Focused regressions for RCA findings QI2 and QI3."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
SOURCE_LEDGER = TASK_DIR / "environment" / "initial_workspace" / "ap_ledger.xlsx"
RUBRICS_PATH = TESTS_DIR / "rubrics.json"

ROW_VALUES = [
    "GLFD-0441",
    "V-00009",
    "Great Lakes Furniture & Design Co.",
    datetime(2026, 3, 20),
    datetime(2026, 3, 24),
    datetime(2026, 4, 19),
    "Non-PO",
    7900.0,
    "1000-100-6200",
    "Open",
]


def load_verify(criterion_id: str):
    rubrics = json.loads(RUBRICS_PATH.read_text())
    rubric = next(item for item in rubrics if item["id"] == criterion_id)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{criterion_id}>", "exec"), namespace)
    return namespace["verify"]


def make_ledger(workspace: Path, row_values=ROW_VALUES) -> Path:
    target = workspace / "ap_ledger.xlsx"
    shutil.copy2(SOURCE_LEDGER, target)
    workbook = openpyxl.load_workbook(target)
    sheet = workbook["Invoice Register"]
    for column, value in enumerate(row_values, start=1):
        sheet.cell(row=13, column=column).value = value
    workbook.save(target)
    return target


class VerifierRegressions(unittest.TestCase):
    def test_required_row_accepts_values_in_named_columns(self):
        verify = load_verify("53c53e31-7fa0-4136-9885-e8eb58789e27")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_ledger(workspace)
            self.assertTrue(verify(workspace)["pass"])

    def test_required_row_rejects_swapped_fields(self):
        verify = load_verify("53c53e31-7fa0-4136-9885-e8eb58789e27")
        swapped = list(ROW_VALUES)
        swapped[1], swapped[2] = swapped[2], swapped[1]
        swapped[3], swapped[5] = swapped[5], swapped[3]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_ledger(workspace, swapped)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Vendor ID", result["feedback"])
            self.assertIn("Invoice Date", result["feedback"])

    def test_required_row_accepts_narrow_valid_formulas(self):
        verify = load_verify("53c53e31-7fa0-4136-9885-e8eb58789e27")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = make_ledger(workspace)
            workbook = openpyxl.load_workbook(target)
            sheet = workbook["Invoice Register"]
            sheet["F13"] = "=D13+30"
            sheet["H13"] = "=7900"
            workbook.save(target)
            self.assertTrue(verify(workspace)["pass"])

    def test_required_row_rejects_uncached_unrecognized_formulas(self):
        verify = load_verify("53c53e31-7fa0-4136-9885-e8eb58789e27")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = make_ledger(workspace)
            workbook = openpyxl.load_workbook(target)
            sheet = workbook["Invoice Register"]
            sheet["F13"] = "=D13+29+1"
            sheet["H13"] = "=7800+100"
            workbook.save(target)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Due Date", result["feedback"])
            self.assertIn("Invoice Amount", result["feedback"])

    def test_blank_fields_after_status_pass(self):
        verify = load_verify("rubric_1774390462114")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_ledger(workspace)
            self.assertTrue(verify(workspace)["pass"])

    def test_numeric_zero_after_status_is_populated(self):
        verify = load_verify("rubric_1774390462114")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = make_ledger(workspace)
            workbook = openpyxl.load_workbook(target)
            sheet = workbook["Invoice Register"]
            sheet["N13"] = 0
            workbook.save(target)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Credit Applied", result["feedback"])
            self.assertIn("=0", result["feedback"])


if __name__ == "__main__":
    unittest.main()
