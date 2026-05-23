"""Validated Excel exporter wrapper.

The balanced exporter performs a pre-save formula cycle check. The initial
formula parser treated the second cell in a qualified range such as
`DCF!B6:F6` as an unqualified same-sheet reference to `F6`, which caused false
positive circular references in the Sensitivity tab.

This wrapper installs a safer dependency scanner before delegating to the
balanced exporter. Qualified ranges now inherit the sheet name on both the start
and end cell, so `DCF!B6:F6` is scanned as `DCF!B6` and `DCF!F6`, not
`Sensitivity!F6`.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook

from src.report import balanced_excel_exporter as balanced
from src.schemas import FullReport

QUALIFIED_RANGE_RE = re.compile(
    r"(?P<sheet>'[^']+'|[A-Za-z_][A-Za-z0-9_ ]*)!"
    r"(?P<start>\$?[A-Z]{1,3}\$?\d+):(?P<end>\$?[A-Z]{1,3}\$?\d+)"
)


def _clean_sheet_name(sheet_token: str) -> str:
    if sheet_token.startswith("'") and sheet_token.endswith("'"):
        return sheet_token[1:-1].replace("''", "'")
    return sheet_token


def _clean_ref(ref: str) -> str:
    return ref.replace("$", "")


def _formula_dependencies(wb: Workbook) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    sheet_names = {ws.title for ws in wb.worksheets}

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str) or not cell.value.startswith("="):
                    continue

                node = f"{ws.title}!{cell.coordinate}"
                graph[node]
                formula = cell.value

                range_dependencies: set[str] = set()

                def remove_qualified_range(match: re.Match[str]) -> str:
                    sheet_name = _clean_sheet_name(match.group("sheet"))
                    if sheet_name in sheet_names:
                        range_dependencies.add(f"{sheet_name}!{_clean_ref(match.group('start'))}")
                        range_dependencies.add(f"{sheet_name}!{_clean_ref(match.group('end'))}")
                    return ""

                # Remove qualified ranges first so the range endpoint is not
                # accidentally read as a same-sheet reference.
                formula_without_qualified_ranges = QUALIFIED_RANGE_RE.sub(remove_qualified_range, formula)
                graph[node].update(range_dependencies)

                for match in balanced.CELL_REF_RE.finditer(formula_without_qualified_ranges):
                    sheet_quoted, sheet_plain, col, row_num = match.groups()
                    sheet_name = sheet_quoted or sheet_plain or ws.title
                    if sheet_name.startswith("'") and sheet_name.endswith("'"):
                        sheet_name = sheet_name[1:-1].replace("''", "'")
                    if sheet_name not in sheet_names:
                        continue
                    graph[node].add(f"{sheet_name}!{col}{row_num}")
    return graph


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    balanced._formula_dependencies = _formula_dependencies
    return balanced.export_excel_model(report, output_dir)
