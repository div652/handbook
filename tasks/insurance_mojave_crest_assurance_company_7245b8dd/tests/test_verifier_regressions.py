#!/usr/bin/env python3
"""Focused regressions for workbook evaluator defects found by the RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}
CORE_FIELDS = "9aeac6a7-fef6-4523-9c07-d42bb426047d"
CASE_FILE_BUNDLE = "9c9243f4-674c-4f52-ab01-e744f345aef9"
SERVICE_AND_TIME = "55b538b6-0a08-42fb-aad4-4ac14a0d3a56"
ROUTING = "46482065-82b3-40bc-8a6c-140a563c39d1"
CASE_FORMULAS = "rubric_1776219626382"
NO_ROWS_AFTER_8 = "rubric_1776219767187"
BLANK_FIELDS = "rubric_1776219797164"
DECISION_DUE_SORT_ORDER = "rubric_decision_due_sort_order"
CASE_BOUND_VERIFIERS = (
    CORE_FIELDS,
    SERVICE_AND_TIME,
    ROUTING,
    CASE_FORMULAS,
    BLANK_FIELDS,
)
WORKBOOK_VERIFIERS = (*CASE_BOUND_VERIFIERS, NO_ROWS_AFTER_8)

HEADERS = [
    "Case ID",
    "Member ID",
    "Group ID",
    "Plan Year",
    "Total Dispute Value",
    "Appeal Type",
    "Service Classification",
    "Standard of Review",
    "Date of Receipt",
    "Acknowledgment Due",
    "Acknowledgment Sent",
    "Tolled (Y/N)",
    "Toll Start",
    "Toll End",
    "Decision Due",
    "Reviewer Assigned",
    "Parity Flag",
    "Compliance Escalation",
    "Related Case ID",
    "Decision Date",
    "Outcome",
    "External Review Requested",
    "Case Status",
    "Coordinator",
]

CASE_BUNDLE_FILENAMES = (
    "EOC-MCA4471-PY2026.pdf",
    "Kovacs_James_ClinicalPacket_CR-2026-044721.pdf",
    "MCA_Denial_Letter_Kovacs_James_CR-2026-044721.pdf",
    "MP-019-v2.2-20260101.pdf",
)
PRIOR_AUTH_FILENAME = "Prior_Authorization_History_Kovacs_James_44710006.xlsx"
CLAIMS_PAYMENT_FILENAME = "Claims_Payment_History_Kovacs_James_44710006.xlsx"


def verifier(rubric_id: str):
    namespace = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


def full_formula(row: int, offset: int) -> str:
    if offset == 1:
        return (
            f'=IF(I{row}="","",IF(ISNUMBER(SEARCH("Concurrent Care",F{row})),'
            f'I{row}+1,IF(OR(F{row}="Pre-Service Standard",'
            f'F{row}="Post-Service Standard",F{row}="Grievance"),'
            f'WORKDAY(INT(I{row}),5),INT(I{row})+1)))'
        )
    return (
        f'=IF(I{row}="","",IF(ISNUMBER(SEARCH("Concurrent Care",F{row})),'
        f'I{row}+3,IF(F{row}="Post-Service Standard",'
        f'INT(I{row})+60+IF(L{row}="Y",N{row}-M{row},0),'
        f'IF(OR(F{row}="Pre-Service Standard",F{row}="Grievance"),'
        f'INT(I{row})+30+IF(L{row}="Y",N{row}-M{row},0),""))))'
    )


def populate_case(
    sheet,
    row: int,
    *,
    timestamp: datetime | str | None = None,
    use_full_formulas: bool = False,
) -> None:
    values = {
        1: "CASE-2026-00478",
        2: "44710006",
        3: "MCA-4471",
        4: 2026,
        5: "undetermined",
        6: "Concurrent Care",
        7: "Inpatient, SUD, In-Network",
        8: "Medical Necessity",
        9: timestamp or datetime(2026, 4, 14, 9, 47, 0),
        10: (
            full_formula(row, 1)
            if use_full_formulas
            else f'=IF(ISNUMBER(SEARCH("Concurrent Care",F{row})),I{row}+1,"")'
        ),
        15: (
            full_formula(row, 3)
            if use_full_formulas
            else f'=IF(ISNUMBER(SEARCH("Concurrent Care",F{row})),I{row}+3,"")'
        ),
        16: "Dr. Ayla Ontario, MD (Behavioral Health)",
        17: "Y",
        18: "N",
        23: "With Reviewer",
        24: "K. Whitfield",
    }
    for column, value in values.items():
        sheet.cell(row=row, column=column).value = value


def create_prior_authorization_history(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Authorization History"
    sheet.append([])
    sheet.append([])
    sheet.append([])
    sheet.append([
        "Record Type",
        "Authorization No.",
        "Member ID",
        "Group ID",
        "Provider",
        "Service",
        "Service Start",
        "Authorized Through / Effective",
        "Determination Date",
        "Status",
        "Case / Review",
        "Notes",
    ])
    sheet.append([
        "Initial authorization",
        "PA-4471-2026-0312",
        "44710006",
        "MCA-4471",
        "Desert Peaks Rehabilitation Center",
        "H0019 — Inpatient Rehabilitation, SUD",
        datetime(2026, 3, 15),
        datetime(2026, 4, 14),
        None,
        "Authorized",
        "CR-2026-044721",
        "Services authorized and rendered before 2026-04-15 are unaffected by the concurrent-care determination.",
    ])
    sheet.append([
        "Concurrent care determination",
        "PA-4471-2026-0312",
        "44710006",
        "MCA-4471",
        "Desert Peaks Rehabilitation Center",
        "H0019 — Continued Inpatient Rehabilitation, SUD",
        datetime(2026, 4, 15),
        datetime(2026, 4, 15),
        datetime(2026, 4, 7),
        "Denied — Adverse Determination; appeal pending",
        "CR-2026-044721 / CASE-2026-00478",
        "Continued authorization denial effective 2026-04-15; expedited appeal received 2026-04-14.",
    ])
    workbook.save(path)
    workbook.close()


def create_claims_payment_history(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Claims Payment History"
    sheet.append([])
    sheet.append([])
    sheet.append([])
    sheet.append([
        "Claim No.",
        "Service Start",
        "Service End",
        "Provider",
        "Service Description",
        "Billed",
        "Allowed",
        "Plan Paid",
        "Status",
        "Authorization No.",
        "Appeal / Notes",
    ])
    sheet.append([
        "CLM-2026-4471-0089",
        datetime(2026, 3, 15),
        datetime(2026, 4, 14),
        "Desert Peaks Rehabilitation Center",
        "H0019 — Inpatient Rehabilitation, SUD (30 days)",
        30000,
        24000,
        19200,
        "PAID",
        "PA-4471-2026-0312",
        None,
    ])
    sheet.append([
        "CLM-2026-4471-0094",
        datetime(2026, 4, 15),
        None,
        "Desert Peaks Rehabilitation Center",
        "H0019 — Inpatient Rehabilitation, SUD (ongoing)",
        None,
        0,
        0,
        "DENIED — Adverse Determination",
        "PA-4471-2026-0312",
        "Pending appeal CR-2026-044721; filed 2026-04-14.",
    ])
    workbook.save(path)
    workbook.close()


class WorkbookVerifierRegressions(unittest.TestCase):
    def make_workspace(self, configure) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        workspace = Path(temporary.name)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Appeals Log"
        for column, header in enumerate(HEADERS, start=1):
            sheet.cell(row=2, column=column).value = header
        configure(sheet)
        workbook.save(workspace / "appeals_log_master.xlsx")
        workbook.close()
        return temporary, workspace

    def make_case_bundle_workspace(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        workspace = Path(temporary.name)
        case_folder = workspace / "CASE-2026-00478"
        case_folder.mkdir()
        for filename in CASE_BUNDLE_FILENAMES:
            (case_folder / filename).write_bytes(b"test fixture")
        create_prior_authorization_history(case_folder / PRIOR_AUTH_FILENAME)
        create_claims_payment_history(case_folder / CLAIMS_PAYMENT_FILENAME)
        return temporary, workspace, case_folder

    def test_complete_case_bundle_with_valid_histories_passes(self) -> None:
        temporary, workspace, _ = self.make_case_bundle_workspace()
        with temporary:
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertTrue(result["pass"], result["feedback"])
            self.assertIn("validated prior-authorization", result["feedback"])

    def test_raw_claims_history_pdf_is_not_required(self) -> None:
        temporary, workspace, case_folder = self.make_case_bundle_workspace()
        with temporary:
            self.assertFalse(
                (case_folder / "Claims_History_Kovacs_James_44710006.pdf").exists()
            )
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertTrue(result["pass"], result["feedback"])

    def test_missing_history_fails_case_bundle(self) -> None:
        temporary, workspace, case_folder = self.make_case_bundle_workspace()
        with temporary:
            (case_folder / PRIOR_AUTH_FILENAME).unlink()
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn(PRIOR_AUTH_FILENAME, result["feedback"])

    def test_corrupt_history_fails_closed(self) -> None:
        temporary, workspace, case_folder = self.make_case_bundle_workspace()
        with temporary:
            (case_folder / CLAIMS_PAYMENT_FILENAME).write_bytes(b"not an xlsx")
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Could not open", result["feedback"])

    def test_mismatched_prior_authorization_history_fails(self) -> None:
        temporary, workspace, case_folder = self.make_case_bundle_workspace()
        with temporary:
            path = case_folder / PRIOR_AUTH_FILENAME
            workbook = openpyxl.load_workbook(path)
            workbook["Authorization History"]["H5"] = datetime(2026, 4, 13)
            workbook.save(path)
            workbook.close()
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("row 5 Authorized Through", result["feedback"])

    def test_mismatched_claims_payment_history_fails(self) -> None:
        temporary, workspace, case_folder = self.make_case_bundle_workspace()
        with temporary:
            path = case_folder / CLAIMS_PAYMENT_FILENAME
            workbook = openpyxl.load_workbook(path)
            workbook["Claims Payment History"]["H5"] = 19000
            workbook.save(path)
            workbook.close()
            result = verifier(CASE_FILE_BUNDLE)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("row 5 Plan Paid", result["feedback"])

    def test_core_fields_follow_case_to_sorted_row(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: populate_case(sheet, 6)
        )
        with temporary:
            result = verifier(CORE_FIELDS)(workspace)
            self.assertTrue(result["pass"], result["feedback"])
            self.assertIn("row 6", result["feedback"])

    def test_case_id_near_miss_is_not_selected(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 1).value = "CASE-2026-00478-EXTRA"

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CORE_FIELDS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("No row", result["feedback"])

    def test_formulas_follow_case_to_sorted_row(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: populate_case(sheet, 6)
        )
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertTrue(result["pass"], result["feedback"])
            self.assertIn("case row 6", result["feedback"])

    def test_full_xhigh_formulas_and_formula_only_row_9_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6, use_full_formulas=True)
            sheet.cell(6, 6).value = "Concurrent Care — Expedited"
            sheet.cell(6, 7).value = "Inpatient — SUD — In-Network"
            sheet.cell(9, 10).value = full_formula(9, 1)
            sheet.cell(9, 15).value = full_formula(9, 3)

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            row_guard_result = verifier(NO_ROWS_AFTER_8)(workspace)
            for rubric_id in CASE_BOUND_VERIFIERS:
                result = verifier(rubric_id)(workspace)
                self.assertTrue(result["pass"], (rubric_id, result["feedback"]))
            self.assertTrue(row_guard_result["pass"], row_guard_result["feedback"])

    def test_row_8_formulas_cannot_rescue_broken_case_row_formulas(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = datetime(2026, 4, 15, 9, 47, 0)
            sheet.cell(6, 15).value = datetime(2026, 4, 17, 9, 47, 0)
            sheet.cell(8, 1).value = "CASE-2026-OTHER"
            sheet.cell(8, 10).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F8)),I8+1,"")'
            sheet.cell(8, 15).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F8)),I8+3,"")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("case row 6", result["feedback"])

    def test_formula_references_are_boundary_exact(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F60)),I60+1,"")'
            sheet.cell(6, 15).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F60)),I60+3,"")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("exact row-relative I6", result["feedback"])
            self.assertIn("exact row-relative F6", result["feedback"])

    def test_formula_rows_must_be_relative(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F$6)),I$6+1,"")'
            sheet.cell(6, 15).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F$6)),I$6+3,"")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("row-relative", result["feedback"])

    def test_formula_offsets_are_exact_numeric_operations(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+10,"")'
            sheet.cell(6, 15).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+30,"")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("exact I6+1 operation", result["feedback"])
            self.assertIn("exact I6+3 operation", result["feedback"])

    def test_formula_offset_cannot_be_extended_by_more_arithmetic(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+1+9,"")'
            sheet.cell(6, 15).value = '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+3+27,"")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("exact I6+1 operation", result["feedback"])
            self.assertIn("exact I6+3 operation", result["feedback"])

    def test_string_literal_pseudo_formulas_do_not_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '="Concurrent Care F6 I6 +1"'
            sheet.cell(6, 15).value = '="Concurrent Care F6 I6 +3"'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("exact row-relative I6", result["feedback"])

    def test_formula_keywords_without_a_concurrent_search_do_not_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = '="Concurrent Care"&F6&I6+1'
            sheet.cell(6, 15).value = '="Concurrent Care"&F6&I6+3'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("SEARCH condition", result["feedback"])

    def test_disconnected_sum_fragments_do_not_pass_as_conditional_formula(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=SUM(IF(ISNUMBER(SEARCH("Concurrent Care",F6)),0,0),I6+1)'
            )
            sheet.cell(6, 15).value = (
                '=SUM(IF(ISNUMBER(SEARCH("Concurrent Care",F6)),0,0),I6+3)'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("genuine IF", result["feedback"])

    def test_if_true_does_not_substitute_for_concurrent_search_condition(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(TRUE,I6+1,ISNUMBER(SEARCH("Concurrent Care",F6)))'
            )
            sheet.cell(6, 15).value = (
                '=IF(TRUE,I6+3,ISNUMBER(SEARCH("Concurrent Care",F6)))'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("genuine IF", result["feedback"])

    def test_concurrent_if_in_statically_dead_branch_does_not_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(TRUE,I6+1,IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+1,""))'
            )
            sheet.cell(6, 15).value = (
                '=IF(TRUE,I6+3,IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+3,""))'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("genuine IF", result["feedback"])

    def test_comparison_constant_cannot_hide_dead_qualifying_if(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(1=1,I6+1,IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+1,""))'
            )
            sheet.cell(6, 15).value = (
                '=IF(1=1,I6+3,IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+3,""))'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Column J", result["feedback"])
            self.assertIn("Column O", result["feedback"])

    def test_not_true_cannot_hide_dead_qualifying_if(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(NOT(TRUE),IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+1,""),I6+1)'
            )
            sheet.cell(6, 15).value = (
                '=IF(NOT(TRUE),IF(ISNUMBER(SEARCH("Concurrent Care",F6)),I6+3,""),I6+3)'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Column J", result["feedback"])
            self.assertIn("Column O", result["feedback"])

    def test_offset_in_false_arm_does_not_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),"",I6+1)'
            )
            sheet.cell(6, 15).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),"",I6+3)'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("genuine IF", result["feedback"])

    def test_parenthesized_offset_extension_does_not_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),(I6+1)*10,"")'
            )
            sheet.cell(6, 15).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),((I6+3)*10),"")'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("genuine IF", result["feedback"])

    def test_harmless_balanced_parentheses_around_true_offset_pass(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 10).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),((I6+1)),"")'
            )
            sheet.cell(6, 15).value = (
                '=IF(ISNUMBER(SEARCH("Concurrent Care",F6)),(((I6+3))),"")'
            )

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CASE_FORMULAS)(workspace)
            self.assertTrue(result["pass"], result["feedback"])

    def test_exact_service_timestamp_passes(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: populate_case(sheet, 6)
        )
        with temporary:
            result = verifier(SERVICE_AND_TIME)(workspace)
            self.assertTrue(result["pass"], result["feedback"])
            self.assertIn("09:47:00", result["feedback"])

    def test_same_date_wrong_time_fails(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: populate_case(
                sheet, 6, timestamp=datetime(2026, 4, 14, 9, 48, 0)
            )
        )
        with temporary:
            result = verifier(SERVICE_AND_TIME)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("exact timestamp", result["feedback"])

    def test_core_fields_do_not_accept_substring_or_wrong_types(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 2).value = "member 44710006 extra"
            sheet.cell(6, 4).value = True

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(CORE_FIELDS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Member ID", result["feedback"])
            self.assertIn("Plan Year", result["feedback"])

    def test_routing_fields_are_type_aware_and_exact(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 16).value = "Ontario Province"
            sheet.cell(6, 17).value = "YES"

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(ROUTING)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Reviewer Assigned", result["feedback"])
            self.assertIn("Parity Flag", result["feedback"])

    def test_duplicate_case_rows_fail_regardless_of_row_order(self) -> None:
        for first_row, second_row in ((6, 9), (9, 6)):
            with self.subTest(first_row=first_row, second_row=second_row):
                def configure(sheet):
                    populate_case(sheet, first_row, use_full_formulas=True)
                    populate_case(sheet, second_row, use_full_formulas=True)

                temporary, workspace = self.make_workspace(configure)
                with temporary:
                    for rubric_id in CASE_BOUND_VERIFIERS:
                        result = verifier(rubric_id)(workspace)
                        self.assertFalse(result["pass"], (rubric_id, result))
                        self.assertIn("Duplicate rows", result["feedback"])

    def test_uncached_formula_does_not_count_as_blank_case_field(self) -> None:
        def configure(sheet):
            populate_case(sheet, 6)
            sheet.cell(6, 11).value = '=IF(A6="","","")'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(BLANK_FIELDS)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("Acknowledgment Sent", result["feedback"])

    def test_no_rows_after_8_passes_when_truly_empty(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: sheet.cell(8, 1, "CASE-2026-00478")
        )
        with temporary:
            result = verifier(NO_ROWS_AFTER_8)(workspace)
            self.assertTrue(result["pass"], result["feedback"])

    def test_uncached_formula_after_row_8_is_allowed(self) -> None:
        def configure(sheet):
            sheet.cell(8, 1).value = "CASE-2026-00478"
            sheet.cell(9, 10).value = '=IF(A9="","",I9+1)'

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(NO_ROWS_AFTER_8)(workspace)
            self.assertTrue(result["pass"], result["feedback"])

    def test_static_zero_after_row_8_is_detected(self) -> None:
        def configure(sheet):
            sheet.cell(8, 1).value = "CASE-2026-00478"
            sheet.cell(9, 10).value = 0

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(NO_ROWS_AFTER_8)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("(9,", result["feedback"])

    def test_decision_due_sort_order_accepts_ascending_records(self) -> None:
        def configure(sheet):
            sheet.cell(3, 1).value = "CASE-2026-00470"
            sheet.cell(3, 15).value = datetime(2026, 4, 16)
            sheet.cell(4, 1).value = "CASE-2026-00478"
            sheet.cell(4, 15).value = datetime(2026, 4, 17)

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(DECISION_DUE_SORT_ORDER)(workspace)
            self.assertTrue(result["pass"], result["feedback"])

    def test_decision_due_sort_order_rejects_descending_records(self) -> None:
        def configure(sheet):
            sheet.cell(3, 1).value = "CASE-2026-00478"
            sheet.cell(3, 15).value = datetime(2026, 4, 17)
            sheet.cell(4, 1).value = "CASE-2026-00470"
            sheet.cell(4, 15).value = datetime(2026, 4, 16)

        temporary, workspace = self.make_workspace(configure)
        with temporary:
            result = verifier(DECISION_DUE_SORT_ORDER)(workspace)
            self.assertFalse(result["pass"])
            self.assertIn("not sorted", result["feedback"])

    def test_malformed_workbook_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "appeals_log_master.xlsx").write_bytes(b"not an xlsx")
            for rubric_id in WORKBOOK_VERIFIERS:
                with self.subTest(rubric_id=rubric_id):
                    result = verifier(rubric_id)(workspace)
                    self.assertFalse(result["pass"])
                    self.assertIn("Could not open", result["feedback"])

    def test_root_and_nested_duplicate_workbooks_fail_all_workbook_verifiers(self) -> None:
        temporary, workspace = self.make_workspace(
            lambda sheet: populate_case(sheet, 6, use_full_formulas=True)
        )
        with temporary:
            nested = workspace / "nested"
            nested.mkdir()
            source = workspace / "appeals_log_master.xlsx"
            (nested / "appeals_log_master.xlsx").write_bytes(source.read_bytes())
            for rubric_id in WORKBOOK_VERIFIERS:
                with self.subTest(rubric_id=rubric_id):
                    result = verifier(rubric_id)(workspace)
                    self.assertFalse(result["pass"], result)
                    self.assertIn(
                        "Expected one appeals_log_master.xlsx, found 2",
                        result["feedback"],
                    )


if __name__ == "__main__":
    unittest.main()
