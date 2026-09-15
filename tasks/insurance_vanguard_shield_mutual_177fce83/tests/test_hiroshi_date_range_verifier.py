#!/usr/bin/env python3
"""Focused regressions for the Hiroshi OPS-71 date-range comparison."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


CRITERION_ID = "8db7af74-e1a4-4f57-b4f7-7186ebe398d9"
EXPECTED_RANGE = "5/5/2026 - 5/9/2026"


def _load_dates_match():
    rubrics = json.loads(Path(__file__).with_name("rubrics.json").read_text())
    criterion = next(rubric for rubric in rubrics if rubric["id"] == CRITERION_ID)
    tree = ast.parse(criterion["verifier_code"])
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "dates_match"
    )
    module = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="re")]),
            ast.ImportFrom(
                module="datetime",
                names=[ast.alias(name="datetime")],
                level=0,
            ),
            function,
        ],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), "<dates_match>", "exec"), namespace)
    return namespace["dates_match"]


class DateRangeVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dates_match = staticmethod(_load_dates_match())

    def test_accepts_ascii_and_unicode_dash_variants(self):
        for dash in "-‐‑‒–—―−":
            with self.subTest(dash=f"U+{ord(dash):04X}"):
                self.assertTrue(
                    self.dates_match(f"5/5/2026{dash}5/9/2026", EXPECTED_RANGE)
                )

    def test_parses_equivalent_endpoint_formats(self):
        self.assertTrue(
            self.dates_match("05/05/2026 – 05/09/2026", EXPECTED_RANGE)
        )
        self.assertTrue(
            self.dates_match("2026-05-05 — 2026-05-09", EXPECTED_RANGE)
        )

    def test_rejects_missing_or_inexact_endpoints(self):
        rejected = [
            "5/5/2026",
            "5/6/2026–5/9/2026",
            "5/5/2026–5/10/2026",
            "5/9/2026–5/5/2026",
            "5/5/2026–5/9/2026 extra",
        ]
        for actual in rejected:
            with self.subTest(actual=actual):
                self.assertFalse(self.dates_match(actual, EXPECTED_RANGE))


if __name__ == "__main__":
    unittest.main()
