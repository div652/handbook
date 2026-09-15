#!/usr/bin/env python3
"""Focused regressions for confirmed evaluator issues from the task RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl
from docx import Document


ROW_13_RUBRIC_ID = "rubric_1776309295974"
ROW_14_RUBRIC_ID = "rubric_1776309041156"
IR_001_RUBRIC_ID = "rubric_1776309397046"
IR_002_RUBRIC_ID = "rubric_1776309609324"
RUBRICS_PATH = Path(__file__).with_name("rubrics.json")
RUBRICS = {item["id"]: item for item in json.loads(RUBRICS_PATH.read_text())}


def run_verifier(rubric_id: str, workspace: Path) -> dict:
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"](str(workspace))


def write_receiving_log(
    workspace: Path,
    column_n: object,
    column_m: object = 2,
    status: str = "Open – Pending Major Variance Investigation",
) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    values = {
        1: "2026-04-15",
        2: "2026-04-15-002",
        3: "Waco Transfer",
        4: 26,
        5: 26,
        6: 520,
        7: 522,
        8: -18,
        9: -16,
        10: -20,
        11: -18,
        12: "Tier 1",
        13: column_m,
        14: column_n,
        16: status,
    }
    for column, value in values.items():
        worksheet.cell(row=13, column=column).value = value
    workbook.save(workspace / "inbound_receiving_log.xlsx")
    workbook.close()


def write_compound_receiving_log(
    workspace: Path,
    disposition: str,
    status: str = "",
    column_m: object = -4,
    column_n: object = "3%",
) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    values = {
        1: "2026-04-15",
        2: "2026-04-15-003",
        3: "Waco Transfer",
        4: 26,
        5: 26,
        6: 520,
        7: 516,
        8: -5,
        9: -4,
        10: -4,
        11: -4,
        12: "Tier 3",
        13: column_m,
        14: column_n,
        16: disposition,
        17: status,
    }
    for column, value in values.items():
        worksheet.cell(row=14, column=column).value = value
    workbook.save(workspace / "inbound_receiving_log.xlsx")
    workbook.close()


def write_ir_002(
    workspace: Path,
    temperatures: str,
    expected_quantity: str | None = "520",
    received_quantity: str | None = "516",
    quantity_statement: str | None = None,
    quantity_table: bool = False,
) -> None:
    if quantity_statement is not None:
        quantity_sentence = quantity_statement
    else:
        quantity_details = []
        if expected_quantity is not None:
            quantity_details.append(f"Expected quantity {expected_quantity}")
        if received_quantity is not None:
            quantity_details.append(f"received {received_quantity}")
        quantity_sentence = "; ".join(quantity_details)
    if quantity_sentence:
        quantity_sentence += "."

    document = Document()
    document.add_paragraph(
        "2026-04-15 — Houston — Manifest 2026-04-15-003 — Priority P2. "
        "Quantity variance identified; receipt quarantined. Escalated via email to "
        "Daniel Reyes and Carlos Mendoza, and notified Daniel Reyes. "
        f"Temperature readings: {temperatures}. {quantity_sentence}"
    )
    if quantity_table:
        table = document.add_table(rows=2, cols=3)
        table.rows[0].cells[0].text = "SKU"
        table.rows[0].cells[1].text = "Manifest"
        table.rows[0].cells[2].text = "Actual"
        table.rows[1].cells[0].text = "TOTAL"
        table.rows[1].cells[1].text = "520"
        table.rows[1].cells[2].text = "516"
    document.save(workspace / "IR-002-2026-04-15-Variance.docx")


class AggregatePercentageRegressionTests(unittest.TestCase):
    def verify_values(self, column_n: object, column_m: object = 2) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_receiving_log(workspace, column_n, column_m)
            return run_verifier(ROW_13_RUBRIC_ID, workspace)

    def test_numeric_zero_passes_for_rounded_aggregate_percentage(self) -> None:
        result = self.verify_values(0)
        self.assertTrue(result["pass"], result["feedback"])
        self.assertIn("PASS Row13 ColN", result["feedback"])

    def test_zero_percent_text_passes_for_rounded_aggregate_percentage(self) -> None:
        result = self.verify_values("0%")
        self.assertTrue(result["pass"], result["feedback"])
        self.assertIn("PASS Row13 ColN", result["feedback"])

    def test_other_numeric_column_n_representations_pass(self) -> None:
        # Per-SKU (-3% / +5%), the precise aggregate (0.38%), and the string "0" are
        # all numeric representations of the same variance and must pass.
        for value in ("0", 0.38, "0.4%", "-3% / +5%", "SC-006 -3%; SC-008 +5%"):
            with self.subTest(value=value):
                result = self.verify_values(value)
                self.assertTrue(result["pass"], result["feedback"])
                self.assertIn("PASS Row13 ColN", result["feedback"])

    def test_non_numeric_column_n_fails(self) -> None:
        for value in ("zero percent", None, "N/A"):
            with self.subTest(value=value):
                result = self.verify_values(value)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("FAIL Row13 ColN", result["feedback"])

    def test_column_m_remains_nonzero(self) -> None:
        result = self.verify_values(0, column_m=0)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("FAIL Row13 ColM", result["feedback"])

    def test_existing_sku_and_escalation_checks_remain(self) -> None:
        ir_001_code = RUBRICS[IR_001_RUBRIC_ID]["verifier_code"]
        for required_check in (
            "SC-006 variance details",
            "SC-008 variance details",
            "Daniel Reyes mentioned",
            "Carlos Mendoza mentioned",
            "Email escalation mentioned",
        ):
            with self.subTest(required_check=required_check):
                self.assertIn(required_check, ir_001_code)


class P2ReceiptStatusRegressionTests(unittest.TestCase):
    def verify_major_variance_status(self, status: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_receiving_log(workspace, 0, status=status)
            return run_verifier(ROW_13_RUBRIC_ID, workspace)

    def verify_compound_status(self, disposition: str, status: str = "") -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_compound_receiving_log(workspace, disposition, status)
            return run_verifier(ROW_14_RUBRIC_ID, workspace)

    def verify_compound_values(
        self,
        column_m: object,
        column_n: object,
        disposition: str = "Quarantine – H-Q pending Director assessment",
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_compound_receiving_log(
                workspace,
                disposition,
                column_m=column_m,
                column_n=column_n,
            )
            return run_verifier(ROW_14_RUBRIC_ID, workspace)

    def test_manifest_002_open_major_variance_investigation_passes(self) -> None:
        for status in (
            "Open – Pending Major Variance Investigation",
            "Hold – Pending Major Variance Investigation",
        ):
            with self.subTest(status=status):
                result = self.verify_major_variance_status(status)
                self.assertTrue(result["pass"], result["feedback"])

    def test_manifest_002_sop_12_6_pending_put_away_status_passes(self) -> None:
        for status in ("Received - Pending Put-Away", "Received – Pending Put-Away"):
            with self.subTest(status=status):
                result = self.verify_major_variance_status(status)
                self.assertTrue(result["pass"], result["feedback"])
                self.assertIn("PASS Row13 ColP/Q (Status)", result["feedback"])

    def test_manifest_002_closed_status_fails(self) -> None:
        result = self.verify_major_variance_status("Closed – Accepted")
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("FAIL Row13 ColP/Q (Status)", result["feedback"])

    def test_manifest_003_quarantine_pending_director_assessment_passes(self) -> None:
        result = self.verify_compound_status(
            "Quarantine – H-Q pending Director assessment"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_manifest_003_split_quarantine_assessment_state_passes(self) -> None:
        result = self.verify_compound_status(
            "Segregated Frozen Hold – H-Q; no standard put-away",
            "Open – P2 Compound Event / Quarantine Confirmation and Director Assessment Pending",
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_manifest_003_sop_12_6_pending_put_away_status_passes(self) -> None:
        result = self.verify_compound_status("Received - Pending Put-Away")
        self.assertTrue(result["pass"], result["feedback"])

    def test_manifest_003_hold_open_pending_variance_resolution_passes(self) -> None:
        result = self.verify_compound_status(
            "Conditional Acceptance – temperature flag",
            "Open – Pending Variance Resolution",
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_manifest_003_closed_status_fails(self) -> None:
        result = self.verify_compound_status("Closed – Accepted")
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("mandatory held-open receipt state", result["feedback"])

    def test_manifest_003_receipt_level_m_and_n_are_mandatory(self) -> None:
        cases = (
            ("SC-003: −4", "3%", "Column M"),
            (-4, "SC-003: −2.5%", "Column N"),
        )
        for column_m, column_n, failed_column in cases:
            with self.subTest(column_m=column_m, column_n=column_n):
                result = self.verify_compound_values(column_m, column_n)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn(failed_column, result["feedback"])
                self.assertIn("mandatory receipt-level", result["feedback"])

    def test_manifest_003_scalar_receipt_value_formats_pass(self) -> None:
        for column_m, column_n in ((-4, "3%"), ("−4", 0.03), (-4.0, 3)):
            with self.subTest(column_m=column_m, column_n=column_n):
                result = self.verify_compound_values(column_m, column_n)
                self.assertTrue(result["pass"], result["feedback"])
                self.assertIn("Mandatory gates passed", result["feedback"])

    def test_manifest_003_nonmandatory_miss_retains_partial_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_compound_receiving_log(
                workspace,
                "Quarantine – H-Q pending Director assessment",
            )
            workbook_path = workspace / "inbound_receiving_log.xlsx"
            workbook = openpyxl.load_workbook(workbook_path)
            workbook.active.cell(row=14, column=3).value = None
            workbook.save(workbook_path)
            workbook.close()

            result = run_verifier(ROW_14_RUBRIC_ID, workspace)
            self.assertTrue(result["pass"], result["feedback"])
            self.assertAlmostEqual(result["score"], 14 / 15)
            self.assertIn("Mandatory gates passed", result["feedback"])


class UnicodeMinusRegressionTests(unittest.TestCase):
    def verify_temperatures(
        self,
        temperatures: str,
        expected_quantity: str | None = "520",
        received_quantity: str | None = "516",
        quantity_statement: str | None = None,
        quantity_table: bool = False,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_ir_002(
                workspace,
                temperatures,
                expected_quantity=expected_quantity,
                received_quantity=received_quantity,
                quantity_statement=quantity_statement,
                quantity_table=quantity_table,
            )
            return run_verifier(IR_002_RUBRIC_ID, workspace)

    def test_ascii_minus_temperatures_still_pass(self) -> None:
        result = self.verify_temperatures("-5, -4, and -4.5")
        self.assertTrue(result["pass"], result["feedback"])

    def test_unicode_minus_temperatures_pass(self) -> None:
        result = self.verify_temperatures("−5, −4, and −4.5")
        self.assertTrue(result["pass"], result["feedback"])
        for reading in ("-5", "-4", "-4.5"):
            self.assertIn(f"PASS: Temperature reading {reading}", result["feedback"])

    def test_other_dash_characters_are_not_normalized(self) -> None:
        result = self.verify_temperatures("–5, –4, and –4.5")
        self.assertFalse(result["pass"], result["feedback"])
        for reading in ("-5", "-4", "-4.5"):
            self.assertIn(f"FAIL: Temperature reading {reading}", result["feedback"])

    def test_ir_002_aggregate_totals_are_individually_mandatory(self) -> None:
        cases = (
            (None, "516", "Expected quantity 520"),
            ("520", None, "Received quantity 516"),
        )
        for expected, received, failed_check in cases:
            with self.subTest(expected=expected, received=received):
                result = self.verify_temperatures(
                    "−5, −4, and −4.5",
                    expected_quantity=expected,
                    received_quantity=received,
                )
                self.assertFalse(result["pass"], result["feedback"])
                self.assertAlmostEqual(result["score"], 13 / 14)
                self.assertIn(f"FAIL: {failed_check}", result["feedback"])
                self.assertIn("required aggregate totals", result["feedback"])

    def test_retained_fable_ir_002_without_both_totals_fails(self) -> None:
        result = self.verify_temperatures(
            "−5, −4, and −4.5",
            expected_quantity=None,
            received_quantity=None,
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertAlmostEqual(result["score"], 12 / 14)
        self.assertIn("required aggregate totals", result["feedback"])

    def test_ir_002_unrelated_numbers_do_not_satisfy_totals(self) -> None:
        for quantity_statement in (
            "Reference ticket 520; page 516",
            "Expected quantity 516; received 520",
            "Expected quantity 1520; received 1516",
        ):
            with self.subTest(quantity_statement=quantity_statement):
                result = self.verify_temperatures(
                    "-5, -4, and -4.5",
                    expected_quantity=None,
                    received_quantity=None,
                    quantity_statement=quantity_statement,
                )
                self.assertFalse(result["pass"], result["feedback"])
                self.assertAlmostEqual(result["score"], 12 / 14)
                self.assertIn("FAIL: Expected quantity 520", result["feedback"])
                self.assertIn("FAIL: Received quantity 516", result["feedback"])

    def test_ir_002_retained_valid_total_phrasings_pass(self) -> None:
        for quantity_statement in (
            "Manifest total 520; received total 516",
            "Total received 516 cases against a manifest total of 520",
            "520 expected; 516 received",
        ):
            with self.subTest(quantity_statement=quantity_statement):
                result = self.verify_temperatures(
                    "−5, −4, and −4.5",
                    expected_quantity=None,
                    received_quantity=None,
                    quantity_statement=quantity_statement,
                )
                self.assertTrue(result["pass"], result["feedback"])

    def test_ir_002_retained_manifest_actual_total_table_passes(self) -> None:
        result = self.verify_temperatures(
            "-5, -4, and -4.5",
            expected_quantity=None,
            received_quantity=None,
            quantity_table=True,
        )
        self.assertTrue(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
