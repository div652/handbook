#!/usr/bin/env python3
"""Focused regressions for comprehensive-QC findings QI2, QI3, and QI5."""

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
SEED_WORKSPACE = TASK_DIR / "environment" / "initial_workspace"
RUBRICS = json.loads((TESTS_DIR / "rubrics.json").read_text())

AMOUNTS_CRITERION = "e93679bd-96c4-43a4-bd26-29973129e54e"
SLACK_CRITERION = "fd59b3bf-8c01-42a6-beae-7c1ba3b035ae"
SCOPE_CRITERION = "rubric_1787788800001"


def load_verify(criterion_id: str):
    rubric = next(item for item in RUBRICS if item["id"] == criterion_id)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{criterion_id}>", "exec"), namespace)
    return namespace["verify"]


def copy_seed(workspace: Path, filename: str) -> Path:
    target = workspace / filename
    shutil.copy2(SEED_WORKSPACE / filename, target)
    return target


def find_row(sheet, key_header: str, key_value: str) -> int:
    headers = [cell.value for cell in sheet[1]]
    key_column = headers.index(key_header) + 1
    rows = [
        row
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row=row, column=key_column).value == key_value
    ]
    if len(rows) != 1:
        raise AssertionError(f"expected one {key_value} row, found {rows}")
    return rows[0]


def set_value(path: Path, key_header: str, key_value: str, field: str, value: object) -> None:
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active
    headers = [cell.value for cell in sheet[1]]
    row = find_row(sheet, key_header, key_value)
    sheet.cell(row=row, column=headers.index(field) + 1).value = value
    workbook.save(path)


class ExactAmountRegressions(unittest.TestCase):
    def verify_amounts(self, billed: object, paid: object, adjustment: object):
        verify = load_verify(AMOUNTS_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = copy_seed(workspace, "PBC_Claim_Register.xlsx")
            workbook = openpyxl.load_workbook(target)
            sheet = workbook.active
            headers = [cell.value for cell in sheet[1]]
            values = {
                "Claim_Status": "Written Off",
                "Billed_Amount": billed,
                "Paid_Amount": paid,
                "Adjustment_Amount": adjustment,
            }
            for field, value in values.items():
                sheet.cell(row=3, column=headers.index(field) + 1).value = value
            workbook.save(target)
            return verify(workspace)

    def test_exact_amounts_pass(self):
        self.assertTrue(self.verify_amounts(285, 285, 0)["pass"])

    def test_near_misses_within_old_tolerance_fail(self):
        cases = (
            (284, 285, 0, "Billed_Amount"),
            (285, 286, 0, "Paid_Amount"),
            (285, 285, 1, "Adjustment_Amount"),
        )
        for billed, paid, adjustment, field in cases:
            with self.subTest(field=field):
                result = self.verify_amounts(billed, paid, adjustment)
                self.assertFalse(result["pass"])
                self.assertIn(field, result["feedback"])


class CanonicalSlackMessageRegressions(unittest.TestCase):
    def verify_messages(self, messages: list[str]):
        verify = load_verify(SLACK_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            services = root / "services"
            workspace.mkdir()
            services.mkdir()
            state = {
                "channels": {"C-SPECIAL": {"name": "special-authorization"}},
                "messages": {
                    "C-SPECIAL": [{"text": message} for message in messages],
                },
            }
            (services / "slack_data.json").write_text(json.dumps(state))
            return verify(workspace, services)

    def test_both_authorization_spellings_pass(self):
        for spelling in ("authorized", "authorised"):
            with self.subTest(spelling=spelling):
                message = f"Alex Rivera: CLM-2026-0062 special action {spelling}"
                self.assertTrue(self.verify_messages([message])["pass"])

    def test_whitespace_is_normalized_before_full_match(self):
        message = "  Alex\tRivera:  CLM-2026-0062\n special action   authorized  "
        self.assertTrue(self.verify_messages([message])["pass"])

    def test_prefixes_and_suffixes_fail(self):
        canonical = "Alex Rivera: CLM-2026-0062 special action authorized"
        for message in (f"NOTICE: {canonical}", f"{canonical} today", f"{canonical}."):
            with self.subTest(message=message):
                self.assertFalse(self.verify_messages([message])["pass"])

    def test_noncanonical_case_and_punctuation_fail(self):
        messages = (
            "alex Rivera: CLM-2026-0062 special action authorized",
            "Alex Rivera - CLM-2026-0062 special action authorized",
        )
        for message in messages:
            with self.subTest(message=message):
                self.assertFalse(self.verify_messages([message])["pass"])

    def test_two_canonical_messages_fail_exactly_one_requirement(self):
        result = self.verify_messages(
            [
                "Alex Rivera: CLM-2026-0062 special action authorized",
                "Alex Rivera: CLM-2026-0062 special action authorised",
            ]
        )
        self.assertFalse(result["pass"])
        self.assertIn("found 2", result["feedback"])


class OutOfScopePreservationRegressions(unittest.TestCase):
    filenames = (
        "PBC_RA_Queue.xlsx",
        "PBC_Claim_Register.xlsx",
        "PBC_Denial_Worklist.xlsx",
    )

    def make_workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        workspace.mkdir()
        for filename in self.filenames:
            copy_seed(workspace, filename)
        return workspace

    def verify_mutation(
        self,
        filename: str,
        key_header: str,
        key_value: str,
        field: str,
        value: object,
    ):
        verify = load_verify(SCOPE_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace(Path(tmp))
            set_value(workspace / filename, key_header, key_value, field, value)
            return verify(workspace)

    def test_seeded_out_of_scope_rows_pass(self):
        verify = load_verify(SCOPE_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace(Path(tmp))
            self.assertTrue(verify(workspace)["pass"])

    def test_every_seeded_q_2026_003_field_is_protected(self):
        cases = (
            ("Date_Added", datetime(2026, 1, 31)),
            ("Claim_ID", "CLM-2026-0066"),
            ("Work_Item_Type", "Claim Follow-up"),
            ("Priority_Level", "Level 3: Medium"),
            ("Status", "Open"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                result = self.verify_mutation(
                    "PBC_RA_Queue.xlsx",
                    "Queue_ID",
                    "Q-2026-003",
                    field,
                    value,
                )
                self.assertFalse(result["pass"])
                self.assertIn(field, result["feedback"])

    def test_duplicate_q_2026_003_row_fails(self):
        verify = load_verify(SCOPE_CRITERION)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace(Path(tmp))
            path = workspace / "PBC_RA_Queue.xlsx"
            workbook = openpyxl.load_workbook(path)
            sheet = workbook.active
            source_row = find_row(sheet, "Queue_ID", "Q-2026-003")
            sheet.append([cell.value for cell in sheet[source_row]])
            workbook.save(path)
            result = verify(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("expected exactly one Q-2026-003 row, found 2", result["feedback"])

    def test_existing_claim_and_denial_protections_remain_enforced(self):
        cases = (
            (
                "PBC_Claim_Register.xlsx",
                "Claim_ID",
                "CLM-2026-0065",
                "Claim_Status",
                "Denied",
            ),
            (
                "PBC_Denial_Worklist.xlsx",
                "Denial_ID",
                "DNL-2026-005",
                "Recovery_Action",
                "Write Off",
            ),
        )
        for filename, key_header, key_value, field, value in cases:
            with self.subTest(filename=filename, field=field):
                result = self.verify_mutation(
                    filename,
                    key_header,
                    key_value,
                    field,
                    value,
                )
                self.assertFalse(result["pass"])
                self.assertIn(field, result["feedback"])


if __name__ == "__main__":
    unittest.main()
