import csv
import io

from .validation import IngestionError


def build_error_report_csv(errors: list[IngestionError]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_no", "field", "value", "reason"])
    for error in errors:
        writer.writerow([error.row_no, error.field, error.value, error.reason])
    return buffer.getvalue().encode("utf-8")
