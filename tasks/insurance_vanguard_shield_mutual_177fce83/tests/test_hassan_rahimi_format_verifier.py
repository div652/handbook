#!/usr/bin/env python3
"""Formatting-tolerance regressions for the Amina Hassan and Leila Rahimi workbook verifiers.

Values that are present but formatted differently (date styles, label colons, sheet-name
variants, currency strings, blank denied cells) must pass. Quoted text must never pass:
the SOP and the task instructions spell these values out verbatim, without quotes.
"""

from __future__ import annotations

import datetime
import json
import re
import tempfile
import unittest
from pathlib import Path

import openpyxl


TESTS_DIR = Path(__file__).resolve().parent
RUBRICS = {
    rubric["id"]: rubric
    for rubric in json.loads((TESTS_DIR / "rubrics.json").read_text())
}
HASSAN_LINES = "f3da8b58-f81a-45a4-82eb-ade5d4f85521"
HASSAN_SUMMARY = "d5283083-687f-489b-9202-dd746e84afc2"
RAHIMI_LINES = "81155ee6-2fb9-4155-a4a3-7b02b7eb9d34"
RAHIMI_SUMMARY = "3f5acb9f-fb7d-482f-aa7d-90a4cae678bc"
ALL_FOUR = (HASSAN_LINES, HASSAN_SUMMARY, RAHIMI_LINES, RAHIMI_SUMMARY)

HEADERS = [
    "Jira Key", "Date of Purchase", "Merchant", "Amount", "Expense Category",
    "Approved Amount", "Denied Amount", "Denial Reason",
]
# The OPS-13 date is taken from the rubric text so the two cannot drift apart.
OPS13_DATE = re.search(
    r"OPS-13 \((\d{1,2}/\d{1,2}/\d{4})", RUBRICS[HASSAN_LINES]["rubric_text"]
).group(1)

# (key, date, merchant, amount, category, approved, denied)
HASSAN_ROWS = (
    ("OPS-1", "4/23/2026", "Shopify (promotional)", 43.89, "Client Relations Expense", 43.89, 0),
    ("OPS-2", "5/5/2026", "Uber", 63.18, "Staff Expense", 63.18, 0),
    ("OPS-3", "5/6/2026", "Blackstone Chophouse", 46.86, "Staff Expense", 46.86, 0),
    ("OPS-4", "5/5/2026", "Delta", 389.75, "Staff Expense", 389.75, 0),
    ("OPS-5", "5/6/2026", "Helios Coffee Shop", 24.75, "Staff Expense", 24.75, 0),
    ("OPS-6", "5/6/2026", "Gold Coast Eatery", 27.01, "Staff Expense", 27.01, 0),
    ("OPS-7", "5/6/2026", "Asgard Restaurant", 541.33, "Client Relations Expense", 541.33, 0),
    ("OPS-8", "5/7/2026", "Helios Coffee Shop", 24.75, "Staff Expense", 24.75, 0),
    ("OPS-9", "5/7/2026", "Pilsen Table", 18.74, "Staff Expense", 18.74, 0),
    ("OPS-10", "5/7/2026", "The Greektown Table", 45.75, "Staff Expense", 45.75, 0),
    ("OPS-11", "5/8/2026", "Helios Coffee Shop", 24.48, "Staff Expense", 24.48, 0),
    ("OPS-12", "5/8/2026", "Wicker Park Kitchen", 28.67, "Staff Expense", 28.67, 0),
    ("OPS-13", OPS13_DATE, "Melody Bistro", 747.49, "Client Relations Expense", 747.49, 0),
    ("OPS-14", "5/9/2026", "Uber", 59.80, "Staff Expense", 59.80, 0),
    ("OPS-15", "5/9/2026", "Helios Coffee Shop", 22.55, "Staff Expense", 22.55, 0),
    ("OPS-16", "5/9/2026", "Bucktown Bites", 33.02, "Staff Expense", 33.02, 0),
    ("OPS-17", "5/5/2026 - 5/8/2026", "Hyatt Regency Chicago", 2098.94, "Staff Expense", 2098.94, 0),
)
HASSAN_SUMMARY_ROWS = (
    ("Jira Key", "OPS-18"),
    ("Total Approved", 4240.96),
    ("Total Denied", 0),
    ("Final Status", "Approved"),
    ("Manager Notified", "N"),
    ("Comments", "T&E review complete. All expenses approved."),
)
RAHIMI_ROWS = (
    ("OPS-40", "4/21/2026", "Shopify (client gifts)", 119.54, "Client Relations Expense", 119.54, 0),
    ("OPS-41", "5/5/2026", "The Greektown Table", 47.96, "Staff Expense", 47.96, 0),
    ("OPS-42", "5/5/2026", "Delta", 384.40, "Staff Expense", 384.40, 0),
    ("OPS-43", "5/6/2026", "Helios Coffee Shop", 10.69, "Staff Expense", 10.69, 0),
    ("OPS-44", "5/6/2026", "The Riverwalk Grille", 21.72, "Staff Expense", 21.72, 0),
    ("OPS-45", "5/7/2026", "Helios Coffee Shop", 12.40, "Staff Expense", 12.40, 0),
    ("OPS-46", "5/7/2026", "Gold Coast Eatery", 28.94, "Staff Expense", 28.94, 0),
    ("OPS-47", "5/7/2026", "Sable & Oak Kitchen", 37.76, "Staff Expense", 37.76, 0),
    ("OPS-48", "5/8/2026", "Helios Coffee Shop", 12.35, "Staff Expense", 12.35, 0),
    ("OPS-49", "5/8/2026", "Pilsen Table", 24.81, "Staff Expense", 24.81, 0),
    ("OPS-50", "5/8/2026", "Lock & Lantern Escape Room", 308.61, "Client Relations Expense", 192.88, 115.73),
    ("OPS-51", "5/9/2026", "Helios Coffee Shop", 12.13, "Staff Expense", 12.13, 0),
    ("OPS-52", "5/9/2026", "Wicker Park Kitchen", 26.13, "Staff Expense", 26.13, 0),
    ("OPS-53", "5/9/2026", "Cosa Nostra Cucina", 49.06, "Staff Expense", 49.06, 0),
    ("OPS-54", "5/5/2026 - 5/9/2026", "Hyatt Regency Chicago", 1916.99, "Staff Expense", 1916.99, 0),
    ("OPS-55", "5/10/2026", "Uber", 57.00, "Staff Expense", 57.00, 0),
    ("OPS-56", "5/10/2026", "Helios Coffee Shop", 11.85, "Staff Expense", 11.85, 0),
)
RAHIMI_SUMMARY_ROWS = (
    ("Jira Key", "OPS-57"),
    ("Total Approved", 2966.61),
    ("Total Denied", 115.73),
    ("Final Status", "Partially Approved"),
    ("Manager Notified", "N"),
    ("Comments", "T&E review complete. Expenses approved except where noted."),
)
SHEETS = (
    ("Amina Hassan", HASSAN_ROWS, HASSAN_SUMMARY_ROWS),
    ("Leila Rahimi", RAHIMI_ROWS, RAHIMI_SUMMARY_ROWS),
)


