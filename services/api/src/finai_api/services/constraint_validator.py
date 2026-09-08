"""Bounded offline SHACL evidence; no canonical identity or promotion authority."""

import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from finai_api.services.rdf_engine import _child_environment

_MIB = 1024 * 1024
_SLOTS = threading.BoundedSemaphore(2)
_CODES = {
    "INVALID_INPUT",
    "INPUT_BUDGET",
    "HASH_MISMATCH",
    "NON_CANONICAL",
    "GRAPH_SELECTION",
    "UNSUPPORTED_SHAPES",
    "MALFORMED_SHAPES",
    "UNKNOWN_FOCUS",
    "UNKNOWN_SHAPE",
    "QUAD_BUDGET",
    "SHAPE_BUDGET",
    "FOCUS_BUDGET",
    "REPORT_BUDGET",
    "ENGINE_VERSION",
    "RESOURCE_CAP_UNAVAILABLE",
    "WALL_TIMEOUT",
    "WORKER_FAILED",
    "BUSY",
}


class ConstraintValidatorError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code if code in _CODES else "WORKER_FAILED"
        self.message = f"Offline constraint validation refused: {self.code}."
        super().__init__(self.message)


@dataclass(frozen=True)
class ValidationDataset:
    canonical_nquads: bytes
    sha256: str
    graph_iris: tuple[str, ...]


@dataclass(frozen=True)
class ValidationSelection:
    mode: Literal["PROFILE_TARGETS", "FILTER_TARGETS", "EXPLICIT_SHAPE_FOCUS"] = "PROFILE_TARGETS"
    focus_iris: tuple[str, ...] = ()
    shape_iris: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConstraintValidationLimits:
    max_input_bytes: int = 8 * _MIB
    max_quads: int = 50_000
    max_shape_quads: int = 5_000
    max_shapes: int = 1_000
    max_focus_nodes: int = 5_000
    max_report_bytes: int = _MIB
    max_results: int = 1_000
    cpu_seconds: int = 8
    memory_bytes: int = 512 * _MIB
    wall_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class ConstraintValidationResult:
    status: Literal["CONFORMS", "VIOLATES", "NOT_EVALUATED"]
    conforms: bool | None
    data_sha256: str
    shapes_sha256: str
    data_graph_iris: tuple[str, ...]
    shape_graph_iris: tuple[str, ...]
    report_nquads: bytes
    report_sha256: str
    evaluated_shape_count: int
    evaluated_focus_count: int
    evaluated_constraint_count: int
    violation_count: int
    manifest: dict[str, str | int | bool]


_DEFAULT_SELECTION = ValidationSelection()
_DEFAULT_LIMITS = ConstraintValidationLimits()
_DEPENDENCIES = {
    "pyshacl": "0.40.1",
    "rdflib": "7.6.0",
    "pyoxigraph": "0.5.11",
    "owlrl": "7.6.2",
    "pyparsing": "3.3.2",
}


def _provenance() -> dict[str, str]:
    try:
        if any(version(package) != expected for package, expected in _DEPENDENCIES.items()):
            raise ConstraintValidatorError("ENGINE_VERSION")
        source = Path(__file__).resolve()
        hashes = {
            key: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for key, path in {
                "controller_source_sha256": source,
                "worker_source_sha256": source.with_name("constraint_validator_worker.py"),
                "resource_caps_source_sha256": source.with_name("rdf_engine_limits.py"),
            }.items()
        }
    except (OSError, PackageNotFoundError):
        raise ConstraintValidatorError("ENGINE_VERSION") from None
    return {
        **hashes,
        "source_hash_policy": "UTF8_SOURCE_CRLF_TO_LF_SHA256",
        "dependency_versions": json.dumps(_DEPENDENCIES, sort_keys=True, separators=(",", ":")),
    }


def _iris(values: tuple[str, ...], maximum: int, *, empty: bool = False) -> None:
    from urllib.parse import urlsplit

    if (
        type(values) is not tuple
        or len(values) > maximum
        or (not values and not empty)
        or any(not isinstance(v, str) or not 1 <= len(v) <= 2048 for v in values)
        or len(set(values)) != len(values)
    ):
        raise ConstraintValidatorError("INVALID_INPUT")
    for value in values:
        try:
            scheme = urlsplit(value).scheme
        except ValueError:
            raise ConstraintValidatorError("INVALID_INPUT") from None
        if not scheme or any(c.isspace() or ord(c) < 32 for c in value):
            raise ConstraintValidatorError("INVALID_INPUT")


