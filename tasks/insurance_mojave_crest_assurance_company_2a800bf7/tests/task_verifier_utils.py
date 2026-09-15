"""Shared verifier logic for the Mojave Crest standing-intake task."""

from __future__ import annotations

import base64
import io
import json
import re
import subprocess
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Iterable


ARI_ADDRESS = "a.costa@mojavecrest.com"
PROVIDER_ADDRESS = "asolis@griffinmedical.org"
MEMBER_ADDRESS = "j.arden.71@gmail.com"
TARGET_SUBJECT = "Mojave Crest Request KPX658320914 - Information Needed"

SENDER_FIELDS = ("from_addr", "from", "sender")
RECIPIENT_FIELDS = ("to_addr", "to", "cc_addr", "cc", "bcc_addr", "bcc")

REQUIRED_PHRASES = {
    "In order to complete our review": r"in\s+order\s+to\s+complete\s+our\s+review",
    "within 15 calendar days": r"within\s+15\s+calendar\s+days",
    "portal.mojavecrest.com": r"portal\.\s*mojavecrest\.\s*com",
    "Ari Costa": r"ari\s+costa",
    "Appeals & Grievances Coordinator": r"appeals\s*&\s*grievances\s+coordinator",
    "Mojave Crest Assurance Company": r"mojave\s+crest\s+assurance\s+company",
    "Phone: (702) 555-0148": r"phone\s*:\s*\(?702\)?[\s.-]*555[\s.-]*0148",
}


def _field_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key in ("email", "address", "addr", "value"):
            if value.get(key):
                name = str(value.get("name") or value.get("display_name") or "").strip()
                address = str(value[key]).strip()
                yield f"{name} <{address}>" if name else address
                return
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _field_strings(item)
        return
    yield str(value)


def _mailboxes(message: dict[str, Any], fields: Iterable[str]) -> list[tuple[str, str]]:
    raw_values: list[str] = []
    for field in fields:
        raw_values.extend(_field_strings(message.get(field)))
    parsed = [
        (name.strip().casefold(), address.strip().casefold())
        for name, address in getaddresses(raw_values)
        if name.strip() or address.strip()
    ]
    # email.utils treats an unquoted name-only field such as ``Jules Arden``
    # as a local address. Preserve an exact name-only recipient as a name.
    for raw in raw_values:
        if "@" not in raw and raw.strip().casefold() == "jules arden":
            parsed.append(("jules arden", ""))
    return parsed


def _has_exact_sender(message: dict[str, Any], address: str = ARI_ADDRESS) -> bool:
    target = address.casefold()
    parsed_addresses = {
        parsed_address
        for _, parsed_address in _mailboxes(message, SENDER_FIELDS)
        if parsed_address
    }
    return parsed_addresses == {target}


def _has_recipient(
    message: dict[str, Any], *, address: str | None = None, name: str | None = None
) -> bool:
    target_address = address.casefold() if address else None
    target_name = name.casefold() if name else None
    for parsed_name, parsed_address in _mailboxes(message, RECIPIENT_FIELDS):
        if target_address and parsed_address == target_address:
            return True
        if target_name and parsed_name == target_name:
            return True
    return False


# The mailbox mock has no durable "sent" marker: a sent message can later be moved
# into any custom folder, so folder == "Sent" cannot be required. What can be
# excluded are the folders that mean the message was never sent.
UNSENT_FOLDERS = frozenset({"drafts", "scheduled", "trash"})


def _is_unsent(message: dict[str, Any]) -> bool:
    folder = str(message.get("folder") or "").strip().casefold()
    return folder in UNSENT_FOLDERS


def _is_provider_outbound(message: dict[str, Any]) -> bool:
    if _is_unsent(message):
        return False
    return _has_exact_sender(message) and _has_recipient(message, address=PROVIDER_ADDRESS)


def _load_mailbox(external_services_path: str | None) -> tuple[list[dict[str, Any]] | None, str | None]:
    if external_services_path is None:
        return None, "external_services_path is None; cannot check mailbox.json"
    mailbox_path = Path(external_services_path) / "mailbox.json"
    if not mailbox_path.is_file():
        return None, "mailbox.json not found"
    try:
        data = json.loads(mailbox_path.read_text())
    except Exception as exc:
        return None, f"Could not read mailbox.json: {exc}"
    emails = data.get("emails", []) if isinstance(data, dict) else []
    if not isinstance(emails, list):
        return None, "mailbox.json field 'emails' is not a list"
    return [email for email in emails if isinstance(email, dict)], None


def _fail(feedback: str) -> dict[str, Any]:
    return {"pass": False, "score": 0.0, "feedback": feedback}


def _pass(feedback: str) -> dict[str, Any]:
    return {"pass": True, "score": 1.0, "feedback": feedback}


