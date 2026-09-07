"""Candidate launch admission refuses queue collisions and unverified installed artifacts."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "g8_prepare_worker", ROOT / "scripts/prepare-built-worker.py"
)
prepare_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_worker)


def test_candidate_queue_cannot_consume_default_runtime(tmp_path):
    with pytest.raises(ValueError, match="candidate queue"):
        prepare_worker.prepare(
            tmp_path / "receipt.json",
            tmp_path / "python.exe",
            "g8-report-source-v1",
            tmp_path / "launches",
        )


def test_bad_wheel_never_reaches_installed_package_probe(tmp_path, monkeypatch):
    wheel = tmp_path / "candidate.whl"
    wheel.write_bytes(b"SYNTHETIC incomplete wheel")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps({"wheel": str(wheel), "wheel_sha256": "0" * 64}), encoding="utf-8"
    )
    monkeypatch.setattr(
        prepare_worker.runtime,
        "verify_installed",
        lambda *_: pytest.fail("Unverified artifact probe"),
    )
    with pytest.raises(ValueError, match="integrity"):
        prepare_worker.prepare(
            receipt, tmp_path / "python.exe", "g8-candidate-test", tmp_path / "launches"
        )
    assert not (tmp_path / "launches").exists()


def test_non_d_artifact_path_refused(tmp_path):
    with pytest.raises(ValueError, match="D:"):
        prepare_worker.prepare(
            Path("C:/candidate-receipt.json"),
            tmp_path / "python.exe",
            "g8-candidate-test",
            tmp_path / "launches",
        )


def test_c_backed_venv_refused_before_interpreter_execution(tmp_path, monkeypatch):
    root = tmp_path / "venv"
    root.mkdir()
    (root / "pyvenv.cfg").write_text("home = C:\\Python313\n", encoding="utf-8")
    monkeypatch.setattr(
        prepare_worker.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("C-backed interpreter must not execute"),
    )
    with pytest.raises(ValueError, match="D:"):
        prepare_worker.verify_interpreter(root / "Scripts/python.exe", tmp_path)


def test_reported_stdlib_must_also_remain_on_d(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prepare_worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps({"base_prefix": str(tmp_path), "stdlib": "C:/Python313/Lib"})
        ),
    )
    with pytest.raises(ValueError, match="D:"):
        prepare_worker.verify_interpreter(tmp_path / "python.exe", tmp_path)


def test_d_interpreter_location_evidence_retained(tmp_path, monkeypatch):
    expected = {"base_prefix": str(tmp_path), "stdlib": str(tmp_path / "Lib")}
    monkeypatch.setattr(
        prepare_worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(expected)),
    )
    assert prepare_worker.verify_interpreter(tmp_path / "python.exe", tmp_path) == expected
