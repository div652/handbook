#!/usr/bin/env python3
"""Focused regressions for evaluator defects confirmed by the task RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


ACKNOWLEDGEMENT_RUBRIC_ID = "34e9fc4f-f5e5-498e-b47b-e2c5b7b54160"
SUMMARY_RUBRIC_ID = "7af6ba73-68f9-49ae-a05e-d232eab00f1d"
OPEN_NCR_RUBRIC_ID = "269a994f-7bf0-44ef-b6d8-3819fcb11965"
RUBRICS_PATH = Path(__file__).with_name("rubrics.json")
RUBRICS = {item["id"]: item for item in json.loads(RUBRICS_PATH.read_text())}


def run_verifier(
    workspace: Path,
    rubric_id: str = ACKNOWLEDGEMENT_RUBRIC_ID,
) -> dict:
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"](str(workspace))


def write_receiving_log(workspace: Path, ad9_note: str) -> None:
    workbook = openpyxl.Workbook()
    workbook.active["AD9"] = ad9_note
    workbook.save(workspace / "receiving_log.xlsx")
    workbook.close()


def write_handoff(workspace: Path, handoff_post: str) -> None:
    slack_data = {
        "channels": {"C-RECEIVING": {"name": "receiving-dock"}},
        "messages": {"C-RECEIVING": [{"text": handoff_post}]},
    }
    (workspace / "slack_data.json").write_text(
        json.dumps(slack_data),
        encoding="utf-8",
    )


def complete_handoff(ncr_metric: str, open_ncr_lines: str) -> str:
    return f"""END-OF-SHIFT HANDOFF 04/14/2026 — SM
Receipts completed today: 4
Receipts open at handoff: 3
{ncr_metric}
Quarantines applied today: 3
Escalations open: 2

OPEN NCRs:
{open_ncr_lines}
OPEN ESCALATIONS:
- REC-20260414-005
- REC-20260414-007
"""


class ElizabethAcknowledgementRegressionTests(unittest.TestCase):
    def verify_note(self, note: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_receiving_log(workspace, note)
            return run_verifier(workspace)

    def test_awaiting_elizabeth_acknowledgement_passes(self) -> None:
        result = self.verify_note(
            "Escalation awaiting Elizabeth acknowledgement since 12:35 CST."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_awaiting_elizabeth_velasquez_acknowledgment_passes(self) -> None:
        result = self.verify_note(
            "Escalation awaiting Elizabeth Velasquez acknowledgment since 12:35 CST."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_existing_awaiting_acknowledgement_form_still_passes(self) -> None:
        result = self.verify_note(
            "Elizabeth is the escalation owner; awaiting acknowledgement since 12:35 CST."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_non_negated_acknowledgement_controls_fail(self) -> None:
        controls = (
            "Elizabeth acknowledged the escalation at 12:35 CST.",
            "Elizabeth Velasquez acknowledgement received at 12:35 CST.",
            "Escalation awaiting regional Elizabeth acknowledgement since 12:35 CST.",
        )
        for note in controls:
            with self.subTest(note=note):
                result = self.verify_note(note)
                self.assertFalse(result["pass"], result["feedback"])

    def test_elizabeth_presence_remains_required(self) -> None:
        result = self.verify_note(
            "Escalation awaiting Walter Finch acknowledgement since 12:35 CST."
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("does not mention Elizabeth", result["feedback"])


class OpenNcrCoordinatorActionRegressionTests(unittest.TestCase):
    def verify_open_ncrs(self, open_ncr_lines: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_handoff(
                workspace,
                complete_handoff(
                    "NCRs issued today: 3 (1 Major, 2 Critical)",
                    open_ncr_lines,
                ),
            )
            return run_verifier(workspace, OPEN_NCR_RUBRIC_ID)

    def test_required_0252_without_optional_0253_passes(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0252 — draft supplier letter; awaiting Theo approval."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_0253_missing_heat_number_supplement_passes(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0252 — draft supplier letter; awaiting Theo approval.\n"
            "- NCR-MER-2026-0253 — Supplemental action: add the missing heat "
            "number H-6203-D to the supplier letter."
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_0253_without_supplemental_action_fails(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0252 — draft supplier letter; awaiting Theo approval.\n"
            "- NCR-0253 — supplier letter sent; await supplier response."
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("permitted only", result["feedback"])

    def test_0253_cannot_borrow_heat_action_from_0252_record(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0253 — supplier letter sent; await supplier response.\n"
            "- NCR-0252 — add the missing heat number to the supplier letter."
        )
        self.assertFalse(result["pass"], result["feedback"])

    def test_negated_0253_action_fails_despite_matching_terms(self) -> None:
        controls = (
            "No supplemental action is needed; the missing heat number was "
            "already included in the supplier letter.",
            "The supplier letter already includes the missing heat number; "
            "no supplement needed.",
        )
        for action in controls:
            with self.subTest(action=action):
                result = self.verify_open_ncrs(
                    "- NCR-0252 — draft supplier letter; awaiting Theo approval.\n"
                    f"- NCR-0253 — {action}"
                )
                self.assertFalse(result["pass"], result["feedback"])

    def test_supplier_waiting_0251_remains_excluded(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0252 — draft supplier letter; awaiting Theo approval.\n"
            "- NCR-0251 — waiting for supplier MTR."
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("must be excluded", result["feedback"])

    def test_0252_remains_required(self) -> None:
        result = self.verify_open_ncrs(
            "- NCR-0253 — Add the missing heat number to the supplier letter."
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("NCR-0252 is required", result["feedback"])


class NcrSummaryCountRegressionTests(unittest.TestCase):
    def verify_metric(self, ncr_metric: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_handoff(
                workspace,
                complete_handoff(
                    ncr_metric,
                    "- NCR-0252 — draft supplier letter; awaiting Theo approval.",
                ),
            )
            return run_verifier(workspace, SUMMARY_RUBRIC_ID)

    def test_aggregate_severity_counts_pass(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major, 2 Critical)"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_sent_and_draft_decomposition_passes(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major, 1 Critical sent, "
            "1 Critical draft)"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_aggregate_with_state_subcounts_passes(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major, 2 Critical (1 sent, 1 draft))"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_wrong_total_fails(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 4 (1 Major, 2 Critical)"
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("expected 3", result["feedback"])

    def test_wrong_severity_breakdown_fails(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (2 Major, 1 Critical)"
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("severity counts", result["feedback"])

    def test_wrong_decomposed_count_fails(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major, 1 Critical sent, 2 Critical draft)"
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("severity counts", result["feedback"])

    def test_aggregate_critical_state_word_does_not_affect_count(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major sent, 2 Critical sent)"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_unknown_state_word_does_not_affect_count(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major sent, 2 Critical closed)"
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_severity_prose_outside_metric_cannot_supply_missing_count(self) -> None:
        result = self.verify_metric(
            "NCRs issued today: 3 (1 Major, 1 Critical sent)\n"
            "NOTES FOR TOMORROW: 1 Critical draft remains open"
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("severity counts", result["feedback"])


if __name__ == "__main__":
    unittest.main()