def _subject_matches(subject: str) -> bool:
    if subject == TARGET_SUBJECT:
        return True
    normalized = re.sub(r"[\s\u2013\u2014]+", " ", subject).strip()
    normalized_target = re.sub(r"[\s\u2013\u2014]+", " ", TARGET_SUBJECT).strip()
    hyphenated = re.sub(r"[\u2013\u2014]", "-", subject).strip()
    return normalized == normalized_target or hyphenated == TARGET_SUBJECT


def verify_provider_subject(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    del workspace_path
    emails, error = _load_mailbox(external_services_path)
    if error:
        return _fail(error)

    wrong_subjects = []
    for message in emails or []:
        if not _is_provider_outbound(message):
            continue
        subject = str(message.get("subject") or "").strip()
        if _subject_matches(subject):
            return _pass(
                "Found outbound email from a.costa@mojavecrest.com to "
                f"asolis@griffinmedical.org with subject '{subject}'."
            )
        wrong_subjects.append(subject)

    if wrong_subjects:
        return _fail(
            f"Found outbound email(s) to the provider, but subject did not match "
            f"'{TARGET_SUBJECT}': {wrong_subjects[:5]}"
        )
    return _fail(
        "No outbound email found with exact sender a.costa@mojavecrest.com and "
        f"parsed recipient asolis@griffinmedical.org. Total emails: {len(emails or [])}."
    )


def _attachment_items(message: dict[str, Any]) -> list[Any]:
    attachments = message.get("attachments")
    items = list(attachments) if isinstance(attachments, list) else ([attachments] if attachments else [])
    singular = message.get("attachment")
    if singular:
        items.extend(singular if isinstance(singular, list) else [singular])
    return items


def _attachment_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("filename") or item.get("name") or item.get("path") or "")
    return ""


def _extract_pdf(source: Path | io.BytesIO) -> str:
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    if text.strip() or not isinstance(source, Path):
        return text
    proc = subprocess.run(
        ["pdftotext", "-layout", str(source), "-"],
        capture_output=True,
        timeout=60,
    )
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""


def _extract_docx(source: Path | io.BytesIO) -> str:
    import docx

    document = docx.Document(source)
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            paragraphs.extend(cell.text for cell in row.cells)
    return "\n".join(paragraphs)


def _extract_source_text(name: str, source: Path | bytes) -> str:
    suffix = Path(name).suffix.casefold()
    file_source: Path | io.BytesIO = source if isinstance(source, Path) else io.BytesIO(source)
    if suffix == ".pdf":
        return _extract_pdf(file_source)
    if suffix == ".docx":
        return _extract_docx(file_source)
    if suffix in {".txt", ".md", ".csv", ".html", ".htm", ".rtf"}:
        if isinstance(source, Path):
            return source.read_text(errors="replace")
        return source.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported attachment type '{suffix or '<none>'}'")


def _extract_attachment(item: Any, workspace_path: str) -> tuple[str, str]:
    name = _attachment_name(item)
    label = name or "unnamed attachment"
    try:
        if isinstance(item, dict) and item.get("content_base64"):
            raw = base64.b64decode(str(item["content_base64"]), validate=True)
            text = _extract_source_text(name, raw)
        elif isinstance(item, dict) and isinstance(item.get("content"), str):
            text = str(item["content"])
        else:
            if not name:
                return "", f"{label}: no filename or extractable content"
            workspace = Path(workspace_path)
            candidates = [workspace / name]
            if Path(name).name == name:
                candidates.extend(workspace.rglob(name))
            source = next((candidate for candidate in candidates if candidate.is_file()), None)
            if source is None:
                return "", f"{label}: referenced file not found"
            text = _extract_source_text(name, source)
    except Exception as exc:
        return "", f"{label}: text extraction failed ({exc})"
    if not text.strip():
        return "", f"{label}: no extractable text"
    return text, ""


def _missing_phrases(text: str) -> list[str]:
    return [
        label
        for label, pattern in REQUIRED_PHRASES.items()
        if not re.search(pattern, text, re.IGNORECASE)
    ]


