#!/usr/bin/env python3
"""Focused regressions for the approved QI1 repair and confirmed QI2 repair."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import openpyxl
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


TESTS_DIR = Path(__file__).resolve().parent
INITIAL_WORKSPACE = TESTS_DIR.parent / "environment" / "initial_workspace"
CRITERION_ID = "9ed41faa-6e26-4966-b450-fb6f0739baa4"
RELEASE_CRITERION_IDS = (
    "0582f69f-6456-4e9f-a350-fc8a218496b6",
    "a773a42e-e1fe-4032-a1c8-31074ef3a0aa",
    "633b2dbd-6618-480b-bee1-843a9ad68813",
    "7056c0e4-718d-4ecf-b54b-abe1d1497bd2",
    "3366695a-2408-4dc6-b59c-5e73ca53d99f",
    "5de62afe-3687-426c-af6f-53d58dea3b01",
    "rubric_1776327435121",
)
NCR_INITIAL_ROWS = (
    (
        "NCR_Number", "Issue_Date", "Supplier_ID", "Supplier_Name", "PO_Number",
        "Receipt_ID", "SKUs", "Quantity_Affected", "NCR_Type", "Severity",
        "Dollar_Value", "Status", "Issued_By", "Supplier_Response_Due",
        "Supplier_Response_Date", "Corrective_Action_Summary", "Internal_Reviewer",
        "Resolution_Notes", "Description",
    ),
    (
        "NCR-MER-2026-0231", "03/15/2026", "SUP-0034",
        "Hartwell Bearing Technologies", "MER-PO-104801", "REC-20260315-002",
        "BG-33044-A1", 8, "DMG", "Major", 1484, "Closed", "K.W.", "04/04/2026",
        "03/28/2026",
        "Carrier damage confirmed; carrier claim filed; supplier issued revised packing instructions",
        "Theo Brandt",
        "Closed 04/05/2026 — carrier liability confirmed. Supplier revised inner packing.",
        "Tier 2 damage on 8 of 96 tapered roller bearings — impact dents on outer race. Carrier damage during transit.",
    ),
    (
        "NCR-MER-2026-0235", "03/22/2026", "SUP-0089",
        "GreatLakes Transmission Parts", "MER-PO-104808", "REC-20260322-001",
        "TR-67801-D1", 3, "QTY", "Major", 1836, "Closed", "K.W.", "04/05/2026",
        "04/01/2026",
        "Supplier acknowledged picking error; issued credit memo; balance shipped on MER-PO-104874",
        "Joon-ho Park",
        "Closed 04/05/2026 — supplier acknowledged picking error. Credit memo received. Balance 3 units confirmed shipped on MER-PO-104874.",
        "Band 2 short ship: ordered 24, received 21 (−3 units, −12.5%) on TR-67801-D1.",
    ),
    (
        "NCR-MER-2026-0239", "04/05/2026", "SUP-0051", "Cascade Fastener Corp",
        "MER-PO-104839", "REC-20260405-003", "FN-33102-B2", 200, "QTY",
        "Critical", 240, "Closed", "K.W.", "04/25/2026", "04/12/2026",
        "Supplier acknowledged count error; issued credit. No corrective action beyond count verification.",
        "Joon-ho Park",
        "Closed 04/15/2026 — credit memo received. Supplier acknowledged picking error.",
        "Band 3 short ship on FN-33102-B2: ordered 1000, received 800 (−200 units, −20.0%). Supplier on Probation. Severity elevated to Critical.",
    ),
    (
        "NCR-MER-2026-0241", "04/13/2026", "SUP-0051", "Cascade Fastener Corp",
        "MER-PO-104847", "REC-20260412-001", "FS-22801-A3", 17, "QTY",
        "Critical", 82.45, "Open", "K.W.", "05/02/2026", None, None,
        "Joon-ho Park", None,
        "Band 1 short ship on safety-critical FS-22801-A3: ordered 500, received 483 (−17 units, −3.4%). Supplier on Probation. Severity elevated to Critical.",
    ),
    (
        "NCR-MER-2026-0247", "04/14/2026", "SUP-0012",
        "Lakewood Precision Forgings", "MER-PO-104821", "REC-20260414-001",
        "AX-04827-B2, AX-05512-C1, FG-91144-A1", 4, "MIX", "Critical", 52300,
        "Open", "K.W.", "04/21/2026", None, None, "Theo Brandt", None,
        "Missing COC on safety-critical receipt (AX/FG parts). Band 1 short ship on AX-04827-B2 (−4 units, −8.3%). Full receipt quarantined pending COC receipt. Dollar value reflects full quarantined receipt value (340 units across all 3 lines) per SOP 14.3.4 DOC NCR valuation: AX-04827-B2 44×$425 + AX-05512-C1 96×$187.50 + FG-91144-A1 200×$78.",
    ),
    (
        "NCR-MER-2026-0248", "04/14/2026", "SUP-0034",
        "Hartwell Bearing Technologies", "MER-PO-104835", "REC-20260414-002",
        "BG-33044-A1", 11, "DMG", "Major", 2040.5, "Open", "K.W.",
        "04/28/2026", None, None, "Theo Brandt", None,
        "Tier 2 damage on 11 of 144 BG-33044-A1 tapered roller bearings — impact dents on outer race. Safety-critical part. Material quarantined pending Quality inspection.",
    ),
    (
        "NCR-MER-2026-0249", "04/14/2026", "SUP-0034",
        "Hartwell Bearing Technologies", "MER-PO-104835", "REC-20260414-002",
        "SL-10922-B1", 12, "QTY", "Minor", 393, "Open", "K.W.", "05/05/2026",
        None, None, "Joon-ho Park", None,
        "Over ship Band B on SL-10922-B1: ordered 288, received 300 (+12 units, +4.2%). Standard part. Excess 12 units staged pending Procurement disposition. Severity Minor. 15 business days for supplier response.",
    ),
)
RUBRICS = {
    item["id"]: item
    for item in json.loads((TESTS_DIR / "rubrics.json").read_text(encoding="utf-8"))
}


def run_verifier(
    workspace: Path,
    criterion_id: str = CRITERION_ID,
    external_services: Path | None = None,
) -> dict:
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[criterion_id]["verifier_code"]
    exec(compile(code, f"<{criterion_id}>", "exec"), namespace)
    return namespace["verify"](
        str(workspace),
        str(external_services) if external_services is not None else None,
    )


def write_text_pdf(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    text = pdf.beginText(54, 738)
    text.setFont("Helvetica", 9)
    for line in lines:
        text.textLine(line)
    pdf.drawText(text)
    pdf.save()


def write_valid_coc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        INITIAL_WORKSPACE / "quality_docs" / "MER-PO-104821_COC.pdf",
        path,
    )


def write_initial_ncr_log(path: Path) -> None:
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "NCR Log"
        for row in NCR_INITIAL_ROWS:
            sheet.append(row)
        workbook.save(path)
    finally:
        workbook.close()


def set_cell(path: Path, coordinate: str, value) -> None:
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        workbook.active[coordinate] = value
        workbook.save(path)
    finally:
        workbook.close()


def write_release_inventory(path: Path) -> None:
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Inventory Master"
        sheet["A1"] = "SKU"
        for row in range(2, 22):
            sheet.cell(row, 1, f"FIXTURE-SKU-{row:02d}")
        sheet["G8"] = 285
        sheet["M8"] = "04/14/2026"
        sheet["N8"] = "REC-20260414-001"
        sheet["O8"] = 0
        sheet["P8"] = None
        sheet["S8"] = "HT-2026-0218, HT-2026-1803"
        sheet["A8"] = "FG-91144-A1"
        workbook.save(path)
    finally:
        workbook.close()


def write_release_receiving(path: Path) -> None:
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Receiving Log"
        sheet["V10"] = "COC Received and Verified"
        sheet["W10"] = "Accepted"
        sheet["X10"] = "ACCEPTED"
        sheet["Z10"] = datetime(2026, 4, 23, 9, 0)
        sheet["AA10"] = "A-09-01"
        sheet["AB10"] = "Putaway Complete"
        workbook.save(path)
    finally:
        workbook.close()


@contextmanager
def valid_release_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        services = root / "services"
        workspace.mkdir()
        services.mkdir()

        write_release_inventory(workspace / "inventory_master.xlsx")
        write_release_receiving(workspace / "receiving_log.xlsx")

        coc_dir = workspace / "quality_docs"
        coc_dir.mkdir()
        write_valid_coc(
            coc_dir / "MER-PO-104821_COC.pdf",
        )
        write_text_pdf(
            workspace / "quarantine_releases" / "REC-20260414-001_release.pdf",
            [
                "I've reviewed the COC submitted by Lakewood Precision Forgings this morning for the FG-91144-A1 line under REC-20260414-001.",
                "The COC is acceptable",
                "heat number HT-2026-1803 is confirmed and the documentation is complete.",
                "You are authorized to release FG-91144-A1 from Q-HOLD. Quantity: 200 units. Please proceed with the standard quarantine release procedure.",
                "Theo Brandt",
            ],
        )

        calendar_description = (
            "Theo Brandt to verify COC against MTR heat numbers: HT-2026-1184, "
            "HT-2026-1185, HT-2026-0997 for receipt REC-20260414-001 "
            "(NCR-MER-2026-0247)\n"
            "Partial release 04/23/2026: FG-91144-A1 released "
            "(200 units to A-09-01). Remaining on Q-HOLD: "
            "AX-04827-B2 (44 units); AX-05512-C1 (96 units)."
        )
        (services / "calendar_data.json").write_text(
            json.dumps(
                {
                    "events": {
                        "evt-025": {
                            "summary": "COC verification follow-up",
                            "description": calendar_description,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        release_message = (
            "QUARANTINE RELEASED: REC-20260414-001, SKU FG-91144-A1, "
            "qty 200 released from Q-HOLD to A-09-01. Authorization: "
            "Theo Brandt, 04/23/2026."
        )
        (services / "slack_data.json").write_text(
            json.dumps(
                {
                    "channels": {"C-DOCK": {"name": "receiving-dock"}},
                    "messages": {"C-DOCK": [{"ts": "1", "text": release_message}]},
                }
            ),
            encoding="utf-8",
        )
        yield workspace, services


class NcrLogNoChangesRegressionTests(unittest.TestCase):
    def evaluate_mutation(self, mutate=None) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            candidate = workspace / "ncr_log.xlsx"
            write_initial_ncr_log(candidate)
            if mutate is not None:
                workbook = openpyxl.load_workbook(candidate, data_only=False)
                try:
                    mutate(workbook.active)
                    workbook.save(candidate)
                finally:
                    workbook.close()
            return run_verifier(workspace)

    def test_unchanged_initial_workbook_passes(self) -> None:
        result = self.evaluate_mutation()
        self.assertTrue(result["pass"], result["feedback"])

    def test_semantically_unchanged_round_trip_passes(self) -> None:
        result = self.evaluate_mutation(lambda sheet: None)
        self.assertTrue(result["pass"], result["feedback"])

    def test_status_changes_in_l6_or_l7_fail(self) -> None:
        for coordinate in ("L6", "L7"):
            with self.subTest(coordinate=coordinate):
                result = self.evaluate_mutation(
                    lambda sheet, coordinate=coordinate: setattr(
                        sheet[coordinate], "value", "Closed"
                    )
                )
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("must remain Open", result["feedback"])

    def test_accurate_note_outside_l6_and_l7_is_allowed(self) -> None:
        result = self.evaluate_mutation(
            lambda sheet: setattr(
                sheet["R6"],
                "value",
                "Release note added while the Status cells remain Open.",
            )
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_appended_row_is_outside_this_criterion(self) -> None:
        result = self.evaluate_mutation(
            lambda sheet: sheet.append(["NCR-MER-2026-9999", "04/23/2026"])
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_unrelated_formula_is_outside_this_criterion(self) -> None:
        result = self.evaluate_mutation(
            lambda sheet: setattr(sheet["K2"], "value", "=740+744")
        )
        self.assertTrue(result["pass"], result["feedback"])


class CocReleaseGateRegressionTests(unittest.TestCase):
    def evaluate_release_criteria(
        self,
        workspace: Path,
        services: Path,
    ) -> dict[str, dict]:
        return {
            criterion_id: run_verifier(
                workspace,
                criterion_id=criterion_id,
                external_services=services,
            )
            for criterion_id in RELEASE_CRITERION_IDS
        }

    def test_all_seven_release_criteria_accept_valid_matching_coc(self) -> None:
        with valid_release_fixture() as (workspace, services):
            results = self.evaluate_release_criteria(workspace, services)
        for criterion_id, result in results.items():
            with self.subTest(criterion_id=criterion_id):
                self.assertTrue(result["pass"], result["feedback"])

    def test_all_seven_release_criteria_reject_missing_coc(self) -> None:
        with valid_release_fixture() as (workspace, services):
            (workspace / "quality_docs" / "MER-PO-104821_COC.pdf").unlink()
            results = self.evaluate_release_criteria(workspace, services)
        for criterion_id, result in results.items():
            with self.subTest(criterion_id=criterion_id):
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("matching COC evidence is missing", result["feedback"])

    def test_all_seven_release_criteria_reject_mismatched_coc(self) -> None:
        with valid_release_fixture() as (workspace, services):
            coc = workspace / "quality_docs" / "MER-PO-104821_COC.pdf"
            coc.write_bytes(coc.read_bytes() + b"\nmodified")
            results = self.evaluate_release_criteria(workspace, services)
        for criterion_id, result in results.items():
            with self.subTest(criterion_id=criterion_id):
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("immutable authoritative shipment COC", result["feedback"])

    def test_existing_release_requirements_remain_enforced(self) -> None:
        cases = (
            (
                "0582f69f-6456-4e9f-a350-fc8a218496b6",
                lambda workspace, services: (
                    workspace
                    / "quarantine_releases"
                    / "REC-20260414-001_release.pdf"
                ).unlink(),
                "not found",
            ),
            (
                "a773a42e-e1fe-4032-a1c8-31074ef3a0aa",
                lambda workspace, services: set_cell(
                    workspace / "inventory_master.xlsx", "G8", 85
                ),
                "G8 expected 285",
            ),
            (
                "633b2dbd-6618-480b-bee1-843a9ad68813",
                lambda workspace, services: set_cell(
                    workspace / "inventory_master.xlsx", "A22", "EXTRA-ROW"
                ),
                "Expected exactly 20 data rows",
            ),
            (
                "7056c0e4-718d-4ecf-b54b-abe1d1497bd2",
                lambda workspace, services: set_cell(
                    workspace / "receiving_log.xlsx", "V10", "Quarantine - missing COC"
                ),
                "V10 expected COC Received and Verified",
            ),
            (
                "3366695a-2408-4dc6-b59c-5e73ca53d99f",
                self.remove_calendar_partial_release,
                "missing Partial release annotation",
            ),
            (
                "5de62afe-3687-426c-af6f-53d58dea3b01",
                self.remove_slack_release_message,
                "has no messages",
            ),
            (
                "rubric_1776327435121",
                self.replace_release_pdf_content,
                "missing",
            ),
        )
        for criterion_id, mutate, expected_feedback in cases:
            with self.subTest(criterion_id=criterion_id):
                with valid_release_fixture() as (workspace, services):
                    mutate(workspace, services)
                    result = run_verifier(
                        workspace,
                        criterion_id=criterion_id,
                        external_services=services,
                    )
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn(expected_feedback, result["feedback"])

    @staticmethod
    def remove_calendar_partial_release(workspace: Path, services: Path) -> None:
        path = services / "calendar_data.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["events"]["evt-025"]["description"] = (
            "Theo Brandt to verify COC against MTR heat numbers: HT-2026-1184, "
            "HT-2026-1185, HT-2026-0997 for receipt REC-20260414-001 "
            "(NCR-MER-2026-0247)"
        )
        path.write_text(json.dumps(data), encoding="utf-8")

    @staticmethod
    def remove_slack_release_message(workspace: Path, services: Path) -> None:
        path = services / "slack_data.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["messages"]["C-DOCK"] = []
        path.write_text(json.dumps(data), encoding="utf-8")

    @staticmethod
    def replace_release_pdf_content(workspace: Path, services: Path) -> None:
        write_text_pdf(
            workspace / "quarantine_releases" / "REC-20260414-001_release.pdf",
            ["Unrelated release authorization."],
        )


if __name__ == "__main__":
    unittest.main()


class SeededReinspectionEventTests(unittest.TestCase):
    """The seeded evt-025 must be identifiable as the SOP §14.6 re-inspection event."""

    CALENDAR_SEED = (
        TESTS_DIR.parent / "environment" / "initial_external_services"
        / "google_calendar" / "calendar_data.json"
    )
    REINSPECTION_TITLE = (
        'RE-INSPECTION: REC-20260414-001 AX-04827-B2 / AX-05512-C1 / FG-91144-A1 Missing COC'
    )
    ORIGINAL_PHRASE = (
        "Theo Brandt to verify COC against MTR heat numbers: HT-2026-1184, HT-2026-1185, "
        "HT-2026-0997 for receipt REC-20260414-001 (NCR-MER-2026-0247)"
    )

    def seeded_event(self) -> dict:
        data = json.loads(self.CALENDAR_SEED.read_text(encoding="utf-8"))
        return data["events"]["evt-025"]

    def test_seed_names_the_reinspection_event_and_keeps_original_phrase(self) -> None:
        description = self.seeded_event()["description"]
        self.assertIn(self.REINSPECTION_TITLE, description)
        self.assertIn(self.ORIGINAL_PHRASE, description)
        self.assertNotIn("[COMPLETED]", self.seeded_event()["summary"].upper())

    def test_partial_release_annotation_on_seeded_description_passes(self) -> None:
        rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
        rubric = next(item for item in rubrics if item["id"].startswith("3366695a"))
        namespace = {"__builtins__": __builtins__}
        exec(compile(rubric["verifier_code"], "<3366695a>", "exec"), namespace)
        data = json.loads(self.CALENDAR_SEED.read_text(encoding="utf-8"))
        data["events"]["evt-025"]["description"] += (
            "\nPartial release 04/23/2026: FG-91144-A1 released (200 units to A-09-01). "
            "Remaining on Q-HOLD: AX-04827-B2 (44 units); AX-05512-C1 (96 units)."
        )
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            (services / "calendar_data.json").write_text(json.dumps(data), encoding="utf-8")
            result = namespace["verify"](str(INITIAL_WORKSPACE), str(services))
        self.assertTrue(result["pass"], result["feedback"])
