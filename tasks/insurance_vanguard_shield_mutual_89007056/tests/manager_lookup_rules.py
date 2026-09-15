#!/usr/bin/env python3
"""Task-local B-9/B-8 chronology checks for Derek Washington's T&E report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any


PEOPLE_ADDRESS = "people@vanguardshield.com"
HROPS_ADDRESS = "hrops@vanguardshield.com"
REPORT_PATTERN = re.compile(r"ops[-_]hr[-_]te[-_]4(?!\d)", re.IGNORECASE)
MINIMUM_WAIT = timedelta(hours=3)


def _result(passed: bool, feedback: str) -> dict[str, Any]:
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "feedback": feedback,
    }


def _load_state(root: str | None, filename: str) -> tuple[Any | None, str | None]:
    if not root:
        return None, f"external_services_path is None; cannot locate {filename}"
    path = Path(root) / filename
    if not path.is_file():
        return None, f"{filename} not found at {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"Failed to parse {filename}: {exc}"


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return "" if value is None else str(value)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _addresses(value: Any) -> set[str]:
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value or "")
    return {
        match.casefold()
        for match in re.findall(
            r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
            text,
            flags=re.IGNORECASE,
        )
    }


def _email_text(email: dict[str, Any]) -> str:
    return " ".join(
        str(email.get(field) or "")
        for field in ("subject", "body_text", "body", "content")
    )


def _email_timestamp(email: dict[str, Any]) -> datetime | None:
    for field in ("date", "sent_at", "created", "created_at", "timestamp"):
        timestamp = _parse_timestamp(email.get(field))
        if timestamp is not None:
            return timestamp
    return None


def _sent(email: dict[str, Any]) -> bool:
    return str(email.get("folder", "")).strip().casefold() == "sent"


def _has_report_identity(text: str) -> bool:
    folded = text.casefold()
    return (
        REPORT_PATTERN.search(folded) is not None
        and "derek washington" in folded
        and "emp-2287" in folded
    )


def _potential_b8(text: str) -> bool:
    folded = text.casefold()
    has_report = REPORT_PATTERN.search(folded) is not None
    has_name = "derek washington" in folded
    has_employee_id = "emp-2287" in folded
    b8_marker = "t&e manager lookup" in folded
    b8_title = "manager lookup needed" in folded and "t&e exception" in folded
    task_related = (
        has_report and (has_name or has_employee_id)
    ) or (has_name and has_employee_id)
    return (b8_marker or b8_title) and task_related


def _valid_b8_content(text: str) -> bool:
    folded = text.casefold()
    return "[t&e manager lookup]" in folded and _has_report_identity(text)


def _b9_requests(mail: Any) -> list[tuple[datetime | None, dict[str, Any]]]:
    if not isinstance(mail, dict) or not isinstance(mail.get("emails"), list):
        return []
    matches = []
    for email in mail["emails"]:
        if not isinstance(email, dict) or not _sent(email):
            continue
        recipients = _addresses(
            email.get("to_addr") or email.get("to") or email.get("recipients")
        )
        text = _email_text(email)
        folded = text.casefold()
        if (
            PEOPLE_ADDRESS in recipients
            and "reporting manager lookup" in folded
            and "reporting manager" in folded
            and _has_report_identity(text)
        ):
            matches.append((_email_timestamp(email), email))
    return matches


def _people_reply_before(
    mail: Any,
    request_at: datetime,
    escalation_at: datetime,
) -> str | None:
    if not isinstance(mail, dict) or not isinstance(mail.get("emails"), list):
        return None
    for email in mail["emails"]:
        if not isinstance(email, dict) or _sent(email):
            continue
        senders = _addresses(email.get("from_addr") or email.get("from"))
        if PEOPLE_ADDRESS not in senders:
            continue
        text = _email_text(email)
        folded = text.casefold()
        if not (
            REPORT_PATTERN.search(folded)
            or "derek washington" in folded
            or "emp-2287" in folded
        ):
            continue
        reply_at = _email_timestamp(email)
        if reply_at is None:
            return "A task-related People reply exists without a usable timestamp"
        if request_at <= reply_at <= escalation_at:
            return f"People replied at {reply_at.isoformat()} before the B-8 escalation"
    return None


def _request_for_escalation(
    requests: list[tuple[datetime | None, dict[str, Any]]],
    escalation_at: datetime | None,
) -> tuple[datetime | None, str | None]:
    if not requests:
        return None, (
            "No initial sent B-9 request to people@vanguardshield.com was found for "
            "Derek Washington / EMP-2287 / OPS_HR_TE-4"
        )
    if escalation_at is None:
        return None, "The task-related B-8 escalation has no usable timestamp"
    timestamped = [timestamp for timestamp, _ in requests if timestamp is not None]
    if not timestamped:
        return None, "The initial B-9 request has no usable timestamp"
    eligible = [timestamp for timestamp in timestamped if timestamp <= escalation_at]
    if not eligible:
        return None, "The B-8 escalation predates every timestamped B-9 request"
    request_at = min(eligible)
    if escalation_at - request_at < MINIMUM_WAIT:
        return None, (
            "The B-8 escalation was premature: it occurred less than three hours "
            "after the initial B-9 People request"
        )
    return request_at, None


def _iter_issues(jira: Any):
    if isinstance(jira, dict):
        issues = jira.get("issues")
        if isinstance(issues, dict):
            yield from (
                (str(key), issue)
                for key, issue in issues.items()
                if isinstance(issue, dict)
            )
            return
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, dict):
                    yield str(issue.get("key") or issue.get("id") or "unknown"), issue
            return
    if isinstance(jira, list):
        for issue in jira:
            if isinstance(issue, dict):
                yield str(issue.get("key") or issue.get("id") or "unknown"), issue


def _issue_timestamp(issue: dict[str, Any]) -> datetime | None:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    for value in (
        fields.get("created"),
        fields.get("created_at"),
        issue.get("created"),
        issue.get("created_at"),
        issue.get("timestamp"),
    ):
        timestamp = _parse_timestamp(value)
        if timestamp is not None:
            return timestamp
    return None


def _in_hrops(issue_key: str, issue: dict[str, Any]) -> bool:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    project = fields.get("project") or issue.get("project") or ""
    project_text = _flatten(project)
    normalized = re.sub(r"[^a-z0-9]+", "", project_text.casefold())
    key_normalized = re.sub(r"[^a-z0-9]+", "", issue_key.casefold())
    return "hrops" in normalized or key_normalized.startswith("hrops")


def verify_jira_rule(workspace_path: str, external_services_path: str | None = None):
    jira, error = _load_state(external_services_path, "jira_state.json")
    if error:
        return _result(False, error)
    mail, error = _load_state(external_services_path, "mailbox.json")
    if error:
        return _result(False, error)

    requests = _b9_requests(mail)
    if not requests:
        return _result(
            False,
            "No initial sent B-9 request to people@vanguardshield.com was found for "
            "Derek Washington / EMP-2287 / OPS_HR_TE-4",
        )

    candidates = []
    for issue_key, issue in _iter_issues(jira):
        text = _flatten(issue)
        if _potential_b8(text):
            candidates.append((issue_key, issue, text))

    if not candidates:
        return _result(
            True,
            "Found the required initial B-9 People request and no task-related B-8 "
            "Jira escalation for Derek Washington / OPS_HR_TE-4.",
        )

    for issue_key, issue, text in candidates:
        if not _valid_b8_content(text):
            return _result(
                False,
                f"Task-related Manager Lookup issue {issue_key} lacks the complete "
                "B-8 marker and Derek Washington / EMP-2287 / OPS_HR_TE-4 identity.",
            )
        if not _in_hrops(issue_key, issue):
            return _result(
                False,
                f"Task-related B-8 issue {issue_key} is not in the HR-Ops queue.",
            )
        escalation_at = _issue_timestamp(issue)
        request_at, timing_error = _request_for_escalation(requests, escalation_at)
        if timing_error:
            return _result(False, f"Issue {issue_key}: {timing_error}")
        assert request_at is not None and escalation_at is not None
        reply_error = _people_reply_before(mail, request_at, escalation_at)
        if reply_error:
            return _result(False, f"Issue {issue_key}: {reply_error}")

    return _result(
        True,
        "Every task-related B-8 Jira escalation is in HR-Ops, follows the initial "
        "B-9 People request by at least three hours, and has no intervening People reply.",
    )


def verify_mail_rule(workspace_path: str, external_services_path: str | None = None):
    mail, error = _load_state(external_services_path, "mailbox.json")
    if error:
        return _result(False, error)
    requests = _b9_requests(mail)
    if not requests:
        return _result(
            False,
            "No initial sent B-9 request to people@vanguardshield.com was found for "
            "Derek Washington / EMP-2287 / OPS_HR_TE-4",
        )

    candidates = []
    emails = mail.get("emails", []) if isinstance(mail, dict) else []
    for email in emails:
        if not isinstance(email, dict) or not _sent(email):
            continue
        text = _email_text(email)
        if _potential_b8(text):
            candidates.append((email, text))

    if not candidates:
        return _result(
            True,
            "Found the required initial B-9 People request and no task-related B-8 "
            "email escalation for Derek Washington / OPS_HR_TE-4.",
        )

    for email, text in candidates:
        email_id = str(email.get("email_id") or email.get("id") or "unknown")
        if not _valid_b8_content(text):
            return _result(
                False,
                f"Task-related Manager Lookup email {email_id} lacks the complete "
                "B-8 marker and Derek Washington / EMP-2287 / OPS_HR_TE-4 identity.",
            )
        recipients = _addresses(
            email.get("to_addr") or email.get("to") or email.get("recipients")
        )
        if HROPS_ADDRESS not in recipients:
            return _result(
                False,
                f"Task-related B-8 email {email_id} was not sent to "
                f"{HROPS_ADDRESS}.",
            )
        escalation_at = _email_timestamp(email)
        request_at, timing_error = _request_for_escalation(requests, escalation_at)
        if timing_error:
            return _result(False, f"Email {email_id}: {timing_error}")
        assert request_at is not None and escalation_at is not None
        reply_error = _people_reply_before(mail, request_at, escalation_at)
        if reply_error:
            return _result(False, f"Email {email_id}: {reply_error}")

    return _result(
        True,
        "Every task-related B-8 email was sent to HR-Ops at least three hours after "
        "the initial B-9 People request, with no intervening People reply.",
    )
