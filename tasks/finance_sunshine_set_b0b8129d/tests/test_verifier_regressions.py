import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl


CRITERION_ID = "4e6e2fd8-4ad9-46c6-a1e5-fe07f75094ad"
TESTS_DIR = Path(__file__).resolve().parent


def load_verifier():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    criterion = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace = {}
    exec(compile(criterion["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


def run_verifier(note, due_date=datetime(2026, 2, 11)):
    with tempfile.TemporaryDirectory() as temp_dir:
        workbook_path = Path(temp_dir) / "Floorplan_Worksheet_April2026.xlsx"
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Floorplan Tracking"
        worksheet.append(
            [
                "Stock#",
                "VIN",
                "Vehicle",
                "Lender",
                "Advance Date",
                "Principal Balance",
                "Curtailment Due Date",
                "Status",
                "Days on Floor",
                "Lot Status",
                "Notes",
            ]
        )
        worksheet.append(
            [
                "N2048",
                "5TDJZRAH6RS904513",
                "2026 Toyota Highlander Platinum",
                "JM Family Enterprises",
                "01/12/2026",
                48200,
                due_date,
                "Aged Curtailment — Immediate Escalation",
                94,
                "On lot",
                note,
            ]
        )
        workbook.save(workbook_path)
        return load_verifier()(temp_dir)


class N2048CurtailmentVerifierTests(unittest.TestCase):
    def test_valid_64_plus_days_past_due_passes(self):
        note = (
            "Aged curtailment. Due 02/11/2026. 64+ days past due. "
            "Escalated to Marcus Hale and Elena Brooks."
        )
        result = run_verifier(note)
        self.assertTrue(result["pass"], result["feedback"])

    def test_equivalent_65_calendar_days_wording_passes(self):
        note = (
            "Aged curtailment. Due 02/11/2026. Curtailment past due by 65 calendar days. "
            "Escalated to Marcus Hale and Elena Brooks."
        )
        result = run_verifier(note)
        self.assertTrue(result["pass"], result["feedback"])

    def test_one_day_past_due_fails(self):
        note = (
            "Aged curtailment. Due 02/11/2026. 1 day past due. "
            "Escalated to Marcus Hale and Elena Brooks."
        )
        result = run_verifier(note)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("days_past_due_64_plus", result["feedback"])

    def test_missing_days_number_fails(self):
        note = (
            "Aged curtailment. Due 02/11/2026. Days past due. "
            "Escalated to Marcus Hale and Elena Brooks."
        )
        result = run_verifier(note)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("days_past_due_64_plus", result["feedback"])

    def test_notes_only_date_does_not_replace_structured_date(self):
        note = (
            "Aged curtailment. Due 02/11/2026. 64 days past due. "
            "Escalated to Marcus Hale and Elena Brooks."
        )
        result = run_verifier(note, due_date=None)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("structured_curtailment_due_date", result["feedback"])


if __name__ == "__main__":
    unittest.main()