def verify_provider_content(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    emails, error = _load_mailbox(external_services_path)
    if error:
        return _fail(error)

    candidates = [message for message in emails or [] if _is_provider_outbound(message)]
    if not candidates:
        return _fail(
            "No outbound email found with exact sender a.costa@mojavecrest.com and "
            "parsed recipient asolis@griffinmedical.org."
        )

    candidate_failures = []
    for message in candidates:
        body = str(message.get("body_text") or message.get("body") or "").strip()
        evidence = [("email body", body)] if body else []
        extraction_errors = []
        for item in _attachment_items(message):
            text, extraction_error = _extract_attachment(item, workspace_path)
            if text:
                evidence.append((_attachment_name(item) or "attachment", text))
            elif extraction_error:
                extraction_errors.append(extraction_error)

        salutation_ok = any(re.search(r"avery\s+solis", text, re.IGNORECASE) for _, text in evidence)
        complete_source = next(
            ((label, text) for label, text in evidence if not _missing_phrases(text)),
            None,
        )
        if salutation_ok and complete_source:
            return _pass(
                "Email correctly addresses Avery Solis and contains every required A-2 "
                f"phrase in {complete_source[0]}."
            )

        problems = []
        if not salutation_ok:
            problems.append("missing addressee 'Avery Solis' or 'Dr. Avery Solis'")
        if not complete_source:
            source_missing = {
                label: _missing_phrases(text) for label, text in evidence
            }
            problems.append(
                "no single readable body/attachment contains all required A-2 phrases; "
                f"missing by source: {source_missing or {'none': list(REQUIRED_PHRASES)}}"
            )
        if extraction_errors:
            problems.append("unreadable attachment evidence: " + "; ".join(extraction_errors))
        candidate_failures.append(", ".join(problems))

    return _fail("Provider email content did not verify: " + " | ".join(candidate_failures))


def verify_no_appeals_log_row(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    del external_services_path
    try:
        import openpyxl
    except ImportError:
        return _fail("openpyxl not available")

    matches = list(Path(workspace_path).rglob("appeals_log_master.xlsx"))
    if not matches:
        return _fail(
            "Authoritative workbook appeals_log_master.xlsx is missing; cannot verify "
            "that Member ID KPX658320914 has no row."
        )
    workbook_path = matches[0]
    try:
        workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    except Exception as exc:
        return _fail(f"Error reading appeals_log_master.xlsx: {exc}")

    member_id = "KPX658320914"
    try:
        for sheet_name in workbook.sheetnames:
            for row in workbook[sheet_name].iter_rows(values_only=True):
                if any(cell is not None and str(cell).strip() == member_id for cell in row):
                    return _fail(
                        f"Found Member ID '{member_id}' in appeals_log_master.xlsx "
                        f"sheet '{sheet_name}'."
                    )
    finally:
        workbook.close()
    return _pass(f"No entry for Member ID '{member_id}' found in appeals_log_master.xlsx.")


def _is_target_correspondence(message: dict[str, Any]) -> bool:
    # A drafted or scheduled acknowledgment was never sent, so it is not a
    # prohibited sent acknowledgment.
    if _is_unsent(message) or not _has_exact_sender(message):
        return False
    return (
        _has_recipient(message, address=PROVIDER_ADDRESS)
        or _has_recipient(message, address=MEMBER_ADDRESS)
        or _has_recipient(message, name="Jules Arden")
    )


def _is_negated_mention(text: str, start: int, end: int) -> bool:
    text = text.replace("\u2019", "'")
    sentence_start = max(text.rfind(char, 0, start) for char in ".!?;\n") + 1
    before_words = re.findall(r"[\w']+", text[sentence_start:start])
    for word in before_words[-4:]:
        word = word.casefold()
        if word in {"no", "not", "without", "never", "cannot", "unable", "neither", "nor"} or word.endswith("n't"):
            return True
    sentence_ends = [index for index in (text.find(char, end) for char in ".!?;\n") if index != -1]
    after = text[end:min(sentence_ends)] if sentence_ends else text[end:]
    if re.match(
        r"\s*(?:[\w']+\s+){0,3}(?:has|have|had|was|were|is|are|will|does|do|did|can)\s+not\b",
        after,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.match(
            r"\s*(?:[\w']+\s+){0,3}(?:hasn't|haven't|hadn't|wasn't|weren't|isn't|aren't|won't|doesn't|don't|didn't|can't|cannot)\b",
            after,
            re.IGNORECASE,
        )
    )


def _has_affirmative_match(pattern: str, text: str) -> bool:
    return any(
        not _is_negated_mention(text, match.start(), match.end())
        for match in re.finditer(pattern, text, re.IGNORECASE)
    )


def verify_no_acknowledgment(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    del workspace_path
    emails, error = _load_mailbox(external_services_path)
    if error:
        return _fail(error)

    forbidden_patterns = (
        r"case\s*id",
        r"case\s*number",
        r"appeal has been received",
        r"appeal is being processed",
        r"your appeal",
        r"case\s*#",
    )
    violations = []
    for message in emails or []:
        if not _is_target_correspondence(message):
            continue
        subject = str(message.get("subject") or "")
        body = str(message.get("body_text") or message.get("body") or "")
        for pattern in forbidden_patterns:
            if _has_affirmative_match(pattern, body) or _has_affirmative_match(pattern, subject):
                recipients = _mailboxes(message, RECIPIENT_FIELDS)
                violations.append(
                    f"Outbound email to {recipients} contains forbidden pattern '{pattern}'"
                )
                break
    if violations:
        return _fail("; ".join(violations))
    return _pass(
        "No outbound emails to Avery Solis or Jules Arden contain appeal "
        "acknowledgment or Case ID references."
    )
