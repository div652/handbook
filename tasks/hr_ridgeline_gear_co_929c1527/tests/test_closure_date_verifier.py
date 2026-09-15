#!/usr/bin/env python3
"""Focused regressions for the Marcus closure-note date criterion."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
CRITERION_ID = "02b7d23d-d9e2-43df-99bc-1e91f5a63ea2"


def _load_verify():
    rubrics = json.loads((TESTS_DIR / "rubrics.json").read_text())
    rubric = next(item for item in rubrics if item["id"] == CRITERION_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{CRITERION_ID}>", "exec"), namespace)
    return namespace["verify"]


class ClosureDateVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(_load_verify())

    def _verify_note(self, note: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet["G11"] = date(2026, 4, 10)
            sheet["O11"] = "Closed"
            sheet["P11"] = note
            workbook.save(Path(tmp) / "leave_tracker.xlsx")
            return self.verify(tmp)

    def test_accepts_both_authorized_date_forms(self) -> None:
        notes = (
            "04/10: Return confirmed; case closed.",
            "Return confirmed; case closed on 04/10/2026.",
        )
        for note in notes:
            with self.subTest(note=note):
                self.assertTrue(self._verify_note(note)["pass"])

    def test_rejects_wrong_or_unanchored_date_forms(self) -> None:
        notes = (
            "Return confirmed; case closed on 04/11.",
            "Return confirmed; case closed on 04/10/2025.",
            "Return confirmed; case closed on 4/10/2026.",
            "Return confirmed; case closed on 04/10/20260.",
        )
        for note in notes:
            with self.subTest(note=note):
                self.assertFalse(self._verify_note(note)["pass"])


if __name__ == "__main__":
    unittest.main()
