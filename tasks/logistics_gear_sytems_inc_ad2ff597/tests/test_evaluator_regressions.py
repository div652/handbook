#!/usr/bin/env python3
"""Focused regression for QI4's REC-20260309-004 Notes value."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "cdddc83d-60f9-421f-919a-40f373f12a20"
EXPECTED_NOTE = (
    "Supplier status: Approved as of 09/14/2023. "
    "Hazmat receipt — SDS on file: FL-21300-A1_SDS.pdf. "
    "Hazmat manifest on file."
)
EXPECTED_ROW = [
    "REC-20260309-004",
    "MER-PO-103515",
    "001",
    "FL-20044-A3",
    "N",
    "SUP-0010",
    "Reliant Freight Solutions",
    "03/09/2026 11:30 CST",
    "03/09/2026 12:15 CST",
    "Dock 3",
    "20",
    "20",
    "20",
    "0",
    "0.0%",
    "N/A",
    "Accepted",
    "Tier 0",
    "Accepted",
    "N/A",
    "Verified",
    "Accepted",
    "",
    "",
    "",
    "ACCEPTED CLEAN",
    "",
    "DH",
    EXPECTED_NOTE,
    "Posted",
    "03/09/2026 12:30 CST",
]
RUBRICS = {
    item["id"]: item
    for item in json.loads((TESTS_DIR / "rubrics.json").read_text(encoding="utf-8"))
}


def run_verifier(note: str) -> dict:
    rubric = RUBRICS[CRITERION_ID]
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(
        compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"),
        namespace,
    )

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        row = [*EXPECTED_ROW]
        row[28] = note
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=10, column=column, value=value)
        workbook.save(workspace / "receiving_log.xlsx")
        workbook.close()
        return namespace["verify"](str(workspace))


def verifier_expected_values() -> list[str]:
    tree = ast.parse(RUBRICS[CRITERION_ID]["verifier_code"])
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "expected_values"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("verifier does not define expected_values")


class QI4ExactValueRegressionTests(unittest.TestCase):
    def test_rubric_and_verifier_accept_immutable_ac10_value(self) -> None:
        rubric = RUBRICS[CRITERION_ID]
        rubric_note = (
            rubric["rubric_text"]
            .split("| DH |", 1)[1]
            .split("| Posted", 1)[0]
            .strip()
        )
        self.assertEqual(rubric_note, EXPECTED_NOTE)
        self.assertEqual(verifier_expected_values()[28], EXPECTED_NOTE)

        result = run_verifier(EXPECTED_NOTE)
        self.assertTrue(result["pass"], result["feedback"])

    def test_hsupplier_typo_is_not_the_expected_value(self) -> None:
        rubric = RUBRICS[CRITERION_ID]
        self.assertNotIn("HSupplier status", rubric["rubric_text"])
        self.assertNotIn("HSupplier status", rubric["verifier_code"])
        self.assertNotEqual(verifier_expected_values()[28], "H" + EXPECTED_NOTE)


if __name__ == "__main__":
    unittest.main()
