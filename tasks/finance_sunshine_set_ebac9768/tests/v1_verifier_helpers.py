"""Deterministic helpers for the approved V1 evaluator correction."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterator

import openpyxl


# Seeded (non-empty) cells per workbook/sheet, with a digest of their values. The
# SOP directs the agent to log the chargeback, funding items, cash exception, and
# floorplan variance in these same trackers, so appended rows and newly filled
# blank cells are allowed; only the seeded cell values must be unchanged.
SEEDED_CELL_SNAPSHOT = {
    "chargeback_tracker.xlsx": {
        "Chargebacks": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","I1","J1","K1","L1","A2","B2","C2","D2","E2","F2","G2","H2","I2","J2","K2","L2"],"digest":"eb99de7e5aad5694d048f49a46df3121c9993ab50b8843239a26e53acb1646ee"},
    },
    "daily_cash_log.xlsx": {
        "Cash Log": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","A2","B2","C2","D2","E2","F2","G2","H2","A3","B3","C3","D3","E3","F3","G3","H3","A4","B4","C4","D4","E4","F4","G4","H4","A5","B5","C5","D5","E5","F5","G5","H5","A6","B6","C6","D6","E6","F6","G6","H6"],"digest":"fd82332940ac19c7718f9af5960aa4ce412a23ff1390f561da23cb04b133b84e"},
    },
    "deal_log.xlsx": {
        "Deal Log": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","I1","J1","K1","L1","M1","N1","O1","P1","Q1","R1","S1","T1","U1","V1","A2","B2","C2","D2","E2","F2","G2","H2","I2","J2","K2","L2","M2","N2","O2","P2","Q2","S2","T2","U2","V2","A3","B3","C3","D3","E3","F3","G3","H3","I3","J3","K3","L3","M3","N3","O3","P3","Q3","R3","T3","U3","V3","A4","B4","C4","D4","E4","F4","G4","H4","I4","J4","K4","L4","M4","N4","O4","P4","Q4","R4","T4","U4","V4","A5","B5","C5","D5","E5","F5","G5","H5","I5","J5","K5","L5","M5","N5","O5","P5","Q5","R5","S5","T5","U5","V5","A6","B6","C6","D6","E6","F6","G6","H6","I6","J6","K6","L6","M6","N6","O6","P6","Q6","R6","T6","U6","V6","A7","B7","C7","D7","E7","F7","G7","H7","I7","J7","K7","L7","M7","N7","O7","P7","Q7","R7","T7","U7","V7","A8","B8","C8","D8","E8","F8","G8","H8","I8","J8","K8","L8","M8","N8","O8","P8","Q8","R8","T8","U8","V8","A9","B9","C9","D9","E9","F9","G9","H9","I9","J9","K9","L9","M9","N9","O9","P9","Q9","R9","S9","T9","U9","V9","A10","B10","C10","D10","E10","F10","G10","H10","I10","J10","K10","L10","M10","N10","O10","P10","Q10","R10","T10","U10","V10","A11","B11","C11","D11","E11","F11","G11","H11","I11","J11","K11","L11","M11","N11","O11","P11","Q11","R11","T11","U11","V11"],"digest":"a7dfccb8997423ddec9847efc5c3d25cce85e247392370c9e60bd559b699b655"},
        "F&I Products": {"cells":["A1","B1","C1","D1","E1","F1","G1","A2","B2","C2","D2","E2","F2","G2","A3","B3","C3","D3","E3","F3","G3","A4","B4","C4","D4","E4","F4","G4","A5","B5","C5","D5","E5","F5","G5","A6","B6","C6","D6","E6","F6","G6","A7","B7","C7","D7","E7","F7","G7","A8","B8","C8","D8","E8","F8","G8","A9","B9","C9","D9","E9","F9","G9","A10","B10","C10","D10","E10","F10","G10","A11","B11","C11","D11","E11","F11","G11","A12","B12","C12","D12","E12","F12","G12","A13","B13","C13","D13","E13","F13","G13","A14","B14","C14","D14","E14","F14","G14","A15","B15","C15","D15","E15","F15","G15","A16","B16","C16","D16","E16","F16","G16","A17","B17","C17","D17","E17","F17","G17","A18","B18","C18","D18","E18","F18","G18"],"digest":"fe3141771facd3bb08c94251921a8b1617609f2ef84f54efd3b2f551c7fee963"},
    },
    "floorplan_worksheet.xlsx": {
        "Floorplan": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","I1","J1","K1","A2","B2","C2","D2","E2","F2","G2","H2","I2","J2","K2","A3","B3","C3","D3","E3","F3","G3","J3","A4","B4","C4","D4","E4","F4","G4","J4","A5","B5","C5","D5","E5","F5","G5","H5","I5","J5","K5","A6","B6","C6","D6","E6","F6","G6","J6","A7","B7","C7","D7","E7","F7","G7","J7","A8","B8","C8","D8","E8","F8","G8","J8","A9","B9","C9","D9","E9","F9","G9","H9","I9","J9","K9","A10","B10","C10","D10","E10","F10","G10","J10","A11","B11","C11","D11","E11","F11","G11","J11","A12","B12","C12","D12","E12","F12","G12","J12","K12","A13","B13","C13","D13","E13","F13","G13","J13","K13","A14","B14","C14","D14","E14","F14","G14","J14","K14"],"digest":"30389bc06b4b94a544dcb840a949026aa65587e95893fd3d9b5fa91d0d4296c7"},
    },
    "funding_tracker.xlsx": {
        "Funding": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","I1","A2","B2","C2","D2","E2","F2","G2","H2","I2","A3","B3","C3","D3","E3","F3","G3","H3","I3","A4","B4","C4","D4","E4","F4","G4","H4","I4"],"digest":"556a201791540acd04e75e47948a8a275de9502b539bc56a286ad302c10297e8"},
    },
    "trade_payoff_tracker.xlsx": {
        "Payoffs": {"cells":["A1","B1","C1","D1","E1","F1","G1","H1","A2","B2","C2","D2","E2","F2","G2","H2","A3","B3","C3","D3","E3","F3","G3","H3","A4","B4","C4","D4","E4","F4","G4","H4","A5","B5","C5","D5","E5","F5","G5","H5","A6","B6","C6","D6","E6","F6","G6","H6"],"digest":"a0a84812fca0cc17c4090d1bdcdc132e41edf7c6f332694780b82571c7cddfe4"},
    },
}

NOAH = "noah.alvarez@sunshineauto.com"
PRIYA = "priya.bennett@sunshineauto.com"
ELENA = "elena.brooks@sunshineauto.com"

FUNDING_NAME_PATTERNS = {
    NOAH: re.compile(r"noah[.\s]+alvarez|\bnoah\b"),
    ELENA: re.compile(r"elena[.\s]+brooks|\belena\b"),
}
FUNDING_DATE_PATTERN = re.compile(
    r"(?:"
    r"\bapr(?:il)?\s+14(?:th)?(?:\s*,?\s*2026\b|"
    r"(?!\s*,?\s*\d{4}\b))|"
    r"\b2026[-/]0?4[-/]14\b|"
    r"\b0?4[-/]14(?:[-/]2026\b|(?![-/]\d{2,4}\b))"
    r")"
)
FUNDING_CALENDAR_DATE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+"
    r"\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b|"
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?\b"
    r")"
)
FUNDING_EOD_PATTERN = re.compile(
    r"\b(?:eod|eob|end\s+of\s+(?:the\s+)?business(?:\s+day)?)\b"
)
FUNDING_EXACT_CLOCK_PATTERN = re.compile(
    r"\b(?:5(?::00)?\s*pm|17:00)\s*"
    r"(?:e[sd]?t|eastern(?:\s+time)?)\b"
)
FUNDING_DEADLINE_CUE_PATTERN = re.compile(
    r"\b(?:deadline|cutoff|due|by)\b|" + FUNDING_EOD_PATTERN.pattern
)
FUNDING_FIELD_PATTERNS = {
    "lender Wells Fargo": re.compile(r"\bwells\s+fargo\b"),
    "deal SL-2026-0412": re.compile(
        r"\bsl\s*[-–— ]\s*2026\s*[-–— ]\s*0412\b"
    ),
    "original Power of Attorney": re.compile(r"\boriginal\b"),
    "notarized Power of Attorney": re.compile(r"\bnotari[sz]ed\b"),
    "Power of Attorney": re.compile(r"\bpower\s+of\s+attorney\b|\bpoa\b"),
    "payoff letter": re.compile(r"\bpayoff\s+letter\b"),
    "account number": re.compile(r"\baccount\s+(?:number|no\.?|#)\b"),
    "good-through date": re.compile(r"\bgood[\s-]*through(?:\s+date)?\b"),
}

PAYOFF_TOPIC_PATTERN = re.compile(r"\bpayoff\b|trade.{0,30}vari|vari.{0,30}trade")
PAYOFF_VALUE_PATTERNS = {
    "payoff variance $290": re.compile(
        r"(?<![\d,.])\$?\s*290(?:\.00)?(?!\d|[.,]\d)"
    ),
    "original total gross $5,000": re.compile(
        r"(?<![\d,.])\$?\s*5(?:,|\s)?000(?:\.00)?(?!\d|[.,]\d)"
    ),
    "recalculated front gross $2,910": re.compile(
        r"(?<![\d,.])\$?\s*2(?:,|\s)?910(?:\.00)?(?!\d|[.,]\d)"
    ),
    "recalculated total gross $4,710": re.compile(
        r"(?<![\d,.])\$?\s*4(?:,|\s)?710(?:\.00)?(?!\d|[.,]\d)"
    ),
    "tier $51-$500": re.compile(
        r"(?<!\d)\$?\s*51\s*(?:[-–—]+|to|through)\s*"
        r"\$?\s*500(?!\d)"
    ),
}


def _normalized_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return {"iso": value.isoformat()}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    return {"type": type(value).__name__, "text": str(value)}


def _logical_workbook_digest(path: Path) -> str:
    """Hash sheet names, cell coordinates, and values—not XLSX packaging metadata."""

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        sheets = []
        for sheet in workbook.worksheets:
            cells = []
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        cells.append([cell.coordinate, _normalized_value(cell.value)])
            sheets.append([sheet.title, cells])
    finally:
        workbook.close()

    encoded = json.dumps(
        sheets,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seeded_cells_digest(sheet, coordinates: list[str]) -> str:
    payload = json.dumps(
        [[coordinate, _normalized_value(sheet[coordinate].value)] for coordinate in coordinates],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_seeded_workbooks(workspace_path: str) -> dict:
    """Seeded sheets must still exist and every seeded cell must hold its seeded value.

    Appended rows and cells that were blank in the seed are not checked, because the
    SOP itself directs logging into these trackers.
    """

    workspace = Path(workspace_path)
    failures = []
    for filename, sheets in SEEDED_CELL_SNAPSHOT.items():
        path = workspace / filename
        if not path.is_file():
            failures.append(f"{filename}: missing at original filename")
            continue
        try:
            workbook = openpyxl.load_workbook(path, data_only=False)
        except Exception as exc:  # pragma: no cover - exact parser errors vary
            failures.append(f"{filename}: unreadable workbook ({type(exc).__name__})")
            continue
        try:
            for title, expected in sheets.items():
                if title not in workbook.sheetnames:
                    failures.append(f"{filename}: seeded sheet '{title}' missing or renamed")
                    continue
                if _seeded_cells_digest(workbook[title], expected["cells"]) != expected["digest"]:
                    failures.append(f"{filename}: seeded cell values changed on sheet '{title}'")
        finally:
            workbook.close()

    total = len(SEEDED_CELL_SNAPSHOT)
    if failures:
        return {
            "pass": False,
            "score": (total - len(failures)) / total if len(failures) <= total else 0.0,
            "feedback": "Seed workbook preservation failures: " + "; ".join(failures),
        }
    return {
        "pass": True,
        "score": 1.0,
        "feedback": (
            "All six seeded workbooks retain their sheets and seeded cell values; appended "
            "rows, newly filled blank cells, and serialization metadata were ignored."
        ),
    }


def _funding_missing_fields(text: str) -> list[str]:
    lowered = text.lower()
    missing = [
        label
        for label, pattern in FUNDING_FIELD_PATTERNS.items()
        if not pattern.search(lowered)
    ]
    if not _has_funding_deadline(lowered):
        missing.append("April 14 EOD deadline or exact 5:00 PM ET equivalent")
    return missing


def _has_funding_deadline(text: str) -> bool:
    """Recognize the fixed April 14 cutoff without accepting a wrong date."""

    segments = re.split(r"(?:\r?\n)+|(?<=[.!?;])\s+", text)
    facts = []
    for segment in segments:
        calendar_dates = [
            match.group(0)
            for match in FUNDING_CALENDAR_DATE_PATTERN.finditer(segment)
        ]
        facts.append(
            {
                "has_cue": bool(FUNDING_DEADLINE_CUE_PATTERN.search(segment)),
                "has_april_14": bool(FUNDING_DATE_PATTERN.search(segment)),
                "has_conflicting_date": any(
                    not FUNDING_DATE_PATTERN.fullmatch(date)
                    for date in calendar_dates
                ),
                "has_eod": bool(FUNDING_EOD_PATTERN.search(segment)),
                "has_exact_clock": bool(
                    FUNDING_EXACT_CLOCK_PATTERN.search(segment)
                ),
            }
        )

    for fact in facts:
        if fact["has_cue"] and fact["has_eod"] and fact["has_april_14"]:
            return True

    for index, fact in enumerate(facts):
        if not fact["has_cue"] or not fact["has_exact_clock"]:
            continue
        neighbors = facts[max(0, index - 1) : index + 2]
        if any(
            neighbor["has_cue"] and neighbor["has_conflicting_date"]
            for neighbor in neighbors
        ):
            continue
        if fact["has_april_14"]:
            return True
        # In this fixed-date task, an exact ET cutoff is an unambiguous EOD
        # equivalent unless the same or neighboring deadline clause explicitly
        # gives a different calendar date. Unrelated notice dates do not block it.
        if not fact["has_conflicting_date"]:
            return True
    return False


def _slack_messages_reaching_both(slack_data: dict) -> Iterator[str]:
    raw_workspaces = slack_data.get("workspaces")
    workspaces = (
        raw_workspaces if isinstance(raw_workspaces, dict) else {"default": slack_data}
    )
    for workspace in workspaces.values():
        if not isinstance(workspace, dict):
            continue
        users = workspace.get("users") or {}
        channels = workspace.get("channels") or {}
        bot_ids = {
            user_id
            for user_id, user in users.items()
            if isinstance(user, dict) and user.get("is_bot")
        }
        if workspace.get("bot_user_id"):
            bot_ids.add(workspace["bot_user_id"])

        person_ids = {}
        for address in (NOAH, ELENA):
            person_ids[address] = {
                user_id
                for user_id, user in users.items()
                if isinstance(user, dict)
                and ((user.get("profile") or {}).get("email") or "").lower()
                == address
            }

        for channel_id, messages in (workspace.get("messages") or {}).items():
            channel = channels.get(channel_id) or {}
            direct_ids = set(channel.get("members") or [])
            if channel.get("is_im") and channel.get("user"):
                direct_ids.add(channel["user"])
            for message in messages or []:
                if (
                    not isinstance(message, dict)
                    or message.get("user") not in bot_ids
                ):
                    continue
                text = message.get("text") or ""
                lowered = text.lower()
                hits = {}
                for address in (NOAH, ELENA):
                    named = bool(FUNDING_NAME_PATTERNS[address].search(lowered))
                    mentioned = any(
                        "<@" + user_id.lower() + ">" in lowered
                        for user_id in person_ids[address]
                    )
                    direct = bool(person_ids[address] & direct_ids)
                    hits[address] = named or mentioned or direct
                if hits[NOAH] and hits[ELENA]:
                    yield text


def verify_funding_fields(external_services_path: str | None) -> dict:
    if external_services_path is None:
        return {
            "pass": False,
            "score": 0.0,
            "feedback": (
                "No external services path provided; cannot inspect funding "
                "communications"
            ),
        }

    service_dir = Path(external_services_path)
    candidate_texts = []
    mailbox_path = service_dir / "mailbox.json"
    if mailbox_path.is_file():
        with mailbox_path.open("r", encoding="utf-8") as handle:
            mailbox = json.load(handle)
        for email in mailbox.get("emails", []):
            if (email.get("folder") or "").lower() != "sent":
                continue
            recipients = (
                (email.get("to_addr") or "")
                + " "
                + (email.get("cc_addr") or "")
            ).lower()
            if NOAH in recipients and ELENA in recipients:
                candidate_texts.append(
                    (email.get("subject") or "")
                    + "\n"
                    + (email.get("body_text") or "")
                )

    slack_path = next(
        (
            service_dir / name
            for name in ("slack.json", "slack_data.json")
            if (service_dir / name).is_file()
        ),
        None,
    )
    if slack_path is not None:
        with slack_path.open("r", encoding="utf-8") as handle:
            candidate_texts.extend(_slack_messages_reaching_both(json.load(handle)))
    if not mailbox_path.is_file() and slack_path is None:
        return {
            "pass": False,
            "score": 0.0,
            "feedback": "Neither mailbox.json nor Slack service state was found",
        }

    best_missing = list(FUNDING_FIELD_PATTERNS) + [
        "April 14 EOD deadline or exact 5:00 PM ET equivalent"
    ]
    for text in candidate_texts:
        missing = _funding_missing_fields(text)
        if not missing:
            return {
                "pass": True,
                "score": 1.0,
                "feedback": (
                    "One joint Noah/Elena funding communication contains the exact "
                    "Wells deal, deadline, and required stipulation fields."
                ),
            }
        if len(missing) < len(best_missing):
            best_missing = missing
    return {
        "pass": False,
        "score": 0.0,
        "feedback": (
            "No single joint Noah/Elena funding communication contains every "
            f"required field. Best candidate missing: {best_missing}"
        ),
    }


def verify_payoff_values(external_services_path: str | None) -> dict:
    if external_services_path is None:
        return {
            "pass": False,
            "score": 0.0,
            "feedback": "No external services path provided; cannot inspect payoff email",
        }
    mailbox_path = Path(external_services_path) / "mailbox.json"
    if not mailbox_path.is_file():
        return {"pass": False, "score": 0.0, "feedback": "mailbox.json not found"}
    with mailbox_path.open("r", encoding="utf-8") as handle:
        mailbox = json.load(handle)

    best_missing = list(PAYOFF_VALUE_PATTERNS)
    found_candidate = False
    for email in mailbox.get("emails", []):
        if (email.get("folder") or "").lower() != "sent":
            continue
        recipients = (
            (email.get("to_addr") or "") + " " + (email.get("cc_addr") or "")
        ).lower()
        if PRIYA not in recipients or ELENA not in recipients:
            continue
        text = (email.get("subject") or "") + "\n" + (email.get("body_text") or "")
        lowered = text.lower()
        if not PAYOFF_TOPIC_PATTERN.search(lowered):
            continue
        found_candidate = True
        missing = [
            label
            for label, pattern in PAYOFF_VALUE_PATTERNS.items()
            if not pattern.search(lowered)
        ]
        if not missing:
            return {
                "pass": True,
                "score": 1.0,
                "feedback": (
                    "One joint Priya/Elena payoff email contains every exact "
                    "SOP-required numeric field; prose quality and label semantics "
                    "were not graded."
                ),
            }
        if len(missing) < len(best_missing):
            best_missing = missing
    if not found_candidate:
        return {
            "pass": False,
            "score": 0.0,
            "feedback": "No joint Priya/Elena trade payoff email was found",
        }
    return {
        "pass": False,
        "score": 0.0,
        "feedback": (
            "No single joint Priya/Elena payoff email contains every required "
            f"exact value. Best candidate missing: {best_missing}"
        ),
    }
