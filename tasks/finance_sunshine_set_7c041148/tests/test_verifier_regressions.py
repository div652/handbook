#!/usr/bin/env python3
"""Focused regressions for evaluator defects identified by the comprehensive RCA."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path


RUBRICS_PATH = Path(__file__).with_name("rubrics.json")
RUBRICS = {rubric["id"]: rubric for rubric in json.loads(RUBRICS_PATH.read_text())}

ATTACHMENT_ID = "c74f7f2a-95ff-458c-9a03-8943860fcaef"
DEAL_LOG_IDS = (
    "25622b64-4ad0-41ae-9ed5-54e0a58e4fb2",
    "c9d032ac-b740-4c98-9ff4-97622e136a16",
    "d483f22b-bd8b-4ae3-b44d-e2acd7d831b9",
)
ORTIZ_REPLY_ID = "d0da5a96-d087-48a7-9d36-6da54673deb9"


def load_namespace(rubric_id: str) -> dict:
    namespace = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace


def run_verifier(rubric_id: str, workspace: Path, services: Path | None = None) -> dict:
    namespace = load_namespace(rubric_id)
    return namespace["verify"](
        str(workspace), str(services) if services is not None else None
    )


def encoded_attachment(filename: str, content: str) -> dict:
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content.encode()).decode(),
    }


def binary_attachment(filename: str, content: bytes) -> dict:
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
    }


def flores_email(attachments: list[dict]) -> dict:
    return {
        "folder": "sent",
        "to_addr": "derek.loomis@sunshineandsetauto.com",
        "subject": "Deal Gross Variance — Deal #10057 / Flores",
        "body_text": (
            "Deal #10057 — Flores, Stock #N16028, VIN ending 342FK. "
            "Approved gross: $7,500. Posted gross: $6,700. Variance: $800. "
            "Source of difference: the desk recap included an accessory charge in error."
        ),
        "attachments": attachments,
    }


class DealLogSelectorRegressionTests(unittest.TestCase):
    def test_backups_cannot_shadow_mutated_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "deal_log.xlsx"
            source.touch()
            (root / "deal_log_backup_20270326.xlsx").touch()
            backup_dir = root / "backups"
            backup_dir.mkdir()
            (backup_dir / "deal_log_v99.xlsx").touch()

            for rubric_id in DEAL_LOG_IDS:
                selected, error = load_namespace(rubric_id)["_select_deal_log"](root)
                self.assertIsNone(error, rubric_id)
                self.assertEqual(selected, source, rubric_id)

    def test_highest_real_revision_wins_even_with_newer_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deal_log.xlsx").touch()
            final = root / "deal_log_v2.xlsx"
            final.touch()
            backup_dir = root / "archive"
            backup_dir.mkdir()
            (backup_dir / "deal_log_v100.xlsx").touch()

            for rubric_id in DEAL_LOG_IDS:
                selected, error = load_namespace(rubric_id)["_select_deal_log"](root)
                self.assertIsNone(error, rubric_id)
                self.assertEqual(selected, final, rubric_id)

    def test_backup_only_workspace_has_no_final_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deal_log_backup.xlsx").touch()

            for rubric_id in DEAL_LOG_IDS:
                selected, error = load_namespace(rubric_id)["_select_deal_log"](root)
                self.assertIsNone(selected, rubric_id)
                self.assertIn("Only stale/decoy/backup", error, rubric_id)

    def test_compact_and_camel_case_deal_log_names_are_accepted(self) -> None:
        for filename in ("DealLogFinal.xlsx", "deallog_v2.xlsm"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                expected = root / filename
                expected.touch()

                for rubric_id in DEAL_LOG_IDS:
                    selected, error = load_namespace(rubric_id)["_select_deal_log"](
                        root
                    )
                    self.assertIsNone(error, rubric_id)
                    self.assertEqual(selected, expected, rubric_id)

    def test_stale_and_decoy_suffixes_and_ancestors_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "DealLogFinal.xlsx"
            final.touch()
            (root / "DealLogStale.xlsx").touch()
            (root / "deal_log_decoy_v99.xlsx").touch()
            stale_dir = root / "StaleCopies"
            stale_dir.mkdir()
            (stale_dir / "DealLogV100.xlsx").touch()
            decoy_dir = root / "decoy"
            decoy_dir.mkdir()
            (decoy_dir / "deal_log_approved.xlsx").touch()

            for rubric_id in DEAL_LOG_IDS:
                selected, error = load_namespace(rubric_id)["_select_deal_log"](root)
                self.assertIsNone(error, rubric_id)
                self.assertEqual(selected, final, rubric_id)

    def test_final_and_approved_variants_remain_ambiguous(self) -> None:
        for creation_order in (
            ("DealLogFinal.xlsx", "deal_log_approved.xlsx"),
            ("deal_log_approved.xlsx", "DealLogFinal.xlsx"),
        ):
            with self.subTest(creation_order=creation_order), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for filename in creation_order:
                    (root / filename).touch()

                for rubric_id in DEAL_LOG_IDS:
                    selected, error = load_namespace(rubric_id)["_select_deal_log"](
                        root
                    )
                    self.assertIsNone(selected, rubric_id)
                    self.assertIn("Ambiguous deal-log revisions", error, rubric_id)


class AttachmentRegressionTests(unittest.TestCase):
    def run_mailbox(self, emails: object) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            (services / "mailbox.json").write_text(json.dumps({"emails": emails}))
            return run_verifier(ATTACHMENT_ID, root, services)

    def run_email(self, attachments: object) -> dict:
        email = flores_email([])
        email["attachments"] = attachments
        return self.run_mailbox([email])

    @staticmethod
    def valid_attachments(deal_log_name: str = "deal_log_excerpt_10057.csv") -> list[dict]:
        return [
            encoded_attachment("Flores_Buyers_Order.pdf", "Deal 10057"),
            encoded_attachment("Flores_Desk_Recap.pdf", "Deal 10057 gross 7500"),
            encoded_attachment(
                deal_log_name,
                "deal,posted total gross,notes\n"
                "10057,6700,desk recap discrepancy",
            ),
        ]

    def test_buyer_order_and_desk_recap_cannot_impersonate_deal_log(self) -> None:
        result = self.run_email(
            [
                encoded_attachment("Flores_Buyers_Order.pdf", "Deal 10057"),
                encoded_attachment(
                    "Flores_Desk_Recap.pdf", "Deal 10057 approved gross 7500"
                ),
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("deal log excerpt", result["feedback"])

    def test_deal_log_filename_without_discrepancy_content_fails(self) -> None:
        result = self.run_email(
            [
                encoded_attachment("Flores_Buyers_Order.pdf", "Deal 10057"),
                encoded_attachment("Flores_Desk_Recap.pdf", "Deal 10057 gross 7500"),
                encoded_attachment("deal_log_excerpt_10057.csv", "deal,total\n10057,7500"),
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("deal log excerpt", result["feedback"])

    def test_deal_and_posted_gross_cannot_be_flattened_across_rows(self) -> None:
        result = self.run_email(
            [
                encoded_attachment("Flores_Buyers_Order.pdf", "Deal 10057"),
                encoded_attachment("Flores_Desk_Recap.pdf", "Deal 10057 gross 7500"),
                encoded_attachment(
                    "DealLogExcerpt.csv",
                    "deal,posted total gross\n10057,7500\n10099,6700",
                ),
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("deal log excerpt", result["feedback"])

    def test_wrong_deal_record_fails(self) -> None:
        result = self.run_email(
            [
                encoded_attachment("Flores_Buyers_Order.pdf", "Deal 10057"),
                encoded_attachment("Flores_Desk_Recap.pdf", "Deal 10057 gross 7500"),
                encoded_attachment(
                    "DealLogExcerpt.csv",
                    "deal,posted total gross\n10099,6700",
                ),
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("deal log excerpt", result["feedback"])

    def test_6700_in_an_unlabeled_or_wrong_field_is_not_posted_gross(self) -> None:
        for content in (
            "10057,6700",
            "deal,approved gross\n10057,6700",
            "deal,posted gross,approved gross\n10057,7500,6700",
        ):
            with self.subTest(content=content):
                attachments = self.valid_attachments()
                attachments[2] = encoded_attachment("DealLogExcerpt.csv", content)
                result = self.run_email(attachments)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("deal log excerpt", result["feedback"])

    def test_compact_camel_case_deal_log_attachment_passes(self) -> None:
        result = self.run_email(self.valid_attachments("DealLogExcerpt10057.csv"))
        self.assertTrue(result["pass"], result["feedback"])

    def test_stale_or_decoy_deal_log_attachment_fails(self) -> None:
        for filename in (
            "DealLogExcerptStale.csv",
            "decoy/DealLogExcerpt10057.csv",
        ):
            with self.subTest(filename=filename):
                result = self.run_email(self.valid_attachments(filename))
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn("deal log excerpt", result["feedback"])

    def test_missing_attachment_filename_or_content_fails_closed(self) -> None:
        missing_filename = self.valid_attachments()
        missing_filename[0] = {
            "content_base64": base64.b64encode(b"Deal 10057").decode()
        }
        missing_content = self.valid_attachments()
        missing_content[1] = {"filename": "Flores_Desk_Recap.pdf"}

        for attachments, expected in (
            (missing_filename, "buyer's order"),
            (missing_content, "desk recap"),
        ):
            with self.subTest(expected=expected):
                result = self.run_email(attachments)
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn(expected, result["feedback"])

    def test_one_combined_attachment_cannot_fill_three_roles(self) -> None:
        result = self.run_email(
            [
                encoded_attachment(
                    "BuyersOrder_DeskRecap_DealLogExcerpt.csv",
                    "deal,posted total gross\n10057,6700",
                )
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("three distinct attachment objects", result["feedback"])

    def test_malformed_mailbox_and_attachment_collections_fail_closed(self) -> None:
        result = self.run_mailbox({"not": "a list"})
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("must be a list", result["feedback"])

        result = self.run_email({"not": "a list"})
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Attachment", result["feedback"])

    def test_duplicate_email_order_does_not_change_pass_result(self) -> None:
        valid = flores_email(self.valid_attachments())
        invalid = flores_email(self.valid_attachments())
        invalid["attachments"] = invalid["attachments"][:2]

        for emails in ([invalid, valid], [valid, invalid]):
            with self.subTest(valid_first=emails[0] is valid):
                result = self.run_mailbox(emails)
                self.assertTrue(result["pass"], result["feedback"])

    def test_recipient_substring_does_not_match_an_accepted_address(self) -> None:
        email = flores_email(self.valid_attachments())
        email["to_addr"] = "not-derek.loomis@sunshineandsetauto.com.example"
        result = self.run_mailbox([email])
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("exact accepted", result["feedback"])

    def test_negated_required_values_fail_before_positive_matching(self) -> None:
        email = flores_email(self.valid_attachments())
        email["body_text"] = email["body_text"].replace(
            "Posted gross: $6,700", "Posted gross was not $6,700"
        )
        result = self.run_mailbox([email])
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Posted gross", result["feedback"])

    def test_postposed_negation_of_posted_gross_fails(self) -> None:
        email = flores_email(self.valid_attachments())
        email["body_text"] = email["body_text"].replace(
            "Posted gross: $6,700", "Posted gross $6,700 is not correct"
        )
        result = self.run_mailbox([email])
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Posted gross", result["feedback"])

    def test_postposed_negation_of_source_evidence_fails(self) -> None:
        email = flores_email(self.valid_attachments())
        email["body_text"] = email["body_text"].replace(
            "the desk recap included an accessory charge in error",
            "desk recap error was not the cause",
        )
        result = self.run_mailbox([email])
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Source of difference", result["feedback"])

    def test_real_rca_buyer_and_recap_pdfs_do_not_impersonate_deal_log(self) -> None:
        workspace = Path(__file__).parents[1] / "environment" / "initial_workspace"
        buyer = workspace / "20261105_10057_Flores_Buyers_Order.pdf"
        recap = workspace / "20261105_10057_Flores_Desk_Recap.pdf"
        result = self.run_email(
            [
                binary_attachment(buyer.name, buyer.read_bytes()),
                binary_attachment(recap.name, recap.read_bytes()),
            ]
        )
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("deal log excerpt", result["feedback"])

    def test_real_deal_log_workbook_binds_10057_to_total_gross_6700(self) -> None:
        workspace = Path(__file__).parents[1] / "environment" / "initial_workspace"
        deal_log = workspace / "deal_log.xlsx"
        attachments = self.valid_attachments()
        attachments[2] = binary_attachment(
            "DealLogExcerpt.xlsx", deal_log.read_bytes()
        )
        result = self.run_email(attachments)
        self.assertTrue(result["pass"], result["feedback"])

    def test_real_rca_wrong_template_amounts_fail(self) -> None:
        email = flores_email(self.valid_attachments())
        email["body_text"] = email["body_text"].replace(
            "Approved gross: $7,500", "Approved gross: $6,704"
        ).replace("Variance: $800", "Variance: $4")
        result = self.run_mailbox([email])
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn("Approved gross", result["feedback"])
        self.assertIn("Variance", result["feedback"])

    def test_actual_deal_log_excerpt_passes(self) -> None:
        result = self.run_email(self.valid_attachments())
        self.assertTrue(result["pass"], result["feedback"])


class OrtizReplyRegressionTests(unittest.TestCase):
    def test_current_verifier_accepts_qualifying_retained_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            mailbox = {
                "emails": [
                    {
                        "folder": "inbox",
                        "from_addr": "marcus.bell@sunshineandsetauto.com",
                        "subject": "New Deal Jacket — Deal #10099",
                        "message_id": "bell-10099",
                    },
                    {
                        "folder": "sent",
                        "to_addr": "marcus.bell@sunshineandsetauto.com",
                        "subject": "Re: New Deal Jacket — Deal #10099",
                        "in_reply_to": "bell-10099",
                        "body_text": (
                            "Deal #10099 has a gross variance: the F&I recap is $8,224 "
                            "while the deal log is $8,220. Marcus Hale review is required. "
                            "Posting remains on hold and cannot proceed until resolved."
                        ),
                    },
                ]
            }
            (services / "mailbox.json").write_text(json.dumps(mailbox))
            result = run_verifier(ORTIZ_REPLY_ID, root, services)
            self.assertTrue(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
