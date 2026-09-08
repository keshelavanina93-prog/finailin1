"""The CI exit code must reflect exact statement coverage, never display rounding."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check-api-coverage.py"


def report(covered, statements):
    summary = {
        "covered_lines": covered,
        "num_statements": statements,
        "missing_lines": statements - covered,
        "percent_covered": 90.0,
        "percent_covered_display": "90",
    }
    return {
        "totals": summary,
        "files": {"finai_api/example.py": {"summary": dict(summary)}},
    }


def run_gate(path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize(
    ("covered", "statements", "expected_exit"),
    [
        (9, 10, 0),
        (10, 10, 0),
        (8999, 10000, 1),
        (899999, 1000000, 1),
        (14557, 16177, 1),
        (14560, 16177, 0),
    ],
)
def test_exact_threshold_and_rounding_regression(
    tmp_path, covered, statements, expected_exit
):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report(covered, statements)), encoding="utf-8")
    process = run_gate(path)
    result = json.loads(process.stdout)
    assert process.returncode == expected_exit
    assert result["passed"] is (expected_exit == 0)
    assert result["threshold_percent"] == 90
    assert result["covered_statements"] == covered
    assert result["statements"] == statements


@pytest.mark.parametrize(
    "damage",
    [
        "missing_totals",
        "missing_count",
        "boolean",
        "float",
        "negative",
        "partition",
        "zero",
        "missing_files",
        "empty_files",
        "inconsistent_files",
        "missing_summary",
    ],
)
def test_malformed_metrics_fail_closed(tmp_path, damage):
    value = report(9, 10)
    if damage == "missing_totals":
        value.pop("totals")
    elif damage == "missing_count":
        value["totals"].pop("missing_lines")
    elif damage in {"boolean", "float", "negative", "partition"}:
        value["totals"]["covered_lines"] = {
            "boolean": True,
            "float": 9.0,
            "negative": -1,
            "partition": 10,
        }[damage]
    elif damage == "zero":
        value = report(0, 0)
    elif damage == "missing_files":
        value.pop("files")
    elif damage == "empty_files":
        value["files"] = {}
    elif damage == "inconsistent_files":
        value["files"]["finai_api/example.py"]["summary"] = report(1, 1)["totals"]
    elif damage == "missing_summary":
        value["files"]["finai_api/example.py"] = {}
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    process = run_gate(path)
    assert process.returncode == 2
    assert json.loads(process.stdout)["passed"] is False


@pytest.mark.parametrize(
    "content", [None, "not JSON", '{"totals":{},"totals":{}}', '{"x":NaN}']
)
def test_missing_invalid_and_ambiguous_json_fail_closed(tmp_path, content):
    path = tmp_path / "coverage.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    process = run_gate(path)
    assert process.returncode == 2
    assert json.loads(process.stdout)["passed"] is False


def test_real_per_file_totals_include_zero_statement_files(tmp_path):
    value = report(90, 100)
    value["files"] = {
        "finai_api/one.py": {"summary": report(40, 50)["totals"]},
        "finai_api/two.py": {"summary": report(50, 50)["totals"]},
        "finai_api/__init__.py": {"summary": report(0, 0)["totals"]},
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert run_gate(path).returncode == 0
