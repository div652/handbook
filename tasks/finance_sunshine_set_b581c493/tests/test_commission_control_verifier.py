#!/usr/bin/env python3
"""Focused regressions for the commission-control workbook verifier."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path


RUBRICS_PATH = Path(__file__).with_name("rubrics.json")
RUBRIC_ID = "rubric_p23_commission_offset_notification"
RUBRIC = next(
    rubric for rubric in json.loads(RUBRICS_PATH.read_text())
    if rubric["id"] == RUBRIC_ID
)
INITIAL_WORKSPACE = Path(__file__).parents[1] / "environment" / "initial_workspace"

HEADERS = [
    "CB Ref #",
    "Employee",
    "Original Deal #",
    "Original Commission Paid",
    "Chargeback Amount",
    "Chargeback Date",
    "Offset Amount",
    "Planned Offset Pay Period",
    "Confirmation / Approval",
    "Offset Status",
    "Notes",
]

VALID_ROW = [
    "CB-2608",
    "D. Watts",
    4451,
    480,
    1600,
    date(2026, 4, 24),
    480,
    "05/01/2026",
    "Pending — Leah Morgan confirmation requested",
    "Pending — not applied",
    "Awaiting confirmation before next payroll",
]


class FakeSheet:
    def __init__(self, rows: list[list[object]], title: str = "Commission Control") -> None:
        self._rows = rows
        self.title = title

    def iter_rows(self, values_only: bool = False):
        assert values_only
        return iter(self._rows)


class FakeWorkbook:
    def __init__(self, rows: list[list[object]]) -> None:
        self.worksheets = [FakeSheet(rows)]

    def close(self) -> None:
        pass


def verifier_namespace() -> dict:
    namespace = {"__builtins__": __builtins__}
    exec(compile(RUBRIC["verifier_code"], f"<{RUBRIC_ID}>", "exec"), namespace)
    return namespace


def run_with_rows(rows: list[list[object]], title: str = "Commission Control") -> dict:
    namespace = verifier_namespace()
    namespace["load_workbook"] = lambda *_args, **_kwargs: FakeWorkbook(rows)
    if title != "Commission Control":
        namespace["load_workbook"] = lambda *_args, **_kwargs: FakeWorkbookWithTitle(rows, title)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copy2(
            INITIAL_WORKSPACE / "commission_control.xlsx",
            root / "commission_control.xlsx",
        )
        (root / "commission_control_v2.xlsx").touch()
        return namespace["verify"](str(root))


class FakeWorkbookWithTitle(FakeWorkbook):
    def __init__(self, rows: list[list[object]], title: str) -> None:
        self.worksheets = [FakeSheet(rows, title)]


class CommissionControlVerifierTests(unittest.TestCase):
    def test_initial_workbook_does_not_pre_satisfy_cb2608(self) -> None:
        workspace = Path(__file__).parents[1] / "environment" / "initial_workspace"
        if not (workspace / "commission_control.xlsx").is_file():
            self.skipTest("source initial workspace is not mounted in the verifier container")

        result = verifier_namespace()["verify"](str(workspace))

        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("No suffixed", result["feedback"])

    def test_complete_pending_offset_record_passes(self) -> None:
        result = run_with_rows([
            ["Sunshine & Set Automotive — Commission Control Workbook"],
            ["Instructions"],
            HEADERS,
            VALID_ROW,
        ])

        self.assertTrue(result["pass"], result["feedback"])

    def test_row_on_wrong_sheet_fails(self) -> None:
        result = run_with_rows([HEADERS, VALID_ROW], title="Offsets")

        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Commission Control sheet", result["feedback"])

    def test_incomplete_or_premature_record_fails(self) -> None:
        invalid_values = {
            1: "R. Vasquez",
            2: 4452,
            3: 479,
            4: 1599,
            5: date(2026, 4, 22),
            6: 479,
            7: "",
            8: "Leah Morgan approval required",
            9: "Applied",
        }
        for index, invalid_value in invalid_values.items():
            with self.subTest(column=HEADERS[index]):
                row = list(VALID_ROW)
                row[index] = invalid_value
                result = run_with_rows([HEADERS, row])
                self.assertFalse(result["pass"], result["feedback"])

    def test_overwritten_original_fails_even_when_revision_is_valid(self) -> None:
        namespace = verifier_namespace()
        namespace["load_workbook"] = lambda *_args, **_kwargs: FakeWorkbook(
            [HEADERS, VALID_ROW]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "commission_control.xlsx").write_bytes(b"overwritten")
            (root / "commission_control_v2.xlsx").touch()

            result = namespace["verify"](str(root))

        self.assertFalse(result["pass"])
        self.assertIn("overwritten", result["feedback"])


if __name__ == "__main__":
    unittest.main()
