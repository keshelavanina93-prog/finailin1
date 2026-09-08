"""Enforce the API statement-coverage threshold without percentage rounding."""

import argparse
import json
from pathlib import Path

THRESHOLD_PERCENT = 90
MAX_REPORT_BYTES = 32 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def counts(summary):
    if not isinstance(summary, dict):
        raise ValueError("Coverage summary must be an object")
    values = tuple(
        summary.get(key) for key in ("covered_lines", "num_statements", "missing_lines")
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Coverage statement counts must be nonnegative integers")
    covered, statements, missing = values
    if covered + missing != statements:
        raise ValueError("Covered and missing statements do not partition the total")
    return values


def evaluate(report):
    if not isinstance(report, dict):
        raise ValueError("Coverage report must be an object")
    covered, statements, missing = counts(report.get("totals"))
    if statements == 0:
        raise ValueError("An empty statement denominator cannot establish API coverage")
    files = report.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Coverage report must contain per-file summaries")
    summaries = []
    for name, record in files.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(record, dict)
        ):
            raise ValueError("Invalid coverage file record")
        summaries.append(counts(record.get("summary")))
    if tuple(map(sum, zip(*summaries, strict=True))) != (covered, statements, missing):
        raise ValueError("Coverage totals differ from per-file statement counts")
    return {
        "contract": "g8-api-coverage-gate/1",
        "passed": covered * 100 >= statements * THRESHOLD_PERCENT,
        "threshold_percent": THRESHOLD_PERCENT,
        "covered_statements": covered,
        "statements": statements,
        "missing_statements": missing,
        "comparison": "covered_statements * 100 >= statements * 90",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        with args.report.open("rb") as source:
            raw = source.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("Coverage report exceeds the bounded input size")
        report = json.loads(
            raw, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
        result = evaluate(report)
    except (OSError, ValueError, TypeError, RecursionError):
        print(
            json.dumps(
                {
                    "contract": "g8-api-coverage-gate/1",
                    "passed": False,
                    "error": "Missing, malformed, or inconsistent coverage report",
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
