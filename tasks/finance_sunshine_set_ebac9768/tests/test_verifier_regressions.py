#!/usr/bin/env python3
"""Focused regressions for the task's deterministic evaluator corrections."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
SOURCE_SEED_DIR = TESTS_DIR.parent / "environment" / "initial_workspace"
SEED_DIR = SOURCE_SEED_DIR if SOURCE_SEED_DIR.is_dir() else Path("/workdir")
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

CHARGEBACK_ID = "85818af8-97bc-43ce-b0fa-73f28f4b0d14"
FUNDING_ID = "f13ab2dc-c8e0-46a8-82c2-55a8260985a0"
PAYOFF_RECIPIENT_ID = "5f7864cf-94ef-4aed-98b4-a7a800441cd8"
FLOORPLAN_ID = "f2e67592-99fe-4331-8b74-e17ec48e4f4f"
MARCUS_ROUTING_ID = "d27c5190-f9cd-44a0-b523-1fd1de0af51c"
PAYOFF_GROSS_ID = "c2p1-gross-recalc-01"
PAYOFF_RECALC_ID = "c2p1-recalc-skipped-01"
CASH_ID = "new_cash_elena_monthend"
WORKBOOK_PRESERVATION_ID = "source-workbooks-preserved-01"

QI3_IDS = (
    CHARGEBACK_ID,
    FUNDING_ID,
    PAYOFF_RECIPIENT_ID,
    FLOORPLAN_ID,
    MARCUS_ROUTING_ID,
    PAYOFF_GROSS_ID,
    PAYOFF_RECALC_ID,
)

PRIYA = "priya.bennett@sunshineauto.com"
ELENA = "elena.brooks@sunshineauto.com"


def run_verifier(
    rubric_id: str, workspace: Path, services: Path | None = None
) -> dict:
    namespace = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"](
        str(workspace), str(services) if services is not None else None
    )


def sent_email(
    recipients: str,
    text: str,
    *,
    cc: str = "",
    subject: str = "Escalation",
) -> dict:
    return {
        "folder": "sent",
        "to_addr": recipients,
        "cc_addr": cc,
        "subject": subject,
        "body_text": text,
    }


def copy_seed_workbooks(workspace: Path) -> None:
    for seed in SEED_DIR.glob("*.xlsx"):
        shutil.copy2(seed, workspace / seed.name)


class WorkbookPreservationRegressionTests(unittest.TestCase):
    def run_workspace(self, mutate=None) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            copy_seed_workbooks(workspace)
            if mutate is not None:
                mutate(workspace)
            return run_verifier(WORKBOOK_PRESERVATION_ID, workspace)

    def test_seeded_workbooks_pass_after_metadata_changing_reserialization(self) -> None:
        def reserialize(workspace: Path) -> None:
            for path in workspace.glob("*.xlsx"):
                workbook = load_workbook(path, data_only=False)
                workbook.properties.creator = "metadata-only regression"
                workbook.properties.modified = None
                workbook.save(path)

        result = self.run_workspace(reserialize)
        self.assertTrue(result["pass"], result["feedback"])

    def test_missing_renamed_or_modified_seed_workbook_fails(self) -> None:
        def missing(workspace: Path) -> None:
            (workspace / "funding_tracker.xlsx").unlink()

        def renamed(workspace: Path) -> None:
            (workspace / "deal_log.xlsx").rename(workspace / "deal_log_original.xlsx")

        def modified(workspace: Path) -> None:
            path = workspace / "floorplan_worksheet.xlsx"
            workbook = load_workbook(path, data_only=False)
            workbook["Floorplan"]["F2"] = 999
            workbook.save(path)

        for label, mutation in (
            ("missing", missing),
            ("renamed", renamed),
            ("modified", modified),
        ):
            with self.subTest(label=label):
                result = self.run_workspace(mutation)
                self.assertFalse(result["pass"], result["feedback"])

    def test_sop_logging_edits_are_allowed(self) -> None:
        def append_chargeback_row(workspace: Path) -> None:
            path = workspace / "chargeback_tracker.xlsx"
            workbook = load_workbook(path, data_only=False)
            sheet = workbook["Chargebacks"]
            sheet.append(["CB-2701", "SL-2026-0412", "Johnson", "SafeGuard Warranty", "VSC", 2800])
            workbook.save(path)

        def fill_blank_note_cell(workspace: Path) -> None:
            path = workspace / "funding_tracker.xlsx"
            workbook = load_workbook(path, data_only=False)
            sheet = workbook["Funding"]
            sheet.cell(row=2, column=sheet.max_column + 1).value = "Escalated to Elena Brooks (6 days unfunded)"
            workbook.save(path)

        for label, mutation in (
            ("appended row", append_chargeback_row),
            ("filled blank cell", fill_blank_note_cell),
        ):
            with self.subTest(label=label):
                result = self.run_workspace(mutation)
                self.assertTrue(result["pass"], result["feedback"])

    def test_clearing_a_seeded_cell_fails(self) -> None:
        def clear_seeded_cell(workspace: Path) -> None:
            path = workspace / "deal_log.xlsx"
            workbook = load_workbook(path, data_only=False)
            workbook["Deal Log"]["B2"] = None
            workbook.save(path)

        result = self.run_workspace(clear_seeded_cell)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("seeded cell values changed", result["feedback"])


class ServiceEvidenceRegressionTests(unittest.TestCase):
    def test_qi3_verifiers_fail_without_service_path_or_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()

            for rubric_id in QI3_IDS:
                with self.subTest(rubric_id=rubric_id, state="no service path"):
                    self.assertFalse(run_verifier(rubric_id, workspace)["pass"])
                with self.subTest(rubric_id=rubric_id, state="no service files"):
                    self.assertFalse(
                        run_verifier(rubric_id, workspace, services)["pass"]
                    )

    def test_readable_empty_mailbox_is_valid_negative_routing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps({"emails": []}))

            result = run_verifier(MARCUS_ROUTING_ID, workspace, services)
            self.assertTrue(result["pass"], result["feedback"])

    def test_missing_qualifying_payoff_email_fails_recalc_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text(
                json.dumps(
                    {
                        "emails": [
                            sent_email(
                                ELENA,
                                "Floorplan update with gross figures 2,910 and 4,710.",
                            )
                        ]
                    }
                )
            )

            result = run_verifier(PAYOFF_RECALC_ID, workspace, services)
            self.assertFalse(result["pass"], result["feedback"])


class JointPayoffRecipientRegressionTests(unittest.TestCase):
    def run_mailbox(self, rubric_id: str, emails: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps({"emails": emails}))
            return run_verifier(rubric_id, workspace, services)

    def test_payoff_recipient_check_rejects_separate_emails(self) -> None:
        text = (
            "Trade payoff variance $290. Original total gross $5,000; "
            "recalculated front gross $2,910; recalculated total gross $4,710; "
            "tier $51-$500."
        )
        emails = [
            sent_email(PRIYA, text),
            sent_email(ELENA, text),
        ]
        result = self.run_mailbox(PAYOFF_RECIPIENT_ID, emails)
        self.assertFalse(result["pass"], result["feedback"])

        joint = sent_email(PRIYA, text, cc=ELENA)
        result = self.run_mailbox(PAYOFF_RECIPIENT_ID, [joint])
        self.assertTrue(result["pass"], result["feedback"])

    def test_gross_check_requires_both_recipients_on_figure_email(self) -> None:
        text = "Trade payoff gross: original $5,000; recalculated $4,710; tier $51-$500."
        separate = [sent_email(PRIYA, text), sent_email(ELENA, text)]
        result = self.run_mailbox(PAYOFF_GROSS_ID, separate)
        self.assertFalse(result["pass"], result["feedback"])

        result = self.run_mailbox(
            PAYOFF_GROSS_ID,
            [sent_email(PRIYA, text, cc=ELENA)],
        )
        self.assertTrue(result["pass"], result["feedback"])


class CoupledEmailContentRegressionTests(unittest.TestCase):
    def run_mailbox(self, rubric_id: str, emails: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps({"emails": emails}))
            return run_verifier(rubric_id, workspace, services)

    def test_cash_email_requires_amount_and_topic_in_same_elena_email(self) -> None:
        failing_cases = (
            [sent_email(ELENA, "Unrelated discrepancy under review.")],
            [sent_email(ELENA, "The amount is $180.00.")],
            [sent_email(ELENA, "Cash shortage under review.")],
            [sent_email(ELENA, "Cash discrepancy is $1,180.00.")],
            [sent_email(ELENA, "Cash discrepancy is $180.50.")],
            [
                sent_email(ELENA, "The amount is $180.00."),
                sent_email(ELENA, "Cash shortage under review."),
            ],
        )
        for emails in failing_cases:
            with self.subTest(emails=emails):
                result = self.run_mailbox(CASH_ID, emails)
                self.assertFalse(result["pass"], result["feedback"])

        result = self.run_mailbox(
            CASH_ID,
            [sent_email(ELENA, "Cash deposit shortage is $ 180.00.")],
        )
        self.assertTrue(result["pass"], result["feedback"])

    def test_chargeback_email_requires_exact_deal_and_topic_together(self) -> None:
        failing_cases = (
            [sent_email(ELENA, "Chargeback requires review.")],
            [sent_email(ELENA, "Deal SL-2026-0412 requires review.")],
            [sent_email(ELENA, "Chargeback on deal SL20260412 requires review.")],
            [
                sent_email(ELENA, "Chargeback requires review."),
                sent_email(ELENA, "Deal SL-2026-0412 requires review."),
            ],
        )
        for emails in failing_cases:
            with self.subTest(emails=emails):
                result = self.run_mailbox(CHARGEBACK_ID, emails)
                self.assertFalse(result["pass"], result["feedback"])

        result = self.run_mailbox(
            CHARGEBACK_ID,
            [sent_email(ELENA, "Chargeback for deal SL-2026-0412 requires review.")],
        )
        self.assertTrue(result["pass"], result["feedback"])


class LenderFieldRegressionTests(unittest.TestCase):
    FUNDING_TEXT = (
        "Wells Fargo funding escalation for Deal SL-2026-0412. "
        "Deadline: EOD April 14, 2026. Missing stipulations: original notarized "
        "Power of Attorney and payoff letter showing the account number and "
        "good-through date."
    )
    PAYOFF_TEXT = (
        "Trade payoff variance $290. Original total gross $5,000; recalculated "
        "front gross $2,910; recalculated total gross $4,710; tier $51-$500."
    )
    MTTYARQ_FUNDING_TEXT = (
        "Deal #SL-2026-0412 is pending with Wells Fargo. Wells Fargo's April 13 "
        "notice requires the following by end of business today, April 14:\n"
        "1. Original, notarized Power of Attorney\n"
        "2. Payoff letter from the prior lienholder showing the account number "
        "and good-through date."
    )

    def run_mailbox(self, rubric_id: str, emails: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps({"emails": emails}))
            return run_verifier(rubric_id, workspace, services)

    def test_funding_document_requires_all_exact_sop_fields_together(self) -> None:
        valid = sent_email(
            "noah.alvarez@sunshineauto.com",
            self.FUNDING_TEXT,
            cc=ELENA,
        )
        result = self.run_mailbox(FUNDING_ID, [valid])
        self.assertTrue(result["pass"], result["feedback"])

        invalid_texts = (
            self.FUNDING_TEXT.replace("Wells Fargo", "Bank of America"),
            self.FUNDING_TEXT.replace("SL-2026-0412", "SL-2026-0413"),
            self.FUNDING_TEXT.replace("April 14, 2026", "April 15, 2026"),
            self.FUNDING_TEXT.replace("original ", ""),
            self.FUNDING_TEXT.replace("notarized ", ""),
            self.FUNDING_TEXT.replace("Power of Attorney", "funding document"),
            self.FUNDING_TEXT.replace("payoff letter", "payoff details"),
            self.FUNDING_TEXT.replace("account number", "account details"),
            self.FUNDING_TEXT.replace("good-through date", "payoff details"),
        )
        for text in invalid_texts:
            with self.subTest(text=text):
                result = self.run_mailbox(
                    FUNDING_ID,
                    [
                        sent_email(
                            "noah.alvarez@sunshineauto.com",
                            text,
                            cc=ELENA,
                        )
                    ],
                )
                self.assertFalse(result["pass"], result["feedback"])

        split = [
            sent_email(
                "noah.alvarez@sunshineauto.com",
                "Wells Fargo funding for SL-2026-0412 is due EOD April 14, 2026.",
                cc=ELENA,
            ),
            sent_email(
                "noah.alvarez@sunshineauto.com",
                "Original notarized POA and payoff letter need account number and good-through date.",
                cc=ELENA,
            ),
        ]
        result = self.run_mailbox(FUNDING_ID, split)
        self.assertFalse(result["pass"], result["feedback"])

    def test_funding_deadline_accepts_fixed_date_and_exact_clock_forms(self) -> None:
        deadline_forms = (
            self.MTTYARQ_FUNDING_TEXT,
            self.FUNDING_TEXT.replace("EOD April 14, 2026", "EOD April 14"),
            self.FUNDING_TEXT.replace("EOD April 14, 2026", "5:00 PM ET"),
            self.FUNDING_TEXT.replace("EOD April 14, 2026", "deadline 17:00 EDT"),
            self.FUNDING_TEXT.replace(
                "Deadline: EOD April 14, 2026.",
                "Wells Fargo's notice is dated April 13, 2026. "
                "Submit by 5:00 PM ET.",
            ),
        )
        for text in deadline_forms:
            with self.subTest(text=text):
                result = self.run_mailbox(
                    FUNDING_ID,
                    [
                        sent_email(
                            "noah.alvarez@sunshineauto.com",
                            text,
                            cc=ELENA,
                        )
                    ],
                )
                self.assertTrue(result["pass"], result["feedback"])

        missing_other_field = self.MTTYARQ_FUNDING_TEXT.replace(
            "good-through date", "payoff details"
        )
        result = self.run_mailbox(
            FUNDING_ID,
            [
                sent_email(
                    "noah.alvarez@sunshineauto.com",
                    missing_other_field,
                    cc=ELENA,
                )
            ],
        )
        self.assertFalse(result["pass"], result["feedback"])

    def test_funding_deadline_rejects_wrong_dates_even_with_exact_clock(self) -> None:
        wrong_deadlines = (
            self.FUNDING_TEXT.replace("April 14, 2026", "April 15, 2026"),
            self.FUNDING_TEXT.replace("April 14, 2026", "April 14, 2027"),
            self.FUNDING_TEXT.replace(
                "EOD April 14, 2026",
                "deadline April 15, 2026 at 5:00 PM ET",
            ),
            self.FUNDING_TEXT.replace(
                "EOD April 14, 2026",
                "5:00 PM ET cutoff on 04/15/2026",
            ),
            self.FUNDING_TEXT.replace(
                "Deadline: EOD April 14, 2026.",
                "Deadline is April 15, 2026. Submit by 5:00 PM ET.",
            ),
            self.FUNDING_TEXT.replace(
                "Deadline: EOD April 14, 2026.",
                "Deadline is 04/15/2026; submit by 17:00 EDT.",
            ),
        )
        for text in wrong_deadlines:
            with self.subTest(text=text):
                result = self.run_mailbox(
                    FUNDING_ID,
                    [
                        sent_email(
                            "noah.alvarez@sunshineauto.com",
                            text,
                            cc=ELENA,
                        )
                    ],
                )
                self.assertFalse(result["pass"], result["feedback"])

    def test_funding_fields_accept_one_joint_assistant_slack_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            services = Path(tmp) / "services"
            workspace.mkdir()
            services.mkdir()
            slack = {
                "workspaces": {
                    "default": {
                        "users": {
                            "B1": {"is_bot": True, "profile": {}},
                            "U1": {"profile": {"email": "noah.alvarez@sunshineauto.com"}},
                            "U2": {"profile": {"email": ELENA}},
                        },
                        "channels": {"C1": {"members": ["U1", "U2"]}},
                        "messages": {"C1": [{"user": "B1", "text": self.FUNDING_TEXT}]},
                    }
                }
            }
            (services / "slack.json").write_text(json.dumps(slack))
            result = run_verifier(FUNDING_ID, workspace, services)
            self.assertTrue(result["pass"], result["feedback"])

    def test_payoff_document_requires_each_exact_value_in_one_email(self) -> None:
        valid = sent_email(PRIYA, self.PAYOFF_TEXT, cc=ELENA)
        result = self.run_mailbox(PAYOFF_RECIPIENT_ID, [valid])
        self.assertTrue(result["pass"], result["feedback"])

        deliberately_unbound = sent_email(
            PRIYA,
            (
                "Trade payoff variance $290. Required figures present: $5,000, "
                "$2,910, and $4,710. Applicable tier: $51-$500."
            ),
            cc=ELENA,
        )
        result = self.run_mailbox(PAYOFF_RECIPIENT_ID, [deliberately_unbound])
        self.assertTrue(result["pass"], result["feedback"])

        invalid_texts = (
            self.PAYOFF_TEXT.replace("$2,910", "$2,900"),
            self.PAYOFF_TEXT.replace("$4,710", "$4,700"),
            self.PAYOFF_TEXT.replace("$51-$500", "$51-$600"),
            (
                "Trade payoff variance $1,290. Original total gross $15,000; "
                "front gross $12,910; total gross $14,710; tier $151-$500."
            ),
        )
        for text in invalid_texts:
            with self.subTest(text=text):
                result = self.run_mailbox(
                    PAYOFF_RECIPIENT_ID,
                    [sent_email(PRIYA, text, cc=ELENA)],
                )
                self.assertFalse(result["pass"], result["feedback"])

        split = [
            sent_email(
                PRIYA,
                "Trade payoff variance $290; original total gross $5,000; tier $51-$500.",
                cc=ELENA,
            ),
            sent_email(
                PRIYA,
                "Trade payoff recalculation gives $2,910 and $4,710.",
                cc=ELENA,
            ),
        ]
        result = self.run_mailbox(PAYOFF_RECIPIENT_ID, split)
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
