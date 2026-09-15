#!/usr/bin/env python3
"""End-to-end regressions for the Slack artifact input contract.

The correction audit found 83 criterion-outcome changes outside the intended
Carlos/Hiroshi fixes. Most involve workbook evidence availability in historical
archive comparisons and are not repaired here. This suite isolates the one
task-local deterministic contract defect: the declared final Slack state must
reach rubric_1776177277018 before its unchanged semantic checks run.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import sop_verifier


TESTS_DIR = Path(__file__).resolve().parent
RUBRIC_ID = "rubric_1776177277018"
RUBRICS = json.loads((TESTS_DIR / "rubrics.json").read_text())
REQUIRED_MERCHANTS = (
    "Serenity Hotel and Spa",
    "Riverfront Deli",
    "The Creamery Cafe",
    "Canal Street Kitchen",
    "The Landing Spot",
)


def load_verifier():
    rubric = next(item for item in RUBRICS if item["id"] == RUBRIC_ID)
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(rubric["verifier_code"], f"<{RUBRIC_ID}>", "exec"), namespace)
    return namespace["verify"]


def valid_message() -> str:
    return "\n".join(
        (
            "T&E Review Flag",
            "Manager: <@U072>",
            "Employee: Priya Natarajan",
            "Date Range: 5/5/2026 - 5/10/2026",
            "Total Amount Approved: $0.00",
            "Total Amount Denied: $1,691.33",
            (
                "Expenses: Serenity Hotel and Spa; Riverfront Deli; "
                "The Creamery Cafe; Canal Street Kitchen; The Landing Spot; "
                "mileage reimbursement"
            ),
            "Details: Submitted without business justification and no calendar support.",
            "Action Taken: Expense report OPS-39 denied.",
        )
    )


def slack_state(message: str) -> dict:
    return {
        "channels": {"C001": {"name": "finance-approvals"}},
        "messages": {"C001": [{"text": message}]},
        "users": {"U072": {"name": "l_zahra"}},
    }


def valid_slack_state() -> dict:
    return slack_state(valid_message())


def create_real_artifact_layout(root: Path) -> tuple[Path, Path, Path]:
    """Mirror a saved grader layout with workdir and data as siblings."""
    graded = root / "artifacts" / "graded"
    workdir = graded / "workdir"
    data = graded / "data"
    slack_final = data / "slack" / "final.json"
    workdir.mkdir(parents=True)
    slack_final.parent.mkdir(parents=True)
    return workdir, data, slack_final


class SlackArtifactPathVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verify = staticmethod(load_verifier())

    def verify_message(self, message: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _, slack_final = create_real_artifact_layout(Path(tmp))
            slack_final.write_text(json.dumps(slack_state(message)))
            return self.verify(str(workdir))

    def test_saved_graded_layout_reaches_semantic_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir, _, slack_final = create_real_artifact_layout(Path(tmp))
            slack_final.write_text(json.dumps(valid_slack_state()))

            result = self.verify(str(workdir))

            self.assertTrue(result["pass"], result["feedback"])
            self.assertIn(str(slack_final), result["feedback"])
            self.assertIn("Best matching message scored 9/9", result["feedback"])

    def test_live_verifier_consumes_final_state_from_saved_data_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workdir, data, slack_final = create_real_artifact_layout(root)
            slack_final.write_text(json.dumps(valid_slack_state()))
            empty_initial = root / "initial_external_services"
            empty_initial.mkdir()
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "rubrics.json").write_text(
                (TESTS_DIR / "rubrics.json").read_text()
            )
            verifier_output = root / "verifier"

            sop_verifier.WORKDIR = workdir
            sop_verifier.DATA_DIR = data
            sop_verifier.INITIAL_DATA_DIR = empty_initial
            sop_verifier.TESTS_DIR = tests_dir
            sop_verifier.VERIFIER_DIR = verifier_output
            with contextlib.redirect_stdout(io.StringIO()):
                sop_verifier.main()

            results = json.loads((tests_dir / "results.json").read_text())
            target = next(
                item for item in results["rubric_results"] if item["id"] == RUBRIC_ID
            )
            self.assertTrue(target["pass"], target["feedback"])
            self.assertIn("slack_data.json", target["feedback"])
            self.assertIn("Best matching message scored 9/9", target["feedback"])

    def test_missing_each_required_merchant_fails(self) -> None:
        for merchant in REQUIRED_MERCHANTS:
            with self.subTest(merchant=merchant):
                result = self.verify_message(valid_message().replace(merchant, ""))
                self.assertFalse(result["pass"], result["feedback"])
                self.assertIn(merchant, result["feedback"])
                self.assertIn(
                    "FAIL: All five required merchants + mileage line",
                    result["feedback"],
                )

    def test_affirmative_business_justification_fails(self) -> None:
        message = valid_message().replace(
            "Details: Submitted without business justification and no calendar support.",
            "Details: Business justification was provided and documented.",
        )
        result = self.verify_message(message)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn(
            "FAIL: Details states missing business justification",
            result["feedback"],
        )

    def test_unrelated_denial_is_not_bound_to_ops_39(self) -> None:
        message = valid_message().replace(
            "Action Taken: Expense report OPS-39 denied.",
            "Action Taken: Expense report OPS-40 denied. OPS-39 remains pending.",
        )
        result = self.verify_message(message)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn(
            "FAIL: Action Taken denies expense report OPS-39",
            result["feedback"],
        )

    def test_action_taken_without_ops_39_fails(self) -> None:
        message = valid_message().replace(
            "Action Taken: Expense report OPS-39 denied.",
            "Action Taken: Expense report denied.",
        )
        result = self.verify_message(message)
        self.assertFalse(result["pass"], result["feedback"])
        self.assertIn(
            "FAIL: Action Taken denies expense report OPS-39",
            result["feedback"],
        )

    def test_missing_declared_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "artifacts" / "graded" / "workdir"
            workdir.mkdir(parents=True)

            result = self.verify(str(workdir))

            self.assertFalse(result["pass"], result["feedback"])
            self.assertEqual(0.0, result["score"])
            self.assertIn("Slack artifact not found", result["feedback"])
            self.assertIn("graded/data/slack/final.json", result["feedback"])

    def test_malformed_declared_artifact_fails_closed(self) -> None:
        malformed_values = ("{not-json", "[]")
        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                with tempfile.TemporaryDirectory() as tmp:
                    workdir, _, slack_final = create_real_artifact_layout(Path(tmp))
                    slack_final.write_text(malformed)

                    result = self.verify(str(workdir))

                    self.assertFalse(result["pass"], result["feedback"])
                    self.assertEqual(0.0, result["score"])
                    self.assertIn(str(slack_final), result["feedback"])
                    self.assertTrue(
                        "Could not load Slack artifact" in result["feedback"]
                        or "Malformed Slack artifact" in result["feedback"]
                    )

    def test_authoritative_external_artifact_is_not_bypassed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workdir, _, slack_final = create_real_artifact_layout(root)
            slack_final.write_text(json.dumps(valid_slack_state()))
            compat = root / "compat"
            compat.mkdir()
            authoritative = compat / "slack_data.json"
            authoritative.write_text("{not-json")

            result = self.verify(str(workdir), str(compat))

            self.assertFalse(result["pass"], result["feedback"])
            self.assertEqual(0.0, result["score"])
            self.assertIn(str(authoritative), result["feedback"])


if __name__ == "__main__":
    unittest.main()
