#!/usr/bin/env python3
"""Focused regressions for evaluator defects QI3-QI6."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}

QUERY = "90e5d5f1-b719-4d7e-8063-86eb1c0deed3"
TRE900 = "f27e4f15-5e0a-4c91-8aee-c0ea4181ef9d"
COMP_EXISTENCE = "7c4a160c-fed8-4ceb-96c1-e1727024a914"
COMP_0223 = "bc26fbaf-5f13-43f2-997c-353c8a8de92c"
COMP_0228 = "60018d88-28b8-44ce-b28c-4c2e11a344ee"
COMP_XREF = "22f973a2-3243-4911-b491-9df67655de73"


def verifier(rubric_id: str):
    namespace = {"__builtins__": __builtins__}
    exec(
        compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"),
        namespace,
    )
    return namespace["verify"]


def write_jira(services: Path, data: dict) -> None:
    (services / "jira_state.json").write_text(json.dumps(data))


def basic_issue(key: str, fields: dict | None = None) -> dict:
    return {"id": key.replace("OPS-", "1000"), "key": key, "fields": fields or {}}


def comp_issue(
    key: str,
    wire_id: str,
    *,
    project_key: str = "COMP",
    description: str = "",
) -> dict:
    return {
        "key": key,
        "fields": {
            "project": {"key": project_key},
            "summary": f"Exception Report: International Wire Control Exception - {wire_id}",
            "assignee": {"accountId": "diana.walsh"},
            "description": description,
        },
    }


DESCRIPTION_0223 = (
    "INTL-2026-0223 OPS-3 OPS-5 #treasury-wires TRE-900 "
    "claire.overton Approved. Chief Compliance Officer"
)
DESCRIPTION_0228 = (
    "INTL-2026-0228 OPS-4 OPS-5 #treasury-wires TRE-900 "
    "claire.overton Approved. Missing dual approval. Chief Compliance Officer"
)


class JiraTre900Regressions(unittest.TestCase):
    def run_state(self, data: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            write_jira(services, data)
            return verifier(TRE900)(str(root), str(services))

    def test_fields_description_alone_does_not_count(self) -> None:
        issues = {
            key: basic_issue(key, {"description": "Applied TRE-900"})
            for key in ("OPS-3", "OPS-4")
        }
        result = self.run_state({"issues": issues, "comments": {}})
        self.assertFalse(result["pass"], result["feedback"])

    def test_reads_labels_from_fields(self) -> None:
        issues = {
            key: basic_issue(key, {"labels": ["TRE-900"]})
            for key in ("OPS-3", "OPS-4")
        }
        result = self.run_state({"issues": issues, "comments": {}})
        self.assertTrue(result["pass"], result["feedback"])

    def test_reads_top_level_keyed_and_inline_comments(self) -> None:
        issues = {
            "OPS-3": basic_issue("OPS-3", {}),
            "OPS-4": basic_issue(
                "OPS-4",
                {
                    "comment": {
                        "comments": [
                            {
                                "body": {
                                    "type": "doc",
                                    "content": [{"type": "text", "text": "TRE-900"}],
                                }
                            }
                        ]
                    }
                },
            ),
        }
        data = {
            "issues": issues,
            "comments": {"OPS-3": [{"body": "Applied TRE-900"}]},
        }
        result = self.run_state(data)
        self.assertTrue(result["pass"], result["feedback"])

    def test_reads_only_named_custom_fields(self) -> None:
        issues = {
            "OPS-3": basic_issue("OPS-3", {"customfield_10420": "TRE-900"}),
            "OPS-4": basic_issue("OPS-4", {"exception_code": "TRE-900"}),
        }
        result = self.run_state({"issues": issues, "comments": {}})
        self.assertTrue(result["pass"], result["feedback"])

        issues["OPS-3"]["fields"] = {"status": {"note": "TRE-900"}}
        result = self.run_state({"issues": issues, "comments": {}})
        self.assertFalse(result["pass"], result["feedback"])


class CompProjectRegressions(unittest.TestCase):
    def run_state(self, rubric_id: str, issues: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            write_jira(services, {"issues": issues})
            return verifier(rubric_id)(str(root), str(services))

    def test_existence_search_rejects_non_comp_lookalikes(self) -> None:
        decoys = {
            "OPS-30": comp_issue(
                "OPS-30", "INTL-2026-0223", project_key="OPS"
            ),
            "OPS-40": comp_issue(
                "OPS-40", "INTL-2026-0228", project_key="OPS"
            ),
        }
        result = self.run_state(COMP_EXISTENCE, decoys)
        self.assertFalse(result["pass"], result["feedback"])

        decoys.update(
            {
                "COMP-1": comp_issue("COMP-1", "INTL-2026-0223"),
                "COMP-2": comp_issue("COMP-2", "INTL-2026-0228"),
            }
        )
        result = self.run_state(COMP_EXISTENCE, decoys)
        self.assertTrue(result["pass"], result["feedback"])

    def test_b3_description_searches_reject_non_comp_lookalikes(self) -> None:
        cases = (
            (COMP_0223, "INTL-2026-0223", DESCRIPTION_0223),
            (COMP_0228, "INTL-2026-0228", DESCRIPTION_0228),
        )
        for rubric_id, wire_id, description in cases:
            with self.subTest(rubric_id=rubric_id):
                decoy = comp_issue(
                    "OPS-99",
                    wire_id,
                    project_key="OPS",
                    description=description,
                )
                result = self.run_state(rubric_id, {"OPS-99": decoy})
                self.assertFalse(result["pass"], result["feedback"])

                valid = comp_issue(
                    "COMP-99", wire_id, description=description
                )
                result = self.run_state(
                    rubric_id, {"OPS-99": decoy, "COMP-99": valid}
                )
                self.assertTrue(result["pass"], result["feedback"])


class SlackQueryRegressions(unittest.TestCase):
    def run_query(self, value: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.cell(3, 1).value = "Wire ID"
            sheet.cell(3, 2).value = "Slack Query Used"
            sheet.cell(4, 1).value = "INTL-2026-0219"
            sheet.cell(4, 2).value = value
            workbook.save(root / "Wire_Population_Q1_2026.xlsx")
            workbook.close()
            return verifier(QUERY)(str(root))

    def test_bare_channel_substrings_do_not_count(self) -> None:
        invalid_values = (
            "treasury-wires",
            "searched #treasury-wires",
            "treasury_wires",
            "notin:#treasury-wires",
            "in:#treasury-wires-extra",
            "query 23",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                result = self.run_query(value)
                self.assertFalse(result["pass"], result["feedback"])

    def test_exact_channel_syntax_or_explicit_query_marker_counts(self) -> None:
        valid_values = (
            "INTL-2026-0219 in:#treasury-wires",
            "query (2)",
            "Query 3 used",
        )
        for value in valid_values:
            with self.subTest(value=value):
                result = self.run_query(value)
                self.assertTrue(result["pass"], result["feedback"])


class SlackCrossReferenceRegressions(unittest.TestCase):
    def run_state(self, messages: list[dict], jira_keys: tuple[str, ...]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "services"
            services.mkdir()
            slack = {
                "channels": {"C-COMP": {"name": "compliance-urgent"}},
                "messages": {"C-COMP": messages},
            }
            jira = {"issues": {key: {"key": key} for key in jira_keys}}
            (services / "slack_data.json").write_text(json.dumps(slack))
            write_jira(services, jira)
            return verifier(COMP_XREF)(str(root), str(services))

    def test_later_corrected_candidate_can_reference_existing_key(self) -> None:
        phrase = "International wire control exception filed"
        messages = [
            {"text": f"{phrase} INTL-2026-0223 | Jira: COMP-999"},
            {"text": f"{phrase} INTL-2026-0223 | Jira: COMP-1"},
            {"text": f"{phrase} INTL-2026-0228 | Jira: COMP-2"},
        ]
        result = self.run_state(messages, ("COMP-1", "COMP-2"))
        self.assertTrue(result["pass"], result["feedback"])

    def test_all_invalid_candidates_still_fail(self) -> None:
        phrase = "International wire control exception filed"
        messages = [
            {"text": f"{phrase} INTL-2026-0223 | Jira: COMP-998"},
            {"text": f"{phrase} INTL-2026-0223 | Jira: COMP-999"},
            {"text": f"{phrase} INTL-2026-0228 | Jira: COMP-2"},
        ]
        result = self.run_state(messages, ("COMP-1", "COMP-2"))
        self.assertFalse(result["pass"], result["feedback"])


if __name__ == "__main__":
    unittest.main()