def load_verifier(rubric_id: str):
    namespace: dict[str, object] = {"__builtins__": __builtins__}
    exec(compile(RUBRICS[rubric_id]["verifier_code"], f"<{rubric_id}>", "exec"), namespace)
    return namespace["verify"]


def mdy(text: str) -> datetime.date:
    month, day, year = (int(part) for part in text.split("/"))
    return datetime.date(year, month, day)


def identity(value):
    return value


def write_workbook(
    workspace: Path,
    *,
    key=identity,
    date=identity,
    text=identity,
    amount=identity,
    label=identity,
    marker=identity,
    denied_zero=0,
    sheet_names=("Amina Hassan", "Leila Rahimi"),
    header_row: int = 1,
    formulas: bool = False,
) -> None:
    """Write both sheets, passing every cell through the matching style callable."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for sheet_name, (_, rows, summary) in zip(sheet_names, SHEETS):
        sheet = workbook.create_sheet(sheet_name)
        if header_row > 1:
            sheet.cell(row=1, column=1, value=f"Expense report for {sheet_name}")
        for col, header in enumerate(HEADERS, 1):
            sheet.cell(row=header_row, column=col, value=header)
        r = header_row
        for jira_key, when, merchant, amt, category, approved, denied in rows:
            r += 1
            denied_value = denied_zero if denied == 0 else denied
            approved_value = f"=D{r}-G{r}" if formulas else amount(approved)
            values = [
                key(jira_key), date(when), text(merchant), amount(amt), text(category),
                approved_value, denied_value, None if denied == 0 else "Tickets exceed attendees",
            ]
            for col, value in enumerate(values, 1):
                sheet.cell(row=r, column=col, value=value)
        r += 2
        sheet.cell(row=r, column=1, value=marker("Report Summary"))
        for name, value in summary:
            r += 1
            if name == "Jira Key":
                value = key(value)
            elif isinstance(value, str):
                value = text(value)
            elif formulas and name == "Total Approved":
                value = f"=SUM(F{header_row + 1}:F{header_row + len(rows)})"
            else:
                value = amount(value)
            sheet.cell(row=r, column=1, value=label(name))
            sheet.cell(row=r, column=2, value=value)
    workbook.save(workspace / "expense_reports.xlsx")
    workbook.close()


def long_date(when: str) -> str:
    if " - " in when:
        start, end = (mdy(part) for part in when.split(" - "))
        return f"{start:%B} {start.day}–{end.day}, {end.year}"
    d = mdy(when)
    return f"{d:%B} {d.day}, {d.year}"


def numeric_style(fmt: str, separator: str = " - "):
    def style(when: str) -> str:
        return separator.join(mdy(part).strftime(fmt) for part in when.split(" - "))
    return style


class HassanRahimiFormatVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifiers = {rubric_id: load_verifier(rubric_id) for rubric_id in ALL_FOUR}

    def run_all(self, **style) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_workbook(workspace, **style)
            return {rubric_id: verify(str(workspace)) for rubric_id, verify in self.verifiers.items()}

    def assert_all_pass(self, results: dict[str, dict], context: str) -> None:
        for rubric_id, result in results.items():
            self.assertTrue(result["pass"], f"{context}: {rubric_id}: {result['feedback']}")

    def assert_fail_mentions(self, result: dict, needle: str, context: str) -> None:
        self.assertFalse(result["pass"], f"{context}: expected failure but passed")
        self.assertIn(needle, result["feedback"], context)

    # ---- values present, formatted differently: accepted -------------------------------

    def test_clean_workbook_passes(self) -> None:
        self.assert_all_pass(self.run_all(), "clean workbook")

    def test_date_styles_accepted(self) -> None:
        styles = {
            "datetime cells": lambda w: w if " - " in w else datetime.datetime.combine(mdy(w), datetime.time()),
            "ISO text": numeric_style("%Y-%m-%d"),
            "ISO text with time": lambda w: numeric_style("%Y-%m-%d")(w) if " - " in w else f"{mdy(w):%Y-%m-%d} 00:00:00",
            "zero-padded": numeric_style("%m/%d/%Y"),
            "two-digit year": numeric_style("%m/%d/%y"),
            "dashed numeric": numeric_style("%m-%d-%Y"),
            "long month name": long_date,
            "weekday prefix": lambda w: w if " - " in w else f"{mdy(w):%A, %B} {mdy(w).day}, {mdy(w).year}",
        }
        for name, style in styles.items():
            with self.subTest(style=name):
                self.assert_all_pass(self.run_all(date=style), name)

    def test_date_range_styles_accepted(self) -> None:
        styles = {
            "en dash": numeric_style("%m/%d/%Y", "–"),
            "em dash spaced": numeric_style("%-m/%-d/%Y", " — "),
            "to": numeric_style("%-m/%-d/%Y", " to "),
            "ISO to": numeric_style("%Y-%m-%d", " to "),
            "month once": long_date,
            "month twice": lambda w: (
                " - ".join(f"{mdy(p):%B} {mdy(p).day}" for p in w.split(" - ")) + f", {mdy(w.split(' - ')[1]).year}"
                if " - " in w else w
            ),
        }
        for name, style in styles.items():
            with self.subTest(style=name):
                self.assert_all_pass(self.run_all(date=style), name)

    def test_currency_strings_accepted(self) -> None:
        self.assert_all_pass(self.run_all(amount=lambda a: f"${a:,.2f}"), "currency strings")

    def test_blank_or_dash_denied_accepted(self) -> None:
        for blank in (None, "-", "—"):
            with self.subTest(blank=blank):
                self.assert_all_pass(self.run_all(denied_zero=blank), f"denied={blank!r}")

    def test_summary_label_variants_accepted(self) -> None:
        variants = {
            "colon": lambda l: f"{l}:",
            "upper-case": str.upper,
            "singular comment": lambda l: "Comment" if l == "Comments" else l,
            "extra word": lambda l: f"{l} (USD)" if l.startswith("Total") else l,
        }
        for name, style in variants.items():
            with self.subTest(variant=name):
                self.assert_all_pass(self.run_all(label=style), name)

    def test_sheet_name_variants_accepted(self) -> None:
        for names in (("Hassan, Amina", "Rahimi, Leila"), ("Amina Hassan ", "Leila Rahimi "), ("amina hassan", "leila rahimi")):
            with self.subTest(sheet_names=names):
                self.assert_all_pass(self.run_all(sheet_names=names), str(names))

    def test_title_row_above_header_accepted(self) -> None:
        self.assert_all_pass(self.run_all(header_row=2), "title row")

    # ---- quoted text: never accepted -----------------------------------------------------

    def test_quoted_jira_keys_rejected(self) -> None:
        for name, style in {"straight": lambda k: f'"{k}"', "curly": lambda k: f"“{k}”"}.items():
            with self.subTest(quotes=name):
                results = self.run_all(key=style)
                for rubric_id in ALL_FOUR:
                    self.assert_fail_mentions(results[rubric_id], "quoted", f"{name} quotes / {rubric_id}")

    def test_quoted_line_text_rejected(self) -> None:
        results = self.run_all(text=lambda s: f'"{s}"')
        for rubric_id in (HASSAN_LINES, RAHIMI_LINES):
            self.assert_fail_mentions(results[rubric_id], "merchant", rubric_id)
            self.assert_fail_mentions(results[rubric_id], "quoted", rubric_id)
        for rubric_id in (HASSAN_SUMMARY, RAHIMI_SUMMARY):
            self.assert_fail_mentions(results[rubric_id], "Final Status", rubric_id)
            self.assert_fail_mentions(results[rubric_id], "Comment", rubric_id)
            self.assert_fail_mentions(results[rubric_id], "quoted", rubric_id)

    def test_quoted_dates_rejected(self) -> None:
        results = self.run_all(date=lambda w: f'"{w}"')
        for rubric_id in (HASSAN_LINES, RAHIMI_LINES):
            self.assert_fail_mentions(results[rubric_id], "date", rubric_id)
            self.assert_fail_mentions(results[rubric_id], "quoted", rubric_id)

    def test_quoted_labels_and_marker_rejected(self) -> None:
        results = self.run_all(label=lambda l: f'"{l}"')
        for rubric_id in (HASSAN_SUMMARY, RAHIMI_SUMMARY):
            self.assert_fail_mentions(results[rubric_id], "quoted", rubric_id)
        results = self.run_all(marker=lambda m: f'"{m}"')
        for rubric_id in (HASSAN_SUMMARY, RAHIMI_SUMMARY):
            self.assert_fail_mentions(results[rubric_id], "Report Summary", rubric_id)

    # ---- other strictness kept or aligned with the sibling verifiers ---------------------

    def test_key_with_trailing_punctuation_rejected(self) -> None:
        results = self.run_all(key=lambda k: f"{k}:")
        for rubric_id in (HASSAN_LINES, RAHIMI_LINES):
            self.assert_fail_mentions(results[rubric_id], "Missing row", rubric_id)

    def test_manager_notified_requires_n_or_no(self) -> None:
        for value, should_pass in (("No", True), ("no", True), ("Pending", False), ("Unknown", False), ("Y", False)):
            with self.subTest(value=value):
                results = self.run_all(text=lambda s, v=value: v if s == "N" else s)
                for rubric_id in (HASSAN_SUMMARY, RAHIMI_SUMMARY):
                    if should_pass:
                        self.assertTrue(results[rubric_id]["pass"], results[rubric_id]["feedback"])
                    else:
                        self.assert_fail_mentions(results[rubric_id], "Manager Notified", f"{value}/{rubric_id}")

    def test_truncated_comment_rejected(self) -> None:
        results = self.run_all(text=lambda s: "T&E review complete." if s.startswith("T&E review complete.") else s)
        for rubric_id in (HASSAN_SUMMARY, RAHIMI_SUMMARY):
            self.assert_fail_mentions(results[rubric_id], "Comment expected", rubric_id)

    def test_formulas_without_cached_values_fail_with_explanation(self) -> None:
        results = self.run_all(formulas=True)
        for rubric_id in ALL_FOUR:
            self.assert_fail_mentions(results[rubric_id], "no cached value", rubric_id)

    def test_ops13_melody_bistro_is_dated_may_8(self) -> None:
        """Jira, the inbox, the receipt filename and the receipt itself all say May 8."""
        self.assertEqual(OPS13_DATE, "5/8/2026")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_workbook(workspace)
            path = workspace / "expense_reports.xlsx"
            workbook = openpyxl.load_workbook(path)
            sheet = workbook["Amina Hassan"]
            for row in sheet.iter_rows(min_row=2, max_col=2):
                if row[0].value == "OPS-13":
                    row[1].value = "5/7/2026"
            workbook.save(path)
            result = self.verifiers[HASSAN_LINES](str(workspace))
        self.assert_fail_mentions(result, 'OPS-13: date expected "5/8/2026"', "OPS-13 dated 5/7")

    def test_wrong_values_still_fail(self) -> None:
        results = self.run_all(amount=lambda a: a + 5)
        for rubric_id in ALL_FOUR:
            self.assertFalse(results[rubric_id]["pass"], rubric_id)


if __name__ == "__main__":
    unittest.main()
