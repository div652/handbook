#!/usr/bin/env python3
"""Focused regressions for verifier defects identified by the comprehensive RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl


RUBRICS_PATH = Path(__file__).with_name("rubrics.json")
RUBRICS = {rubric["id"]: rubric for rubric in json.loads(RUBRICS_PATH.read_text())}


def run_verifier(rubric_id: str, workspace: Path, services: Path | None = None) -> dict:
    namespace = {"__builtins__": __builtins__}
    exec(compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"](str(workspace), str(services) if services else None)


class VerifierRegressionTests(unittest.TestCase):
    def test_kunlun_invoice_number_is_required_in_subject_not_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            body = "Your $6,019.44 invoice is pending internal approval. Allow 5 additional business days."
            mailbox = {
                "emails": [{
                    "folder": "sent",
                    "to_addr": "greg.kendrick@kunluncreativestudio.com",
                    "subject": "Status for INV-KC-20260305",
                    "body_text": body,
                }]
            }
            (services / "mailbox.json").write_text(json.dumps(mailbox))
            self.assertTrue(run_verifier("6e8e36a8-e868-4af4-bc06-8cb2578ea253", root, services)["pass"])

            mailbox["emails"][0]["subject"] = "Status update"
            (services / "mailbox.json").write_text(json.dumps(mailbox))
            self.assertFalse(run_verifier("6e8e36a8-e868-4af4-bc06-8cb2578ea253", root, services)["pass"])

    def test_sentinel_requires_exact_amount_and_no_po(self) -> None:
        headers = ["Vendor / Payee", "Invoice #", "Invoice Date", "Due Date", "Amount ($)", "GL Account", "PO Number", "Status"]
        valid = ["Sentinel Cybersecurity Solutions", "INV-4839201-24", datetime(2026, 3, 16), datetime(2026, 4, 15), 13837, "6400-010-1100", "—", "Approved"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Payment Queue"
            ws.append(headers)
            ws.append(valid)
            wb.save(root / "ap_ledger.xlsx")
            rubric_id = "76697ce7-241c-48a7-87d2-57eb944b78aa"
            self.assertTrue(run_verifier(rubric_id, root)["pass"])

            ws.cell(2, 5).value = 13836
            wb.save(root / "ap_ledger.xlsx")
            self.assertFalse(run_verifier(rubric_id, root)["pass"])

            ws.cell(2, 5).value = 13837
            ws.cell(2, 7).value = "PO-UNSUPPORTED"
            wb.save(root / "ap_ledger.xlsx")
            self.assertFalse(run_verifier(rubric_id, root)["pass"])

    def test_main_street_checks_exact_columns_and_accepts_variance_formula(self) -> None:
        headers = [
            "Match Date", "Vendor / Payee", "PO Number", "PO Amount ($)", "GR Number", "GR Date",
            "Invoice Number", "Invoice Date", "Invoice Amount ($)", "GL Account", "PO Variance ($)", "Status",
        ]
        row = [
            datetime(2026, 3, 16), "Main Street Office Products", "PO-2026-00532", 1276.14,
            "GR-20260311-004", datetime(2026, 3, 11), "INV-004322", datetime(2026, 3, 16),
            1356.14, "6200-000-5100", "=I2-D2", "Approved",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "3-Way Match Log"
            ws.append(headers)
            ws.append(row)
            wb.save(root / "match_log_2026_Q1.xlsx")
            rubric_id = "6929234d-ab72-4732-90bb-865f606bf268"
            self.assertTrue(run_verifier(rubric_id, root)["pass"])

            ws.cell(2, 8).value = datetime(2026, 3, 15)
            wb.save(root / "match_log_2026_Q1.xlsx")
            self.assertFalse(run_verifier(rubric_id, root)["pass"])

            ws.cell(2, 8).value = datetime(2026, 3, 16)
            ws.cell(2, 4).value = 1277.00
            wb.save(root / "match_log_2026_Q1.xlsx")
            self.assertFalse(run_verifier(rubric_id, root)["pass"])

    def test_negative_email_requires_readable_mailbox_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            rubric_id = "rubric_1775678154191"
            self.assertFalse(run_verifier(rubric_id, root, services)["pass"])
            (services / "mailbox.json").write_text("not-json")
            self.assertFalse(run_verifier(rubric_id, root, services)["pass"])
            (services / "mailbox.json").write_text(json.dumps({"emails": []}))
            self.assertTrue(run_verifier(rubric_id, root, services)["pass"])

    def test_payment_queue_ignores_footer_but_rejects_extra_vendor_row(self) -> None:
        expected = [
            "Deloitte Consulting LLP", "Jones Day LLP", "Workday Inc", "225 Wacker LLC",
            "Aramark Workplace Services", "Iron Mountain Inc", "Sentinel Cybersecurity Solutions",
            "Main Street Office Products",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Payment Queue"
            ws.append(["Vendor / Payee", "Invoice #"])
            for index, vendor in enumerate(expected, start=1):
                ws.append([vendor, f"INV-{index}"])
            ws.append(["TOTAL PAYMENT QUEUE", None])
            wb.save(root / "ap_ledger.xlsx")
            rubric_id = "rubric_1775678196872"
            self.assertTrue(run_verifier(rubric_id, root)["pass"])

            # A populated vendor is still a genuine queue row when its invoice
            # cell is blank; only the recognized total/footer above is ignored.
            ws.append(["Luminary Logistics", None])
            wb.save(root / "ap_ledger.xlsx")
            result = run_verifier(rubric_id, root)
            self.assertFalse(result["pass"])
            self.assertIn("luminary logistics", result["feedback"].lower())


if __name__ == "__main__":
    unittest.main()