def validator_manifest(
    *,
    selection: ValidationSelection = _DEFAULT_SELECTION,
    limits: ConstraintValidationLimits = _DEFAULT_LIMITS,
) -> dict[str, str | int | bool]:
    if not isinstance(selection, ValidationSelection) or not isinstance(
        limits, ConstraintValidationLimits
    ):
        raise ConstraintValidatorError("INVALID_INPUT")
    _iris(selection.focus_iris, 100, empty=True)
    _iris(selection.shape_iris, 32, empty=True)
    if (
        selection.mode not in ("PROFILE_TARGETS", "FILTER_TARGETS", "EXPLICIT_SHAPE_FOCUS")
        or (selection.mode == "PROFILE_TARGETS" and (selection.focus_iris or selection.shape_iris))
        or (selection.mode != "PROFILE_TARGETS" and not selection.focus_iris)
        or (selection.mode == "EXPLICIT_SHAPE_FOCUS" and not selection.shape_iris)
    ):
        raise ConstraintValidatorError("INVALID_INPUT")
    for key, default in asdict(ConstraintValidationLimits()).items():
        value = getattr(limits, key)
        if key == "wall_timeout_seconds":
            valid = type(value) in (int, float) and math.isfinite(value) and 0 < value <= default
        else:
            valid = type(value) is int and 0 < value <= default
        if not valid:
            raise ConstraintValidatorError("INVALID_INPUT")
    return {
        **_provenance(),
        "profile": "G8_OFFLINE_SHACL_CORE_1",
        "engine": "pyshacl",
        "engine_version": "0.40.1",
        "rdflib_version": "7.6.0",
        "canonicalizer": "pyoxigraph/0.5.11/RDFC-1.0",
        "inference": "none",
        "advanced": False,
        "js": False,
        "sparql_mode": False,
        "network_retrieval": False,
        "owl_imports": False,
        "abort_on_first": False,
        "allow_infos": False,
        "allow_warnings": False,
        "max_validation_depth": 15,
        "meta_shacl": True,
        "report_message_policy": "AUTHOR_MESSAGES_ONLY",
        "blank_node_origin_policy": "SELECTED_DATASET_SHA256_CANONICAL_LABEL_ROLE",
        "coverage_policy": "COMPLETED_SUBSTANTIVE_CORE_COMPONENT_SHAPE_FOCUS_TUPLES",
        "selection_mode": selection.mode,
        "focus_iris": json.dumps(sorted(selection.focus_iris), separators=(",", ":")),
        "shape_iris": json.dumps(sorted(selection.shape_iris), separators=(",", ":")),
        **{
            key: str(value) if isinstance(value, float) else value
            for key, value in asdict(limits).items()
        },
    }


def validate_constraints(
    data: ValidationDataset,
    shapes: ValidationDataset,
    *,
    work_dir: Path,
    selection: ValidationSelection = _DEFAULT_SELECTION,
    limits: ConstraintValidationLimits = _DEFAULT_LIMITS,
) -> ConstraintValidationResult:
    """Validate retained bytes in a credential-free, killable process with mandatory caps."""
    validator_manifest(selection=selection, limits=limits)
    for source in (data, shapes):
        if not isinstance(source, ValidationDataset) or not isinstance(
            source.canonical_nquads, bytes
        ):
            raise ConstraintValidatorError("INVALID_INPUT")
        _iris(source.graph_iris, 64)
        if hashlib.sha256(source.canonical_nquads).hexdigest() != source.sha256:
            raise ConstraintValidatorError("HASH_MISMATCH")
    if len(data.canonical_nquads) + len(shapes.canonical_nquads) > limits.max_input_bytes:
        raise ConstraintValidatorError("INPUT_BUDGET")
    directory = Path(work_dir).resolve()
    worker = Path(__file__).with_name("constraint_validator_worker.py").resolve()
    if os.name == "nt" and any(
        p.drive.lower() != "d:" for p in (directory, worker, Path(sys.executable).resolve())
    ):
        raise ConstraintValidatorError("INVALID_INPUT")
    if not _SLOTS.acquire(blocking=False):
        raise ConstraintValidatorError("BUSY")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="shacl-", dir=directory) as temporary:
            scratch = Path(temporary)
            request, response = scratch / "request.json", scratch / "response.json"
            request.write_text(
                json.dumps(
                    {
                        "data": {
                            **asdict(data),
                            "canonical_nquads": base64.b64encode(data.canonical_nquads).decode(),
                        },
                        "shapes": {
                            **asdict(shapes),
                            "canonical_nquads": base64.b64encode(shapes.canonical_nquads).decode(),
                        },
                        "selection": asdict(selection),
                        "limits": asdict(limits),
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-I",
                "-B",
                str(worker),
                str(request),
                str(response),
                str(limits.cpu_seconds),
                str(limits.memory_bytes),
                str(2 * limits.max_report_bytes + _MIB),
            ]
            with subprocess.Popen(
                command,
                cwd=scratch,
                env=_child_environment(scratch),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            ) as process:
                try:
                    process.wait(timeout=limits.wall_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise ConstraintValidatorError("WALL_TIMEOUT") from None
            if not response.is_file():
                raise ConstraintValidatorError("WORKER_FAILED")
            if response.stat().st_size > 2 * limits.max_report_bytes + _MIB:
                raise ConstraintValidatorError("REPORT_BUDGET")
            result = json.loads(response.read_text(encoding="utf-8"))
            if "error" in result:
                raise ConstraintValidatorError(result["error"])
            if process.returncode:
                raise ConstraintValidatorError("WORKER_FAILED")
            report = base64.b64decode(result.pop("report_nquads"), validate=True)
            if len(report) > limits.max_report_bytes:
                raise ConstraintValidatorError("REPORT_BUDGET")
            if hashlib.sha256(report).hexdigest() != result["report_sha256"]:
                raise ConstraintValidatorError("WORKER_FAILED")
            return ConstraintValidationResult(
                report_nquads=report,
                **{
                    **result,
                    "data_graph_iris": tuple(result["data_graph_iris"]),
                    "shape_graph_iris": tuple(result["shape_graph_iris"]),
                },
            )
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ConstraintValidatorError("WORKER_FAILED") from None
    finally:
        _SLOTS.release()
