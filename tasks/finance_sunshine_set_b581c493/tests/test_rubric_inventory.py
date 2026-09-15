#!/usr/bin/env python3
"""Regression coverage for the QI2 rubric-inventory repair."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


RUBRICS_PATH = Path(__file__).with_name("rubrics.json")


class RubricInventoryTests(unittest.TestCase):
    def test_unsupported_marcus_prohibition_is_removed(self) -> None:
        rubrics = json.loads(RUBRICS_PATH.read_text())
        rubric_ids = {rubric["id"] for rubric in rubrics}

        self.assertNotIn("rubric_no_variance_email_to_marcus", rubric_ids)
        self.assertIn("rubric_template_a_email_sofia", rubric_ids)


if __name__ == "__main__":
    unittest.main()
