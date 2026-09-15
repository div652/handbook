"""Task-local deterministic workbook-preservation verifiers."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl


SCOTT_IDENTIFIERS = (
    "scott young",
    "scott.young@ridgelinegear.com",
    "young.s@gmail.com",
)

# These fingerprints were generated from the task's authoritative initial
# workbooks using _logical_snapshot(). They cover sheet names/order, every
# populated coordinate and value/formula, and merged ranges. XLSX package
# metadata, styles, and ZIP serialization details are intentionally excluded.
SEEDED_LOGICAL_SNAPSHOTS = {
    "employee_roster.xlsx": {
        "sha256": "c56408d27ff65245ade99488f829482a2ce9484a5b73e661d3c23f7debb68639",
        "sheet_names": ["Employee Roster"],
        "populated_cells": 364,
    },
    "hfwa_balance_tracker.xlsx": {
        "sha256": "614cc9e40e3888fb3623d4231af46f18c3919f666f8a1879b9b80dddf5374598",
        "sheet_names": ["HFWA Balance Tracker"],
        "populated_cells": 156,
    },
    "hours_worked_log.xlsx": {
        "sha256": "205acd41b4e24c7999d453d9afc89e6136970839cd3b9cfe430018211c28d51d",
        "sheet_names": ["Hours Worked Log"],
        "populated_cells": 130,
    },
}


def _logical_value(cell: Any) -> list[Any]:
    """Return a JSON-safe, type-aware representation of a populated cell."""
    value = cell.value
    if cell.data_type == "f":
        return ["formula", str(value)]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, time):
        return ["time", value.isoformat()]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ["number", str(value)]
        number = Decimal(str(value))
        if number == number.to_integral_value():
            normalized = str(number.quantize(Decimal("1")))
        else:
            normalized = format(number.normalize(), "f")
        return ["number", normalized]
    if isinstance(value, str):
        return ["string", value]
    return [type(value).__name__, repr(value)]


def _populated_cells(worksheet: Any) -> list[Any]:
    """Return populated cells without expanding sparse worksheet dimensions."""
    cells = [cell for cell in worksheet._cells.values() if cell.value is not None]
    return sorted(cells, key=lambda cell: (cell.row, cell.column))


def _logical_snapshot(workbook: Any) -> dict[str, Any]:
    """Capture only logical workbook semantics relevant to this task."""
    sheets = []
    for worksheet in workbook.worksheets:
        cells = [
            [cell.coordinate, _logical_value(cell)]
            for cell in _populated_cells(worksheet)
        ]
        sheets.append(
            {
                "name": worksheet.title,
                "cells": cells,
                "merges": sorted(str(rng) for rng in worksheet.merged_cells.ranges),
            }
        )
    return {
        "sheet_names": list(workbook.sheetnames),
        "sheets": sheets,
    }


def _snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _find_scott(workbook: Any) -> list[str]:
    hits = []
    for worksheet in workbook.worksheets:
        for cell in _populated_cells(worksheet):
            text = str(cell.value).casefold()
            matched = [identifier for identifier in SCOTT_IDENTIFIERS if identifier in text]
            if matched:
                hits.append(f"{worksheet.title}!{cell.coordinate} ({', '.join(matched)})")
    return hits


def verify_seeded_workbook(workspace_path: str, filename: str) -> dict[str, Any]:
    expected = SEEDED_LOGICAL_SNAPSHOTS[filename]
    workbook_path = Path(workspace_path) / filename
    if not workbook_path.is_file():
        return {
            "pass": False,
            "score": 0.0,
            "feedback": f"Required workbook '{filename}' is missing.",
        }

    try:
        workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    except Exception as exc:
        return {
            "pass": False,
            "score": 0.0,
            "feedback": f"Required workbook '{filename}' could not be opened: {exc}",
        }

    try:
        scott_hits = _find_scott(workbook)
        if scott_hits:
            return {
                "pass": False,
                "score": 0.0,
                "feedback": (
                    f"Workbook '{filename}' contains prohibited Scott Young onboarding data: "
                    + "; ".join(scott_hits[:10])
                ),
            }

        snapshot = _logical_snapshot(workbook)
        fingerprint = _snapshot_fingerprint(snapshot)
        populated_cells = sum(len(sheet["cells"]) for sheet in snapshot["sheets"])
        if fingerprint != expected["sha256"]:
            return {
                "pass": False,
                "score": 0.0,
                "feedback": (
                    f"Workbook '{filename}' does not match its seeded logical snapshot "
                    "(sheet names/order, populated coordinates/values/formulas, or merges changed). "
                    f"Expected sheets={expected['sheet_names']}, cells={expected['populated_cells']}, "
                    f"sha256={expected['sha256']}; found sheets={snapshot['sheet_names']}, "
                    f"cells={populated_cells}, sha256={fingerprint}."
                ),
            }

        return {
            "pass": True,
            "score": 1.0,
            "feedback": (
                f"Workbook '{filename}' matches the seeded logical snapshot and contains "
                "no Scott Young identifiers."
            ),
        }
    finally:
        workbook.close()


def verify_employee_roster(workspace_path, external_services_path=None):
    return verify_seeded_workbook(workspace_path, "employee_roster.xlsx")


def verify_hfwa_balance_tracker(workspace_path, external_services_path=None):
    return verify_seeded_workbook(workspace_path, "hfwa_balance_tracker.xlsx")


def verify_hours_worked_log(workspace_path, external_services_path=None):
    return verify_seeded_workbook(workspace_path, "hours_worked_log.xlsx")
