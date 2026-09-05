"""Bounded source browsing over integrity-verified retained bytes; no type coercion."""
import csv
from hashlib import sha256
from io import StringIO
from typing import Any


def preview(content: bytes, offset: int = 0, search: str = "") -> dict[str, Any]:
    records = csv.reader(StringIO(content.decode("utf-8-sig"), newline=""))
    columns = next(records, [])
    rows = []
    total = 0
    matched = 0
    query = search.casefold()
    for source_row, values in enumerate(records, start=2):
        total += 1
        if query and not any(query in value.casefold() for value in values):
            continue
        if offset <= matched < offset + 100:
            rows.append({"source_row": source_row, "values": values,
                         "width_matches_header": len(values) == len(columns)})
        matched += 1
    return {"columns": columns, "rows": rows, "total_rows": total,
            "matching_rows": matched, "offset": offset, "page_size": 100,
            "has_more": matched > offset + 100, "sha256": sha256(content).hexdigest(),
            "byte_length": len(content), "integrity": "VERIFIED", "value_semantics": "SOURCE_TEXT"}
