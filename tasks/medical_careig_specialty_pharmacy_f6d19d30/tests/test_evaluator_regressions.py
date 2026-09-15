#!/usr/bin/env python3
"""Focused regression for the audit-row verifier's archived-run stability."""

from __future__ import annotations

import datetime as real_datetime
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "rubric_1775063145806"


def _load_verify(regrade_today: real_datetime.date):
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)

    class FutureDate(real_datetime.date):
        @classmethod
        def today(cls):
            return cls(
                regrade_today.year,
                regrade_today.month,
                regrade_today.day,
            )

    future_datetime = types.ModuleType("datetime")
    future_datetime.date = FutureDate
    future_datetime.datetime = real_datetime.datetime
    future_datetime.timedelta = real_datetime.timedelta

    namespace: dict[str, object] = {"__builtins__": __builtins__}
    with mock.patch.dict("sys.modules", {"datetime": future_datetime}):
        exec(
            compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"),
            namespace,
        )
    return namespace["verify"], rubric["verifier_code"]


def _write_audit_log(workspace: Path, logged_date: str) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Date",
            "Patient_Last_Name",
            "Patient_First_Name",
            "Patient_DOB",
            "Action",
            "File_Updated",
            "Fields_Updated",
            "New_Value",
            "Staff_User",
            "Result",
        ]
    )
    sheet.append(
        [
            logged_date,
            "Lopez",
            "Kevin",
            "11091990",
            "Financial Counseling Complete",
            "Benefits.xlsx",
            "Financial_Counseling_Log; BV_Complete",
            "03/26/2026 14:36—SUCCESS; YES",
            "Mark",
            "SUCCESS",
        ]
    )
    workbook.save(workspace / "audit_log.xlsx")
    workbook.close()


class AuditDateVerifierRegressionTests(unittest.TestCase):
    def test_scenario_date_remains_valid_on_future_regrade(self) -> None:
        verify, verifier_code = _load_verify(real_datetime.date(2035, 12, 31))
        self.assertNotIn("date.today", verifier_code)

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _write_audit_log(workspace, "03/26/2026")
            result = verify(str(workspace))

        self.assertTrue(result["pass"], result["feedback"])

    def test_unrelated_date_is_not_accepted(self) -> None:
        verify, _ = _load_verify(real_datetime.date(2035, 12, 31))

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _write_audit_log(workspace, "12/31/2035")
            result = verify(str(workspace))

        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
