#!/usr/bin/env python3
"""Regressions for the Sunshine GL surface and Deal 4462 follow-up guard."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
TASK_DIR = TESTS_DIR.parent
INITIAL_WORKSPACE = TASK_DIR / "environment" / "initial_workspace"
RUBRICS = json.loads((TESTS_DIR / "rubrics.json").read_text())


def namespace_for(rubric_id: str) -> dict:
    rubric = next(item for item in RUBRICS if item["id"] == rubric_id)
    namespace = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{rubric_id}>", "exec"), namespace)
    return namespace


LEDGER_HEADERS = [
    "Entry Date",
    "Journal ID",
    "Source Type",
    "Source Ref",
    "Deal #",
    "Customer Last",
    "GL Account",
    "Account Name",
    "Department Code",
    "Debit",
    "Credit",
    "Description",
    "Posted By",
    "Status",
]
VALID_LINES = [
    ["04/24/2026", "JE-2026-0424-08", "Chargeback", "CB-2608", 4451,
     "Castellano", "6250", "F&I Product Chargeback Expense", "200", 1600,
     None, "GAP cancellation chargeback", "Jasmine Patel", "Posted"],
    ["04/24/2026", "JE-2026-0424-08", "Chargeback", "CB-2608", 4451,
     "Castellano", "2155", "Product Chargeback Clearing", "200", None,
     1600, "GAP cancellation chargeback", "Jasmine Patel", "Posted"],
]


class FakeSheet:
    title = "General Ledger"

    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, values_only=False):
        assert values_only
        return iter(self.rows)


class FakeWorkbook:
    def __init__(self, rows):
        self.worksheets = [FakeSheet(rows)]

    def close(self):
        pass


def run_gl(rows):
    namespace = namespace_for("rubric_s4_gl_posting")
    namespace["load_workbook"] = lambda *_args, **_kwargs: FakeWorkbook(rows)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copy2(INITIAL_WORKSPACE / "general_ledger.xlsx", root / "general_ledger.xlsx")
        shutil.copy2(
            INITIAL_WORKSPACE / "Chart_of_Accounts_and_Department_Coding_Guide.xlsx",
            root / "Chart_of_Accounts_and_Department_Coding_Guide.xlsx",
        )
        (root / "general_ledger_v2.xlsx").touch()
        return namespace["verify"](root)


class GeneralLedgerVerifierTests(unittest.TestCase):
    def test_balanced_authoritative_chargeback_posting_passes(self):
        result = run_gl([LEDGER_HEADERS, *VALID_LINES])

        self.assertTrue(result["pass"], result["feedback"])

    def test_unbalanced_or_wrongly_coded_posting_fails(self):
        invalid = [list(row) for row in VALID_LINES]
        invalid[1][10] = 1500

        result = run_gl([LEDGER_HEADERS, *invalid])

        self.assertFalse(result["pass"])
        self.assertIn("incomplete or incorrectly coded", result["feedback"])


class Deal4462VerifierTests(unittest.TestCase):
    def setUp(self):
        self.namespace = namespace_for("rubric_no_deal4462_funding")
        self.seeded = [
            "Deal 4462 / missing insurance stip: document remains outstanding. "
            "Noah Alvarez owns follow-up and escalation."
        ]

    def test_status_prompt_is_not_overridden_by_shingle_similarity(self):
        text = (
            "Noah, status update on Deal 4462 / missing insurance stip: document "
            "remains outstanding. Do you need anything before your escalation?"
        )

        self.assertFalse(
            self.namespace["_is_duplicate_escalation"](text, self.seeded)
        )

    def test_new_missing_stip_announcement_is_a_duplicate(self):
        text = "Deal 4462 — Missing stip: proof of insurance remains outstanding."

        self.assertTrue(
            self.namespace["_is_duplicate_escalation"](text, self.seeded)
        )


if __name__ == "__main__":
    unittest.main()
