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

import pandas as pd

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
    Killer, 5 sheets before 'PEPE DSR- 2026' for Pepe). Falls back to
    pandas' own default (sheet index 0) when not configured, so single-sheet
    fixtures/files are unaffected."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension == ".csv":
        df = pd.read_csv(fileobj, dtype=object)
    elif extension in ENGINE_BY_EXTENSION:
        df = pd.read_excel(
            fileobj,
            dtype=object,
            engine=ENGINE_BY_EXTENSION[extension],
            sheet_name=sheet_name if sheet_name else 0,
        )
    else:
        raise ValueError(f"unsupported file extension: {extension!r}")

    df.columns = [str(c) for c in df.columns]
    headers = list(df.columns)
    rows = df.to_dict(orient="records")
    return headers, rows
