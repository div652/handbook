#!/usr/bin/env python3
"""Run bundled SOP Python verifiers inside a Harbor task container."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKDIR = Path("/workdir")
DATA_DIR = Path("/data")
INITIAL_DATA_DIR = Path("/initial_data")
TESTS_DIR = Path("/tests")
VERIFIER_DIR = Path("/logs/verifier")

SERVICE_COMPAT_FILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "slack": ("slack.json", ("slack.json", "slack_data.json")),
    "google_mail": ("inbox.json", ("inbox.json", "mailbox.json")),
    "google_calendar": ("calendar_data.json", ("calendar_data.json", "calendar.json")),
    "jira": ("jira_state.json", ("jira_state.json", "jira_data.json")),
    "shopify": ("shopify_data.json", ("shopify_data.json",)),
}

OPS4_POSITIVE_RUBRICS = {
    "6a839ad9-3949-4bf7-9002-63258e6e5e43",
    "rubric_1775880280596",
}
OPS3_PROTECTED_LINES_RUBRIC = "c713cced-31be-4221-8419-072a071ecab7"
B8_MANAGER_LOOKUP_RUBRIC = "rubric_1775880314655"
B2_MANAGER_DM_RUBRIC = "rubric_1775880383123"
OPS5_COMPLETION_RUBRIC = "rubric_1776019924720"


def _state_path(service: str, seed_name: str) -> Path | None:
    candidates = [
        DATA_DIR / service / "final.json",
        DATA_DIR / service / seed_name,
        INITIAL_DATA_DIR / service / seed_name,
    ]
    return next((p for p in candidates if p.is_file()), None)


def _build_compat_external_services(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for service, (seed_name, compat_names) in SERVICE_COMPAT_FILES.items():
        src = _state_path(service, seed_name)
        if src is not None:
            for compat_name in compat_names:
                shutil.copy2(src, dest / compat_name)


def _coerce_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        passed = bool(raw.get("pass", raw.get("passed", False)))
        score = raw.get("score", 1.0 if passed else 0.0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 1.0 if passed else 0.0
        return {
            "pass": passed,
            "score": max(0.0, min(1.0, score)),
            "feedback": str(raw.get("feedback", "")),
        }
    passed = bool(raw)
    return {"pass": passed, "score": 1.0 if passed else 0.0, "feedback": str(raw)}


def _result(passed: bool, feedback: str) -> dict[str, Any]:
    return {"pass": passed, "score": 1.0 if passed else 0.0, "feedback": feedback}


def _load_json(external_services_path: Path, filename: str) -> Any | None:
    path = external_services_path / filename
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _issue_key(issue: Any) -> str:
    if not isinstance(issue, dict):
        return ""
    for field in ("key", "issue_key", "issueKey"):
        value = issue.get(field)
        if isinstance(value, str):
            return value.strip().upper()
    return ""


def _exact_issue_representations(jira_data: Any, issue_key: str) -> list[dict[str, Any]]:
    """Return every exact representation of an issue, not the first fuzzy match."""
    if not isinstance(jira_data, dict):
        if isinstance(jira_data, list):
            return [i for i in jira_data if _issue_key(i) == issue_key]
        return []

    candidates: list[Any] = []
    issues = jira_data.get("issues")
    if isinstance(issues, dict):
        candidates.append(issues.get(issue_key))
        candidates.extend(
            value
            for key, value in issues.items()
            if key != issue_key and _issue_key(value) == issue_key
        )
    elif isinstance(issues, list):
        candidates.extend(i for i in issues if _issue_key(i) == issue_key)

    candidates.append(jira_data.get(issue_key))
    candidates.extend(
        value
        for key, value in jira_data.items()
        if key not in {"issues", issue_key} and _issue_key(value) == issue_key
    )

    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or id(candidate) in seen:
            continue
        if candidate is jira_data.get(issue_key) or _issue_key(candidate) == issue_key:
            found.append(candidate)
            seen.add(id(candidate))
    return found


def _canonical_issue(jira_data: Any, issue_key: str) -> dict[str, Any] | None:
    """Prefer the canonical top-level issues[KEY] record for workflow state."""
    if isinstance(jira_data, dict):
        issues = jira_data.get("issues")
        if isinstance(issues, dict) and isinstance(issues.get(issue_key), dict):
            return issues[issue_key]
        if isinstance(issues, list):
            for issue in issues:
                if _issue_key(issue) == issue_key:
                    return issue
        if isinstance(jira_data.get(issue_key), dict):
            return jira_data[issue_key]
    representations = _exact_issue_representations(jira_data, issue_key)
    return representations[0] if representations else None


def _issue_status(issue: Any) -> str:
    if not isinstance(issue, dict):
        return ""
    fields = issue.get("fields")
    status = fields.get("status") if isinstance(fields, dict) else None
    if status is None:
        status = issue.get("status")
    if isinstance(status, dict):
        status = status.get("name")
    return str(status or "").strip()


def _verify_status(jira_data: Any, issue_key: str, expected: str) -> dict[str, Any]:
    issue = _canonical_issue(jira_data, issue_key)
    if issue is None:
        return _result(False, f"Hard gate failed: canonical issue {issue_key} was not found.")
    actual = _issue_status(issue)
    if actual.casefold() != expected.casefold():
        return _result(
            False,
            f"Hard gate failed: {issue_key} status is {actual!r}; expected {expected!r}.",
        )
    return _result(True, f"Hard gate passed: {issue_key} is {expected}.")


def _flatten_adf_text(node: Any) -> str:
    """Recursively flatten ADF text nodes while ignoring non-text metadata."""
    if isinstance(node, str):
        return node
    pieces: list[str] = []
    if isinstance(node, list):
        for item in node:
            text = _flatten_adf_text(item)
            if text:
                pieces.append(text)
    elif isinstance(node, dict):
        direct = node.get("text")
        if isinstance(direct, str):
            pieces.append(direct)
        for key, value in node.items():
            if key != "text" and isinstance(value, (dict, list)):
                text = _flatten_adf_text(value)
                if text:
                    pieces.append(text)
    return " ".join(pieces)


def _comment_text(comment: Any) -> str:
    if isinstance(comment, str):
        return comment
    if not isinstance(comment, dict):
        return ""
    pieces: list[str] = []
    for field in ("body", "text", "comment", "content", "message"):
        if field in comment:
            text = _flatten_adf_text(comment[field])
            if text:
                pieces.append(text)
    return " ".join(pieces) if pieces else _flatten_adf_text(comment)


def _unpack_comments(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return [value] if isinstance(value, str) else []
    if "comments" in value:
        return _unpack_comments(value["comments"])
    # A single comment/ADF record should not be split into its child nodes.
    if any(field in value for field in ("body", "text", "content", "message")):
        return [value]
    comments: list[Any] = []
    for child in value.values():
        comments.extend(_unpack_comments(child))
    return comments


def _comment_issue_refs(comment: Any) -> set[str]:
    if not isinstance(comment, dict):
        return set()
    refs: set[str] = set()
    for field in ("issue", "issueKey", "issue_key", "issueId", "issue_id", "key"):
        value = comment.get(field)
        if isinstance(value, dict):
            value = value.get("key") or value.get("id")
        if value is not None:
            refs.add(str(value).strip().upper())
    return refs


def _all_issue_comments(jira_data: Any, issue_key: str) -> list[Any]:
    representations = _exact_issue_representations(jira_data, issue_key)
    comments: list[Any] = []
    issue_refs = {issue_key}
    for issue in representations:
        issue_id = issue.get("id")
        if issue_id is not None:
            issue_refs.add(str(issue_id).strip().upper())
        comments.extend(_unpack_comments(issue.get("comments")))
        fields = issue.get("fields")
        if isinstance(fields, dict):
            comments.extend(_unpack_comments(fields.get("comment")))
            comments.extend(_unpack_comments(fields.get("comments")))

    if not isinstance(jira_data, dict):
        return comments
    top_level = jira_data.get("comments")
    if isinstance(top_level, dict):
        for ref in issue_refs:
            comments.extend(_unpack_comments(top_level.get(ref)))
        for entry in top_level.values():
            for comment in _unpack_comments(entry):
                if _comment_issue_refs(comment) & issue_refs:
                    comments.append(comment)
    elif isinstance(top_level, list):
        comments.extend(
            comment
            for comment in top_level
            if _comment_issue_refs(comment) & issue_refs
        )
    return comments


def _verify_ops3_protected_lines(jira_data: Any) -> dict[str, Any]:
    issues = _exact_issue_representations(jira_data, "OPS-3")
    if not issues:
        return _result(False, "OPS-3 was not found by exact key; protected lines cannot be verified.")
    comments = _all_issue_comments(jira_data, "OPS-3")
    vendor_terms = ("capital grille", "marriott", "hartwell group")
    violations: list[str] = []
    for comment in comments:
        text = _comment_text(comment)
        lowered = text.casefold()
        if "missing business justification" in lowered and any(
            vendor in lowered for vendor in vendor_terms
        ):
            violations.append(text[:240])
    if violations:
        return _result(
            False,
            "OPS-3 protected-lines violation found across canonical/top-level and "
            f"embedded comments: {violations}",
        )
    return _result(
        True,
        f"Checked {len(comments)} aggregated OPS-3 comment(s) across {len(issues)} exact "
        "issue representation(s); no protected-line violation was found.",
    )


def _channel_values(channels: Any) -> list[dict[str, Any]]:
    if isinstance(channels, dict):
        return [c for c in channels.values() if isinstance(c, dict)]
    if isinstance(channels, list):
        return [c for c in channels if isinstance(c, dict)]
    return []


def _u002_dm_texts(slack_data: Any) -> list[str]:
    if not isinstance(slack_data, dict):
        return []
    messages_by_channel = slack_data.get("messages")
    texts: list[str] = []
    for channel in _channel_values(slack_data.get("channels")):
        if channel.get("is_im") is not True or str(channel.get("user", "")) != "U002":
            continue
        channel_id = str(channel.get("id", ""))
        messages: list[Any] = []
        messages.extend(_unpack_comments(channel.get("messages")))
        if isinstance(messages_by_channel, dict):
            messages.extend(_unpack_comments(messages_by_channel.get(channel_id)))
        for message in messages:
            text = _comment_text(message)
            if text:
                texts.append(text)
    return texts


def _valid_b2_message(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = next((line for line in lines if line.startswith("[T&E Review Flag]")), "")
    if not re.fullmatch(
        r"\[T&E Review Flag\]\s*-\s*Employee ID:\s*EMP-3312(?:\s*\(Rachel Okonkwo\))?",
        header,
        flags=re.IGNORECASE,
    ):
        return False
    date_amount = next((line for line in lines if line.casefold().startswith("expense date:")), "")
    match = re.fullmatch(
        r"Expense Date:\s*([^|]+?)\s*\|\s*Amount:\s*\$144\.00",
        date_amount,
        flags=re.IGNORECASE,
    )
    allowed_dates = {"2026-10-01", "oct 1, 2026", "october 1, 2026"}
    if match is None or match.group(1).strip().casefold() not in allowed_dates:
        return False
    merchant = next((line for line in lines if line.casefold().startswith("merchant:")), "")
    if "vsm branded water bottles" not in merchant.casefold():
        return False
    details = next((line for line in lines if line.casefold().startswith("details:")), "")
    if "shopify promo purchase not found" not in details.casefold():
        return False
    action = next((line for line in lines if line.casefold().startswith("action taken:")), "")
    required_action = (
        "line item rejected",
        "jira",
        "ops-hr-te workflow",
        "please review with your direct report",
    )
    return all(fragment in action.casefold() for fragment in required_action)


def _verify_b2(jira_data: Any, slack_data: Any) -> dict[str, Any]:
    status = _verify_status(jira_data, "OPS-3", "Rejected")
    if not status["pass"]:
        return status
    messages = _u002_dm_texts(slack_data)
    if not any(_valid_b2_message(message) for message in messages):
        return _result(
            False,
            "No U002 DM contained the complete scenario-specific Template B-2 fields: "
            "EMP-3312; Oct 1, 2026; $144.00; VSM Branded Water Bottles; Shopify "
            "promo purchase not found; and the required Jira action.",
        )
    return _result(True, "Complete scenario-specific Template B-2 DM found for U002 after OPS-3 rejection.")


def _top_level_issues(jira_data: Any) -> list[dict[str, Any]]:
    if not isinstance(jira_data, dict):
        return []
    issues = jira_data.get("issues")
    if isinstance(issues, dict):
        return [i for i in issues.values() if isinstance(i, dict)]
    if isinstance(issues, list):
        return [i for i in issues if isinstance(i, dict)]
    return []


def _field_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_with_prefix(lines: list[str], prefix: str) -> str:
    prefix_folded = prefix.casefold()
    return next((line for line in lines if line.casefold().startswith(prefix_folded)), "")


def _valid_b8_description(text: str) -> bool:
    lines = _field_lines(text)
    if not any(line.casefold() == "[t&e manager lookup]" for line in lines):
        return False
    employee = _line_with_prefix(lines, "Employee:")
    if not re.fullmatch(
        r"Employee:\s*Derek Huang\s*\|\s*ID:\s*EMP-4507",
        employee,
        flags=re.IGNORECASE,
    ):
        return False
    report = _line_with_prefix(lines, "OPS-HR-TE / expense report issue:")
    if "ops-4" not in report.casefold():
        return False
    directory = _line_with_prefix(lines, "Directory / People search result:")
    directory_folded = directory.casefold()
    blank_field = re.search(
        r"reporting manager(?: custom)? field (?:is )?blank",
        directory,
        flags=re.IGNORECASE,
    )
    no_result_markers = (
        "no result",
        "no response",
        "no matching",
        "no reporting-manager mapping",
        "returned no match",
    )
    if (
        blank_field is None
        or "people@vanguardshield.com" not in directory_folded
        or not any(marker in directory_folded for marker in no_result_markers)
    ):
        return False
    need = _line_with_prefix(lines, "Need:")
    expected_need = "need: correct manager jira username or slack handle for template b-2 notification."
    return need.rstrip(".").casefold() == expected_need.rstrip(".").casefold()


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


def _email_value(email: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = email.get(field)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
    return ""


def _directory_email_timestamp(mail_data: Any) -> datetime | None:
    if not isinstance(mail_data, dict):
        return None
    timestamps: list[datetime] = []
    for email in mail_data.get("emails", []):
        if not isinstance(email, dict) or str(email.get("folder", "")).casefold() != "sent":
            continue
        to_addr = _email_value(email, "to_addr", "to").casefold()
        body = _email_value(email, "body_text", "body", "content").casefold()
        required = ("derek huang", "emp-4507", "ops-4", "reporting manager")
        if "people@vanguardshield.com" not in to_addr or not all(item in body for item in required):
            continue
        timestamp = _parse_timestamp(email.get("date") or email.get("sent_at") or email.get("created"))
        if timestamp is not None:
            timestamps.append(timestamp)
    return min(timestamps) if timestamps else None


def _issue_created_timestamp(issue: dict[str, Any]) -> datetime | None:
    fields = issue.get("fields")
    value = fields.get("created") if isinstance(fields, dict) else None
    return _parse_timestamp(value or issue.get("created"))


def _verify_b8(jira_data: Any, mail_data: Any) -> dict[str, Any]:
    status = _verify_status(jira_data, "OPS-4", "Rejected")
    if not status["pass"]:
        return status
    lookup_email_at = _directory_email_timestamp(mail_data)
    if lookup_email_at is None:
        return _result(
            False,
            "Template B-8 prerequisite failed: no timestamped Sent email to "
            "people@vanguardshield.com requesting Derek Huang's (EMP-4507) OPS-4 "
            "reporting manager was found.",
        )

    matching_issues: list[dict[str, Any]] = []
    for issue in _top_level_issues(jira_data):
        if _issue_key(issue) in {"OPS-3", "OPS-4", "OPS-5"}:
            continue
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else issue
        summary = str(fields.get("summary", ""))
        summary_folded = re.sub(r"[\u2010-\u2015]", "-", summary).casefold()
        if not summary_folded.startswith("manager lookup needed - t&e exception -"):
            continue
        if "derek huang" not in summary_folded or "emp-4507" not in summary_folded:
            continue
        description = _flatten_adf_text(fields.get("description"))
        if _valid_b8_description(description):
            matching_issues.append(issue)

    if not matching_issues:
        return _result(
            False,
            "No standalone Jira issue contained the exact Derek Huang/EMP-4507 Template "
            "B-8 title and all authoritative description fields.",
        )
    for issue in matching_issues:
        created_at = _issue_created_timestamp(issue)
        if created_at is not None and lookup_email_at <= created_at:
            return _result(
                True,
                "OPS-4 is Rejected; the complete B-8 issue exists; and the timestamped "
                "People Directory lookup email was sent before issue creation.",
            )
    return _result(
        False,
        "Complete B-8 content was found, but its creation timestamp does not prove that "
        "the People Directory lookup email was sent first.",
    )


def _apply_scenario_requirements(
    rubric_id: str,
    result: dict[str, Any],
    external_services_path: Path,
) -> dict[str, Any]:
    """Apply the SOP-critical checks that the legacy inline rubrics omitted."""
    jira_data = _load_json(external_services_path, "jira_state.json")

    if rubric_id == OPS3_PROTECTED_LINES_RUBRIC:
        return _verify_ops3_protected_lines(jira_data)
    if rubric_id == B2_MANAGER_DM_RUBRIC:
        return _verify_b2(jira_data, _load_json(external_services_path, "slack_data.json"))
    if rubric_id == B8_MANAGER_LOOKUP_RUBRIC:
        return _verify_b8(jira_data, _load_json(external_services_path, "mailbox.json"))

    gate: dict[str, Any] | None = None
    if rubric_id in OPS4_POSITIVE_RUBRICS:
        gate = _verify_status(jira_data, "OPS-4", "Rejected")
    elif rubric_id == OPS5_COMPLETION_RUBRIC:
        gate = _verify_status(jira_data, "OPS-5", "Approved")
    if gate is not None and not gate["pass"]:
        return gate
    return result


def _run_one(rubric: dict[str, Any], external_services_path: Path) -> dict[str, Any]:
    rubric_id = str(rubric.get("id") or "rubric")
    code = rubric.get("verifier_code")
    if not isinstance(code, str) or not code.strip():
        return {
            "id": rubric_id,
            "pass": False,
            "score": 0.0,
            "feedback": "rubric has no verifier_code",
        }

    namespace: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        exec(compile(code, f"<{rubric_id}>", "exec"), namespace)
        verify = namespace.get("verify")
        if not callable(verify):
            raise RuntimeError("verifier_code did not define verify()")
        result = _coerce_result(verify(str(WORKDIR), str(external_services_path)))
        result = _apply_scenario_requirements(rubric_id, result, external_services_path)
        return {"id": rubric_id, **result}
    except Exception:
        return {
            "id": rubric_id,
            "pass": False,
            "score": 0.0,
            "feedback": traceback.format_exc(),
        }


def main() -> None:
    rubrics_path = TESTS_DIR / "rubrics.json"
    if not rubrics_path.is_file():
        print("[sop-verifier] ERROR: rubrics.json not found", file=sys.stderr)
        sys.exit(1)

    rubrics = json.loads(rubrics_path.read_text())
    if not isinstance(rubrics, list):
        print("[sop-verifier] ERROR: rubrics.json must be a list", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="sop-external-services-") as tmp:
        compat_dir = Path(tmp)
        _build_compat_external_services(compat_dir)
        results = [_run_one(r, compat_dir) for r in rubrics]

    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    average_score = round(
        sum(float(r.get("score", 0.0)) for r in results) / total,
        4,
    ) if total else 0.0

    print(f"[sop-verifier] {passed}/{total} rubrics passed; score={average_score:.2f}")
    for result in results:
        status = "PASS" if result.get("pass") else "FAIL"
        feedback = str(result.get("feedback", "")).replace("\n", " ")[:500]
        print(f"  [{status}] {result.get('id')}: {feedback}")

    output = {
        "passed": passed == total,
        "rubrics_passed": passed,
        "rubrics_total": total,
        "score": average_score,
        "rubric_results": results,
    }
    (TESTS_DIR / "results.json").write_text(json.dumps(output, indent=2) + "\n")

    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    (VERIFIER_DIR / "reward.txt").write_text(str(average_score))


if __name__ == "__main__":
    main()
