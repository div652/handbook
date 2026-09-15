#!/usr/bin/env python3
"""Focused regressions for Template 6 outbound send-history grading."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
import task_verifier_utils


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "24fa1712-d834-44c2-93cc-9384dea24276"
REMOVED_SLACK_COUNT_ID = "rubric_1776823960297"
WORKBOOK_CRITERIA = {
    "d7011e7c-9854-46a7-9e2d-3323e2cba9ab": "employee_roster.xlsx",
    "rubric_1776826027518": "hfwa_balance_tracker.xlsx",
    "rubric_1776826059275": "hours_worked_log.xlsx",
}
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}


def verifier():
    namespace = {"__builtins__": __builtins__}
    code = RUBRICS[CRITERION_ID]["verifier_code"]
    exec(compile(code, f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


def rubric_verifier(rubric_id: str):
    namespace = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"]


class Template6SendHistoryRegressions(unittest.TestCase):
    def evaluate(self, *, folder: str, sender: str = "leaves@ridgelinegear.com") -> dict:
        mailbox = {
            "mailbox": {
                "email": "leaves@ridgelinegear.com",
                "name": "Leave Coordinator",
            },
            "contacts": [
                {
                    "name": "Tomás Guerrero",
                    "email": "tomas.guerrero@ridgelinegear.com",
                }
            ],
            "emails": [
                {
                    "email_id": "40",
                    "folder": folder,
                    "from_addr": sender,
                    "to_addr": "tomas.guerrero@ridgelinegear.com",
                    "subject": "Medical Certification Reminder",
                    "body_text": (
                        "Hi Tomás,\n\n"
                        "This is a reminder for Case ID LC-2026-0321. "
                        "Your WH-380-F was originally sent on 03/26/2026. "
                        "The certification is due 04/15/2026, which is 5 "
                        "calendar days from the original deadline."
                    ),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            services = root / "services"
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps(mailbox))
            return verifier()(str(root), str(services))

    def test_filed_after_send_still_counts_as_sent(self) -> None:
        result = self.evaluate(folder="FMLA Cases")
        self.assertTrue(result["pass"], result["feedback"])

    def test_draft_and_scheduled_owner_messages_do_not_count_as_sent(self) -> None:
        for folder in ("Draft", "Drafts", "Scheduled"):
            with self.subTest(folder=folder):
                result = self.evaluate(folder=folder)
                self.assertFalse(result["pass"], result["feedback"])

    def test_current_sent_folder_does_not_make_a_foreign_sender_outbound(self) -> None:
        result = self.evaluate(
            folder="Sent",
            sender="tomas.guerrero@ridgelinegear.com",
        )
        self.assertFalse(result["pass"], result["feedback"])


class OnboardingWorkbookRegressions(unittest.TestCase):
    def build_logical_seed(self, workspace: Path, filename: str) -> tuple[Path, dict]:
        path = workspace / filename
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = task_verifier_utils.SEEDED_LOGICAL_SNAPSHOTS[filename]["sheet_names"][0]
        worksheet.append(["ID", "Name", "Value", "Derived"])
        worksheet.append(["R-1001", "Alex Rivera", 1.0, "=C2*2"])
        worksheet.append(["R-1002", "Morgan Lee", 2, "=C3*2"])
        worksheet.merge_cells("A5:B5")
        worksheet["A5"] = "Seed footer"
        workbook.save(path)
        workbook.close()

        workbook = openpyxl.load_workbook(path, data_only=False)
        snapshot = task_verifier_utils._logical_snapshot(workbook)
        workbook.close()
        expected = {
            "sha256": task_verifier_utils._snapshot_fingerprint(snapshot),
            "sheet_names": snapshot["sheet_names"],
            "populated_cells": sum(len(sheet["cells"]) for sheet in snapshot["sheets"]),
        }
        return path, expected

    def evaluate(self, rubric_id: str, workspace: Path, expected: dict | None = None) -> dict:
        verify = rubric_verifier(rubric_id)
        if expected is None:
            return verify(str(workspace), None)
        filename = WORKBOOK_CRITERIA[rubric_id]
        with patch.dict(
            task_verifier_utils.SEEDED_LOGICAL_SNAPSHOTS,
            {filename: expected},
            clear=False,
        ):
            return verify(str(workspace), None)

    def test_redundant_slack_count_criterion_is_removed(self) -> None:
        self.assertNotIn(REMOVED_SLACK_COUNT_ID, RUBRICS)

    def test_canonical_logical_workbook_snapshots_pass(self) -> None:
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                _, expected = self.build_logical_seed(workspace, filename)
                result = self.evaluate(rubric_id, workspace, expected)
                self.assertTrue(result["pass"], result["feedback"])

    def test_reordered_rows_fail_logical_snapshot_comparison(self) -> None:
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                path, expected = self.build_logical_seed(workspace, filename)
                workbook = openpyxl.load_workbook(path, data_only=False)
                worksheet = workbook.active
                row_two = [worksheet.cell(2, column).value for column in range(1, worksheet.max_column + 1)]
                row_three = [worksheet.cell(3, column).value for column in range(1, worksheet.max_column + 1)]
                for column, (value_two, value_three) in enumerate(zip(row_two, row_three), start=1):
                    worksheet.cell(2, column).value = value_three
                    worksheet.cell(3, column).value = value_two
                workbook.save(path)
                workbook.close()

                result = self.evaluate(rubric_id, workspace, expected)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("logical snapshot", result["feedback"])

    def test_missing_and_corrupt_exact_workbooks_fail(self) -> None:
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            with self.subTest(filename=filename, state="missing"), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                decoy = openpyxl.Workbook()
                decoy.save(workspace / f"renamed-{filename}")
                decoy.close()
                result = self.evaluate(rubric_id, workspace)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("missing", result["feedback"].lower())

            with self.subTest(filename=filename, state="corrupt"), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                (workspace / filename).write_bytes(b"not an xlsx package")
                result = self.evaluate(rubric_id, workspace)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("could not be opened", result["feedback"].lower())

    def test_each_scott_identifier_is_rejected_in_every_workbook(self) -> None:
        identifiers = (
            "Scott Young",
            "scott.young@ridgelinegear.com",
            "young.s@gmail.com",
        )
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            for identifier in identifiers:
                with (
                    self.subTest(filename=filename, identifier=identifier),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    workspace = Path(temporary)
                    path, expected = self.build_logical_seed(workspace, filename)
                    workbook = openpyxl.load_workbook(path, data_only=False)
                    worksheet = workbook.create_sheet("Elsewhere")
                    worksheet["Z99"] = f"Onboarding record: {identifier}"
                    workbook.save(path)
                    workbook.close()

                    result = self.evaluate(rubric_id, workspace, expected)
                    self.assertFalse(result["pass"], result["feedback"])
                    self.assertIn("prohibited Scott Young onboarding data", result["feedback"])
                    self.assertIn("Elsewhere!Z99", result["feedback"])

    def test_harmless_xlsx_serialization_round_trip_passes(self) -> None:
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                path, expected = self.build_logical_seed(workspace, filename)
                workbook = openpyxl.load_workbook(path, data_only=False)
                workbook.save(path)
                workbook.close()

                result = self.evaluate(rubric_id, workspace, expected)
                self.assertTrue(result["pass"], result["feedback"])

    def test_substantive_non_scott_mutation_fails(self) -> None:
        for rubric_id, filename in WORKBOOK_CRITERIA.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                path, expected = self.build_logical_seed(workspace, filename)
                workbook = openpyxl.load_workbook(path, data_only=False)
                worksheet = workbook.active
                worksheet["A2"] = f"{worksheet['A2'].value}-MUTATED"
                workbook.save(path)
                workbook.close()

                result = self.evaluate(rubric_id, workspace, expected)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("logical snapshot", result["feedback"])


if __name__ == "__main__":
    unittest.main()
