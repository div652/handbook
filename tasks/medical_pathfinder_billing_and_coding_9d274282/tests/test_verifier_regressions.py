#!/usr/bin/env python3
"""Focused regressions for the Daily Posting Log sign-off verifier."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "09393a5a-5aa7-45f4-9033-6e4055388b6f"


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


class DailyPostingLogSignoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(_load_verify())

    def _verify(self, signoff_status, signoff_role, *, notes=""):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Daily Posting Logs"
            sheet.append(
                [
                    "Posting Date",
                    "Batch ID",
                    "Payments Posted",
                    "Posting Status",
                    "Sign-off Status",
                    "Sign-off Role",
                    "Notes",
                ]
            )
            sheet.append(
                [
                    "2026-03-31",
                    "BATCH2026033101",
                    2794.50,
                    "Posted",
                    signoff_status,
                    signoff_role,
                    notes,
                ]
            )
            workbook.save(Path(tmp) / "PBC_Audit_Log.xlsx")
            return self.verify(tmp)

    def _verify_direct(self, value, *, header="RCM Manager Sign-off"):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Daily Posting Logs"
            sheet.append(
                ["Posting Date", "Batch ID", "Payments Posted", header]
            )
            sheet.append(
                ["2026-03-31", "BATCH2026033101", 2794.50, value]
            )
            workbook.save(Path(tmp) / "PBC_Audit_Log.xlsx")
            return self.verify(tmp)

    def _verify_approver_fields(self, name, role):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Daily Posting Logs"
            sheet.append(
                [
                    "Posting Date",
                    "Batch ID",
                    "Payments Posted",
                    "Approver Name",
                    "Approver Role",
                ]
            )
            sheet.append(
                [
                    "2026-03-31",
                    "BATCH2026033101",
                    2794.50,
                    name,
                    role,
                ]
            )
            workbook.save(Path(tmp) / "PBC_Audit_Log.xlsx")
            return self.verify(tmp)

    def test_accepts_affirmative_rcm_manager_signoff(self) -> None:
        result = self._verify("Approved", "RCM Manager")
        self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_affirmative_on_duty_auditor_signoff(self) -> None:
        result = self._verify("Signed off", "On-duty Resolution Auditor")
        self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_named_manager_in_direct_signoff_field(self) -> None:
        result = self._verify_direct("Jane Manager")
        self.assertTrue(result["pass"], result["feedback"])

    def test_accepts_task_grounded_approver_header_variants(self) -> None:
        result = self._verify_approver_fields("Jane Manager", "RCM Manager")
        self.assertTrue(result["pass"], result["feedback"])

    def test_rejects_blank_signoff_fields(self) -> None:
        result = self._verify(None, None, notes="RCM Manager will review tomorrow")
        self.assertFalse(result["pass"], result["feedback"])

    def test_rejects_pending_or_absent_wording(self) -> None:
        result = self._verify("Pending - RCM Manager absent", None)
        self.assertFalse(result["pass"], result["feedback"])

    def test_rejects_nonaffirmative_status_even_for_authorized_role(self) -> None:
        result = self._verify("Needs review", "RCM Manager")
        self.assertFalse(result["pass"], result["feedback"])

    def test_rejects_unauthorized_role(self) -> None:
        result = self._verify("Approved", "Billing Specialist")
        self.assertFalse(result["pass"], result["feedback"])

    def test_rejects_demonstrated_direct_signer_placeholders_and_prose(self) -> None:
        placeholders = (
            None,
            "",
            "N/A",
            "NA",
            "None",
            "Requested",
            "Scheduled",
            "Not provided",
            "Not available",
            "Not applicable",
            "Pending",
            "Pending - RCM Manager absent",
            "RCM Manager absent",
            "Manager unavailable",
            "Awaiting RCM Manager",
            "Approval requested",
            "Sign-off scheduled",
            "Not signed",
            "No signature",
            "No approver",
            "Needs review",
            "Review later",
            "Will review",
            "To follow",
            "See notes",
            "Approval forthcoming",
            "Manager notified",
            "Unassigned",
            "Incomplete",
            "null",
            "TBD",
        )
        for placeholder in placeholders:
            with self.subTest(placeholder=placeholder):
                result = self._verify_direct(placeholder)
                self.assertFalse(result["pass"], result["feedback"])

    def test_rejects_unauthorized_role_in_direct_signoff_field(self) -> None:
        result = self._verify_direct("Billing Specialist")
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
