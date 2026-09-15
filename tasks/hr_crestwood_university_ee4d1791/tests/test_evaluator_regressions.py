#!/usr/bin/env python3
"""Focused regressions for the evaluator defects identified in the task RCA."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {item["id"]: item for item in json.loads((TESTS_DIR / "rubrics.json").read_text())}


def verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    code = RUBRICS[rubric_id]["verifier_code"]
    exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"], namespace


def write_json(directory: Path, name: str, value: object) -> None:
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


class EvaluatorRegressionTests(unittest.TestCase):
    def test_all_inline_verifiers_compile(self) -> None:
        for rubric_id in RUBRICS:
            with self.subTest(rubric_id=rubric_id):
                verifier(rubric_id)

    def test_external_service_verifiers_fail_closed_without_evidence(self) -> None:
        affected = {
            "cb20ffd5-5d81-4814-ae29-03c32e1ff398": "mailbox.json",
            "a320280d-d6c5-4e61-a78f-20d77a54127d": "mailbox.json",
            "12ef90e8-0558-4d47-9e4b-3b2b014c36e6": "calendar_data.json",
            "83a1a28b-8460-4566-97c0-033153f0131b": "mailbox.json",
            "57ef7283-93c8-47cd-a493-6457e21230bc": "slack_data.json",
            "4bccaed5-3de3-4419-9390-bc2d4544f222": "mailbox.json",
            "rubric_1776042091132": "jira_state.json",
            "rubric_1776042100472": "mailbox.json",
            "rubric_1776042123728": "slack_data.json",
            "c2eba6d4-881b-49be-b512-3fb373b3095c": "jira_state.json",
            "a78a9f20-c5f1-4fc6-92cb-deaf0ff4b05b": "jira_state.json",
        }
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = Path(tmp)
            for rubric_id, filename in affected.items():
                verify, _ = verifier(rubric_id)
                state_file = empty_dir / filename
                state_file.unlink(missing_ok=True)
                with self.subTest(rubric_id=rubric_id, evidence="no path"):
                    self.assertFalse(verify(str(empty_dir), None)["pass"])
                with self.subTest(rubric_id=rubric_id, evidence="missing file"):
                    result = verify(str(empty_dir), str(empty_dir))
                    self.assertFalse(result["pass"])
                    self.assertIn(filename, result["feedback"])
                with self.subTest(rubric_id=rubric_id, evidence="missing collection"):
                    write_json(empty_dir, filename, {})
                    self.assertFalse(verify(str(empty_dir), str(empty_dir))["pass"])

    def test_maria_emails_are_bound_to_template_and_certification_forward(self) -> None:
        verify, namespace = verifier("a320280d-d6c5-4e61-a78f-20d77a54127d")
        expected_body = namespace["EXPECTED_TEMPLATE_15"]
        retained_authored_body = expected_body.replace(
            "Best regards, Crestwood University – Office of Human Resources hr@crestwood.edu",
            "Best regards,\nCrestwood University – Office of Human Resources\nhr@crestwood.edu",
        )
        quoted_original = """--- Original Message ---
From: m.torres@crestwood.edu
Date: 2026-04-12 08:12
Subject: FMLA Leave Request

Hi,

I need to request FMLA leave from June 29th to August 7th for an upcoming medical procedure and recovery.

Please let me know what else you need.

Maria Torres
Finance Department, Main Campus"""
        retained_reply_body = f"{retained_authored_body}\n\n{quoted_original}"
        valid = {
            "emails": [
                {
                    "email_id": "35",
                    "folder": "Sent",
                    "to_addr": "m.torres@crestwood.edu",
                    "subject": "Re: FMLA Leave Request",
                    "body_text": expected_body,
                    "attachments": [],
                },
                {
                    "email_id": "36",
                    "folder": "Sent",
                    "to_addr": "p.huang@crestwood.edu",
                    "subject": "Fwd: FMLA Leave Request",
                    "body_text": "Forwarding for review.",
                    "attachments": [{"filename": "medical_certification_torres.pdf"}],
                },
                {
                    "email_id": "1",
                    "folder": "Leave",
                    "from_addr": "m.torres@crestwood.edu",
                    "to_addr": "hr@crestwood.edu",
                    "subject": "FMLA Leave Request",
                    "date": "2026-04-12T08:12:00-06:00",
                    "body_text": """Hi,

