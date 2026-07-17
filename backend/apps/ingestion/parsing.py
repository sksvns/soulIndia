"""Reads CSV/XLSX/XLS/XLSB into (headers, rows) with no implicit type
inference beyond what the file format itself carries -- Excel engines
return native int/float/str/datetime per cell; CSV is read as raw strings.
Explicit coercion happens in coercion.py per each field's declared `cast`,
never here.

Killer's and Pepe's real files are .xlsb (confirmed by inspecting the actual
sample files during Day 0), not .xlsx as the plan's "CSV/XLSX/XLS" wording
assumed -- pyxlsb support was added specifically so the pipeline can ingest
the real files, alongside keeping xlsx/xls/csv as originally specified.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

ENGINE_BY_EXTENSION = {
    ".xlsx": "openpyxl",
    ".xls": "xlrd",
    ".xlsb": "pyxlsb",
}


def read_source_file(
    fileobj, filename: str, sheet_name: str | None = None
) -> tuple[list[str], list[dict]]:
    """sheet_name picks a specific sheet out of a multi-sheet workbook (both
    real Killer and Pepe files are multi-sheet, with the transactional data
    on a non-first sheet -- 'SUMMARY'/'23-24 TO 25-26 SALE REPORT' for
    Killer, 5 sheets before 'PEPE DSR- 2026' for Pepe). Falls back to sheet
    index 0 both when no sheet_name is configured at all, and when one is
    configured but this particular file doesn't actually have a sheet by
    that name -- confirmed real-world case: a brand's export format can
    change (e.g. Pepe's original multi-sheet DSR workbook vs. a later
    single-sheet "Sheet1" extract) without every historical upload
    convention being renamed to match. Downstream required-column
    validation still catches a genuinely wrong sheet (missing required
    fields fails cleanly), so this fallback can't silently load garbage --
    it just stops a format's rename from being a hard blocker on its own."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension == ".csv":
        df = pd.read_csv(fileobj, dtype=object)
    elif extension in ENGINE_BY_EXTENSION:
        engine = ENGINE_BY_EXTENSION[extension]
        workbook = pd.ExcelFile(fileobj, engine=engine)
        if sheet_name and sheet_name not in workbook.sheet_names:
            logger.warning(
                "configured sheet %r not found in %r (has: %s) -- falling back to the first sheet",
                sheet_name,
                filename,
                workbook.sheet_names,
            )
            resolved_sheet = 0
        else:
            resolved_sheet = sheet_name if sheet_name else 0
        df = workbook.parse(sheet_name=resolved_sheet, dtype=object)
    else:
        raise ValueError(f"unsupported file extension: {extension!r}")

    df.columns = [str(c) for c in df.columns]
    headers = list(df.columns)
    rows = df.to_dict(orient="records")
    return headers, rows
