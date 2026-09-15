#!/usr/bin/env python3
"""Focused regression coverage for the Whitfield invoice folder verifier."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


CRITERION_ID = "e1811786-91b9-483d-b2f4-06dab61c2cef"
TESTS_DIR = Path(__file__).resolve().parent
WCG_FILENAME = "INV-V-00038-WCG-2025-0087.pdf"


def load_verifier():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


def run_verifier(relative_path: str | None) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        if relative_path is not None:
            target = workspace / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.4\n")
        return load_verifier()(str(workspace), None)


class WhitfieldInvoiceFolderTests(unittest.TestCase):
    def test_receipt_month_folder_passes(self) -> None:
        result = run_verifier(f"Invoices/2025-09/{WCG_FILENAME}")
        self.assertTrue(result["pass"], result["feedback"])

    def test_invoice_date_month_folder_passes(self) -> None:
        result = run_verifier(f"Invoices/2025-08/{WCG_FILENAME}")
        self.assertTrue(result["pass"], result["feedback"])

    def test_root_level_file_fails(self) -> None:
        result = run_verifier(WCG_FILENAME)
        self.assertFalse(result["pass"], result["feedback"])

    def test_unrelated_month_folder_fails(self) -> None:
        result = run_verifier(f"Invoices/2025-10/{WCG_FILENAME}")
        self.assertFalse(result["pass"], result["feedback"])

    def test_other_invoice_in_accepted_folder_fails(self) -> None:
        result = run_verifier("Invoices/2025-09/INV-V-00039-HC-2025-0001.pdf")
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
