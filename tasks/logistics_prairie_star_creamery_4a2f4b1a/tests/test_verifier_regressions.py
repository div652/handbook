#!/usr/bin/env python3
"""Focused regressions for evaluator defects confirmed by the task RCA."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
SEED_DIR = TASK_DIR / "environment" / "initial_workspace"
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

RECEIVING_ID = "562add5f-6c5a-4847-867b-95a7857b0ee0"
SLACK_ID = "f14469ac-f9fd-44fe-b08b-d15bbb125abc"
TEMPERATURE_ID = "f2e1929e-2228-4d11-9fd6-8d79cbb6d35a"
INVENTORY_ID = "c3753422-0cdb-427c-9bbf-4dcd10e2c1c6"


def verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


def write_receiving_log(workspace: Path, overrides: dict[int, object] | None = None) -> None:
    values: dict[int, object] = {
        1: "2026-04-15-001",
        6: 210,
        7: -10.2,
        8: -10.2,
        9: -18.7,
        10: -13.03,
        11: "Tier 1",
        12: 0,
        13: 0,
        14: "Exact Match",
        15: (
            "A-20260410-01; A-20260411-01 -- MISMATCH - manifest "
            "A-20260412-01 vs received A-20260411-01; B-20260408-01"
        ),
        16: "none",
        17: "No damage",
        18: "P3",
        19: "Open",
        20: "Open pending lot-code clarification",
    }
    values.update(overrides or {})

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.cell(row=1, column=1, value="Manifest")
    sheet.cell(row=1, column=15, value="Lot Codes")
    for column, value in values.items():
        sheet.cell(row=2, column=column, value=value)
    workbook.save(workspace / "Inbound_Receiving_Log.xlsx")
    workbook.close()


def write_slack_state(workspace: Path, channel_name: str, message: str) -> None:
    state = {
        "channels": {"C1": {"name": channel_name}},
        "messages": {"C1": [{"text": message}]},
    }
    (workspace / "slack_data.json").write_text(json.dumps(state))


def nonempty_row_count(path: Path) -> int:
    workbook = openpyxl.load_workbook(path, data_only=True)
    try:
        return sum(
            any(cell.value is not None for cell in row)
            for row in workbook.active.iter_rows()
        )
    finally:
        workbook.close()


class ReceivingValueRegressions(unittest.TestCase):
    def evaluate(self, overrides: dict[int, object] | None = None) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_receiving_log(workspace, overrides)
            return verifier(RECEIVING_ID)(str(workspace))

    def test_exact_and_nearest_whole_degree_values_pass(self) -> None:
        cases = (
            {},
            {7: -10, 8: -10, 9: -19, 10: -13},
            {7: "-10°F", 8: "-10.2 F", 9: "-19° F", 10: "-13"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.evaluate(overrides)
                self.assertTrue(result["pass"], result["feedback"])

    def test_nearby_but_unapproved_values_fail(self) -> None:
        bad_values = {
            6: 209,
            7: -10.1,
            8: -11,
            9: -18,
            10: -14,
        }
        for column, value in bad_values.items():
            with self.subTest(column=column, value=value):
                result = self.evaluate({column: value})
                self.assertFalse(result["pass"], result["feedback"])


class SlackMismatchRegressions(unittest.TestCase):
    def evaluate(self, channel_name: str, message: str) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_slack_state(workspace, channel_name, message)
            return verifier(SLACK_ID)(str(workspace), str(workspace))

    def test_literal_mismatch_in_permitted_channel_passes(self) -> None:
        result = self.evaluate(
            "receiving-houston",
            "P3 manifest 2026-04-15-001 lot code mismatch requires clarification.",
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_lot_code_without_literal_mismatch_fails(self) -> None:
        result = self.evaluate(
            "receiving-houston",
            "P3 manifest 2026-04-15-001 has a lot code requiring clarification.",
        )
        self.assertFalse(result["pass"], result["feedback"])

    def test_message_in_unpermitted_channel_fails(self) -> None:
        result = self.evaluate(
            "general",
            "P3 manifest 2026-04-15-001 lot code mismatch requires clarification.",
        )
        self.assertFalse(result["pass"], result["feedback"])


class UnchangedWorkbookRegressions(unittest.TestCase):
    CASES = (
        (TEMPERATURE_ID, "temperature_log.xlsx"),
        (INVENTORY_ID, "inventory_master.xlsx"),
    )

    def test_exact_seed_artifacts_pass(self) -> None:
        for rubric_id, filename in self.CASES:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                shutil.copy2(SEED_DIR / filename, workspace / filename)
                result = verifier(rubric_id)(str(workspace))
                self.assertTrue(result["pass"], result["feedback"])

    def test_same_row_count_content_edits_fail(self) -> None:
        for rubric_id, filename in self.CASES:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                artifact = workspace / filename
                shutil.copy2(SEED_DIR / filename, artifact)
                seeded_rows = nonempty_row_count(artifact)

                workbook = openpyxl.load_workbook(artifact)
                sheet = workbook.active
                sheet["A2"] = f"corrupted-{sheet['A2'].value}"
                workbook.save(artifact)
                workbook.close()

                self.assertEqual(nonempty_row_count(artifact), seeded_rows)
                result = verifier(rubric_id)(str(workspace))
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("was changed", result["feedback"])


if __name__ == "__main__":
    unittest.main()
