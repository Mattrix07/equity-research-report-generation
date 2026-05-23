"""Optional native Excel recalculation runtime.

openpyxl can create and edit workbooks, but it cannot calculate formulas the way
Excel does. This module optionally opens the generated workbook in local Excel via
xlwings, recalculates it, saves it, then closes Excel.

This is optional and disabled by default because it requires Microsoft Excel to
be installed on the machine running the app.
"""
from __future__ import annotations

from pathlib import Path

from src.config import settings


def recalc_with_excel_if_enabled(workbook_path: str | Path) -> tuple[bool, str]:
    """Recalculate workbook with native Excel when enabled.

    Returns a success flag and a message. If disabled or xlwings or Excel is
    unavailable, report generation continues and Excel recalculates on open.
    """
    if not getattr(settings, "enable_excel_runtime", False):
        return False, "Excel runtime disabled; workbook will recalculate when opened in Excel."

    try:
        import xlwings as xw  # type: ignore
    except Exception as exc:
        return False, f"Excel runtime requested but xlwings is unavailable: {exc}"

    path = str(Path(workbook_path).resolve())
    app = None
    book = None
    try:
        app = xw.App(visible=False, add_book=False)
        book = app.books.open(path)
        book.app.calculate()
        book.save(path)
        return True, "Workbook recalculated and saved with native Excel via xlwings."
    except Exception as exc:
        return False, f"Excel runtime failed; workbook will recalculate on open: {exc}"
    finally:
        if book is not None:
            try:
                book.close()
            except Exception:
                pass
        if app is not None:
            try:
                app.quit()
            except Exception:
                pass