I need to request FMLA leave from June 29th to August 7th for an upcoming medical procedure and recovery.

Please let me know what else you need.

Maria Torres
Finance Department, Main Campus""",
                    "attachments": [{"filename": "medical_certification_torres.pdf"}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            write_json(services, "mailbox.json", valid)
            self.assertTrue(verify(tmp, tmp)["pass"])

            retained_reply = json.loads(json.dumps(valid))
            retained_reply["emails"][0]["body_text"] = retained_reply_body
            write_json(services, "mailbox.json", retained_reply)
            self.assertTrue(verify(tmp, tmp)["pass"])

            numeric_format_variant = json.loads(json.dumps(retained_reply))
            numeric_format_variant["emails"][0]["body_text"] = retained_reply_body.replace("1,420", "1420", 1)
            write_json(services, "mailbox.json", numeric_format_variant)
            self.assertTrue(verify(tmp, tmp)["pass"])

            wrong_template_bodies = {
                "wrong hours": retained_reply_body.replace("1,420", "1,400", 1),
                "wrong due date": retained_reply_body.replace("04/27/2026", "04/28/2026", 1),
                "missing required sentence": retained_reply_body.replace(
                    " Failure to return the certification by this date may result in denial of your FMLA leave request.",
                    "",
                    1,
                ),
                "extra authored text": retained_reply_body.replace(
                    "\n\n--- Original Message ---",
                    "\n\nThis notice supersedes the standard terms.\n\n--- Original Message ---",
                    1,
                ),
                "fake headers with unrelated body": (
                    f"{retained_authored_body}\n\n--- Original Message ---\n"
                    "From: m.torres@crestwood.edu\n"
                    "Date: 2026-04-12 08:12\n"
                    "Subject: FMLA Leave Request\n\n"
                    "This is unrelated text, not the matching inbound Maria message."
                ),
            }
            for case, body in wrong_template_bodies.items():
                wrong_template = json.loads(json.dumps(valid))
                wrong_template["emails"][0]["body_text"] = body
                write_json(services, "mailbox.json", wrong_template)
                with self.subTest(case=case):
                    self.assertFalse(verify(tmp, tmp)["pass"])

            irrelevant = json.loads(json.dumps(valid))
            irrelevant["emails"][0]["body_text"] = "Unrelated note"
            write_json(services, "mailbox.json", irrelevant)
            self.assertFalse(verify(tmp, tmp)["pass"])

            missing_attachment = json.loads(json.dumps(valid))
            missing_attachment["emails"][1]["attachments"] = []
            write_json(services, "mailbox.json", missing_attachment)
            result = verify(tmp, tmp)
            self.assertFalse(result["pass"])
            self.assertIn("medical_certification_torres.pdf", result["feedback"])

    def test_jira_description_flattens_all_adf_text_nodes(self) -> None:
        verify, _ = verifier("8e6b5aaa-6946-428a-a874-eee5e12ea7d5")
        jira = {
            "issues": {
                "LEAVE-2": {
                    "fields": {
                        "summary": "LEAVE-Torres-04122026",
                        "project": {"key": "LEAVE"},
                        "description": {
                            "type": "doc",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "Employee Name: Maria Torres"}]},
                                {
                                    "type": "bulletList",
                                    "content": [
                                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Employee ID: E-1001"}]}]},
                                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Assignee: Patricia Huang"}]}]},
                                    ],
                                },
                            ],
                        },
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp), "jira_state.json", jira)
            self.assertTrue(verify(tmp, tmp)["pass"])

    def test_certification_received_requires_the_final_tracker_date(self) -> None:
        verify, _ = verifier("feee0d0b-9a8d-4e10-8100-8325b71dd4ca")
        headers = [
            "employee_id",
            "employee_name",
            "status",
            "fmla_certification_received",
        ]
        rows = [
            ["E-1011", "Michael Torres", "Active", None],
            ["E-1001", "Maria Torres", "Approved – Pending Certification Review", "2026-04-12"],
            ["E-1005", "Kevin Walsh", "Returned", "2026-01-22"],
        ]

        def write_tracker(directory: Path, tracker_headers: list[str], tracker_rows: list[list[object]]) -> None:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Sheet1"
            ws.append(tracker_headers)
            for tracker_row in tracker_rows:
                ws.append(tracker_row)
            wb.save(directory / "leave_tracker.xlsx")
            wb.close()

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_tracker(workspace, headers, rows)
            self.assertTrue(verify(tmp, None)["pass"])

            write_tracker(workspace, headers, list(reversed(rows)))
            self.assertTrue(verify(tmp, None)["pass"])

            missing_value = json.loads(json.dumps(rows))
            missing_value[1][3] = None
            write_tracker(workspace, headers, missing_value)
            self.assertFalse(verify(tmp, None)["pass"])

            wrong_value = json.loads(json.dumps(rows))
            wrong_value[1][3] = "04/13/2026"
            write_tracker(workspace, headers, wrong_value)
            self.assertFalse(verify(tmp, None)["pass"])

            write_tracker(workspace, headers[:-1], [row[:-1] for row in rows])
            result = verify(tmp, None)
            self.assertFalse(result["pass"])
            self.assertIn("fmla_certification_received", result["feedback"])

    def test_leave_ticket_must_remain_in_progress(self) -> None:
        verify, _ = verifier("c2eba6d4-881b-49be-b512-3fb373b3095c")
        target = {
            "key": "LEAVE-7",
            "fields": {
                "summary": "LEAVE-Torres-04122026",
                "status": {
                    "name": "In Progress",
                    "statusCategory": {"key": "indeterminate", "name": "In Progress"},
                },
                "comment": {
                    "comments": [
                        {"created": "2026-04-12T12:02:00Z", "body": "Certification forwarded"},
                        {"created": "2026-04-12T12:01:00Z", "body": "Eligibility checked"},
                    ]
                },
            },
        }
        valid = {
            "issues": {
                "LEAVE-1": {"fields": {"summary": "LEAVE-Walsh-01092026", "status": {"name": "Done"}}},
                "LEAVE-7": target,
                "HR-9": {"fields": {"summary": "Unrelated record", "status": {"name": "In Progress"}}},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            write_json(services, "jira_state.json", valid)
            self.assertTrue(verify(tmp, tmp)["pass"])

            reordered = {"issues": {"LEAVE-7": target, "LEAVE-1": valid["issues"]["LEAVE-1"]}}
            write_json(services, "jira_state.json", reordered)
            self.assertTrue(verify(tmp, tmp)["pass"])

            missing_status = json.loads(json.dumps(valid))
            del missing_status["issues"]["LEAVE-7"]["fields"]["status"]
            write_json(services, "jira_state.json", missing_status)
            self.assertFalse(verify(tmp, tmp)["pass"])

            wrong_status = json.loads(json.dumps(valid))
            wrong_status["issues"]["LEAVE-7"]["fields"]["status"] = {
                "name": "Done",
                "statusCategory": {"key": "done", "name": "Done"},
            }
            write_json(services, "jira_state.json", wrong_status)
            self.assertFalse(verify(tmp, tmp)["pass"])

    def test_offboarding_ticket_must_be_closed(self) -> None:
        verify, _ = verifier("a78a9f20-c5f1-4fc6-92cb-deaf0ff4b05b")
        target = {
            "key": "OFFBOARD-1",
            "fields": {
                "summary": "OFFBOARD-Kim-04062026",
                "status": {
                    "name": "Done",
                    "statusCategory": {"key": "done", "name": "Done"},
                },
            },
        }
        valid = {
            "issues": {
                "OFFBOARD-4": {
                    "key": "OFFBOARD-4",
                    "fields": {"summary": "OFFBOARD-Edwards-10192025", "status": {"name": "Done"}},
                },
                "OFFBOARD-1": target,
                "ONBOARD-1": {
                    "key": "ONBOARD-1",
                    "fields": {"summary": "ONBOARD-Ellis-04202026", "status": {"name": "In Progress"}},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            write_json(services, "jira_state.json", valid)
            self.assertTrue(verify(tmp, tmp)["pass"])

            reordered = {
                "issues": {
                    "OFFBOARD-1": target,
                    "OFFBOARD-4": valid["issues"]["OFFBOARD-4"],
                    "ONBOARD-1": valid["issues"]["ONBOARD-1"],
                }
            }
            write_json(services, "jira_state.json", reordered)
            self.assertTrue(verify(tmp, tmp)["pass"])

            missing_status = json.loads(json.dumps(valid))
            del missing_status["issues"]["OFFBOARD-1"]["fields"]["status"]
            write_json(services, "jira_state.json", missing_status)
            self.assertFalse(verify(tmp, tmp)["pass"])

            wrong_status = json.loads(json.dumps(valid))
            wrong_status["issues"]["OFFBOARD-1"]["fields"]["status"] = {
                "name": "In Progress",
                "statusCategory": {"key": "indeterminate", "name": "In Progress"},
            }
            write_json(services, "jira_state.json", wrong_status)
            self.assertFalse(verify(tmp, tmp)["pass"])

    def test_slack_negative_check_only_inspects_structured_messages_once(self) -> None:
        verify, _ = verifier("rubric_1776042123728")
        slack = {
            "channels": {"C001": {"name": "okafor-metadata-only"}},
            "users": {"U001": {"real_name": "James Okafor", "title": "E-1003"}},
            "messages": {"C001": [{"text": "No case activity here", "metadata": "Okafor"}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp)
            write_json(services, "slack_data.json", slack)
            self.assertTrue(verify(tmp, tmp)["pass"])

            slack["messages"]["C001"][0]["text"] = "Do not process James Okafor (E-1003)."
            write_json(services, "slack_data.json", slack)
            result = verify(tmp, tmp)
            self.assertFalse(result["pass"])
            self.assertIn("Found 1 Slack message(s)", result["feedback"])

            write_json(services, "slack_data.json", {"channels": slack["channels"]})
            self.assertFalse(verify(tmp, tmp)["pass"])

    def test_okafor_requires_cobra_column_and_blank_cell(self) -> None:
        verify, _ = verifier("rubric_1776042175636")

        def make_workbooks(directory: Path, cobra_header: bool, cobra_value=None) -> None:
            roster = openpyxl.Workbook()
            roster.active.append(["employee_id", "employee_name", "status"])
            roster.active.append(["E-1003", "James Okafor", "Active"])
            roster.save(directory / "employee_roster.xlsx")
            roster.close()

            benefits = openpyxl.Workbook()
            if cobra_header:
                benefits.active.append(["employee_id", "employee_name", "cobra_notification_date", "status"])
                benefits.active.append(["E-1003", "James Okafor", cobra_value, "Active"])
            else:
                benefits.active.append(["employee_id", "employee_name", "status"])
                benefits.active.append(["E-1003", "James Okafor", "Active"])
            benefits.save(directory / "benefits_enrollment.xlsx")
            benefits.close()

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workbooks(workspace, cobra_header=False)
            result = verify(tmp, None)
            self.assertFalse(result["pass"])
            self.assertIn("Required 'cobra_notification_date' column is missing", result["feedback"])

            make_workbooks(workspace, cobra_header=True, cobra_value=None)
            self.assertTrue(verify(tmp, None)["pass"])

            make_workbooks(workspace, cobra_header=True, cobra_value="04/12/2026")
            self.assertFalse(verify(tmp, None)["pass"])


if __name__ == "__main__":
    unittest.main()
