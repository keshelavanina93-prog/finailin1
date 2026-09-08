"""Offline derived RDF processing. No canonical resource or business authority."""

import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

_MIB = 1024 * 1024
_ERRORS = {
    "INVALID_INPUT": "RDF artifact metadata or processing limits are invalid.",
    "INPUT_BUDGET": "The RDF input budget was exceeded.",
    "UNSAFE_XML": "RDF/XML must be UTF-8 without DTDs or entity declarations.",
    "MALFORMED_RDF": "An artifact is not valid in its declared RDF format.",
    "UNSUPPORTED_RDF": "RDF-star and RDF 1.2 constructs are unsupported by this profile.",
    "NAMESPACE_COLLISION": "Artifact namespace ownership overlaps another artifact.",
    "NAMESPACE_VIOLATION": "An artifact asserts a subject outside its owned namespace.",
    "IMPORT_NOT_PERMITTED": "An RDF import is not explicitly permitted by its artifact.",
    "IMPORT_MISSING": "A permitted import has no supplied artifact.",
    "IMPORT_CYCLE": "The supplied RDF import closure contains a cycle.",
    "IMPORT_DEPTH": "The RDF import depth budget was exceeded.",
    "UNREACHABLE_ARTIFACT": "A supplied artifact is outside the selected import closure.",
    "QUAD_BUDGET": "The parsed RDF quad budget was exceeded.",
    "BLANK_NODE_BUDGET": "The RDF blank-node budget was exceeded.",
    "LITERAL_BUDGET": "The RDF literal byte budget was exceeded.",
    "OUTPUT_BUDGET": "The canonical RDF output budget was exceeded.",
    "RESOURCE_CAP_UNAVAILABLE": "Required operating-system RDF resource caps are unavailable.",
    "WALL_TIMEOUT": "The isolated RDF worker exceeded its wall-clock budget.",
    "WORKER_FAILED": "The isolated RDF worker failed or exceeded an operating-system cap.",
    "ENGINE_VERSION": "The installed RDF engine does not match the pinned version.",
}


class RdfEngineError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        # Never forward parser exception text, source literals or process environment.
        self.code = code if code in _ERRORS else "WORKER_FAILED"
        self.message = _ERRORS[self.code]
        super().__init__(self.message)


@dataclass(frozen=True)
class RdfArtifact:
    artifact_iri: str
    format: Literal["TURTLE", "RDF_XML"]
    content: bytes
    owned_namespaces: tuple[str, ...]
    permitted_import_iris: tuple[str, ...] = ()


@dataclass(frozen=True)
class RdfLimits:
    max_artifacts: int = 16
    max_input_bytes: int = 8 * _MIB
    max_quads: int = 50_000
    max_blank_nodes: int = 10_000
    max_literal_bytes: int = _MIB
    max_output_bytes: int = 16 * _MIB
    max_import_depth: int = 16
    wall_timeout_seconds: float = 10.0
    cpu_seconds: int = 8
    memory_bytes: int = 512 * _MIB


_DEFAULT_LIMITS = RdfLimits()


@dataclass(frozen=True)
class RdfArtifactResult:
    artifact_iri: str
    sha256: str
    imports: tuple[str, ...]
    quad_count: int


@dataclass(frozen=True)
class RdfResult:
    canonical_nquads: bytes
    canonical_sha256: str
    artifacts: tuple[RdfArtifactResult, ...]
    import_closure: tuple[str, ...]
    quad_count: int
    blank_node_count: int
    literal_bytes: int
    manifest: dict[str, str | int | bool]


def _validate_inputs(
    artifacts: Sequence[RdfArtifact], root_iris: Sequence[str], limits: RdfLimits
) -> None:
    ceilings = {
        "max_artifacts": 64,
        "max_input_bytes": 64 * _MIB,
        "max_quads": 250_000,
        "max_blank_nodes": 20_000,
        "max_literal_bytes": 8 * _MIB,
        "max_output_bytes": 128 * _MIB,
        "max_import_depth": 64,
        "cpu_seconds": 60,
        "memory_bytes": 2 * 1024 * _MIB,
    }
    if not isinstance(limits, RdfLimits):
        raise RdfEngineError("INVALID_INPUT")
    for key, ceiling in ceilings.items():
        value = getattr(limits, key)
        if type(value) is not int or not 1 <= value <= ceiling:
            raise RdfEngineError("INVALID_INPUT")
    if (
        type(limits.wall_timeout_seconds) not in (int, float)
        or not math.isfinite(limits.wall_timeout_seconds)
        or not 0 < limits.wall_timeout_seconds <= 90
    ):
        raise RdfEngineError("INVALID_INPUT")
    if not artifacts or len(artifacts) > limits.max_artifacts:
        raise RdfEngineError("INPUT_BUDGET")
    identities: set[str] = set()
    total = 0
    for artifact in artifacts:
        if not isinstance(artifact, RdfArtifact) or not isinstance(artifact.content, bytes):
            raise RdfEngineError("INVALID_INPUT")
        if artifact.format not in ("TURTLE", "RDF_XML") or not artifact.owned_namespaces:
            raise RdfEngineError("INVALID_INPUT")
        if len(artifact.owned_namespaces) > 64 or len(artifact.permitted_import_iris) > 64:
            raise RdfEngineError("INVALID_INPUT")
        for iri in (
            artifact.artifact_iri,
            *artifact.owned_namespaces,
            *artifact.permitted_import_iris,
        ):
            if not isinstance(iri, str) or not 1 <= len(iri) <= 2048:
                raise RdfEngineError("INVALID_INPUT")
        if artifact.artifact_iri in identities:
            raise RdfEngineError("INVALID_INPUT")
        identities.add(artifact.artifact_iri)
        total += len(artifact.content)
        if total > limits.max_input_bytes:
            raise RdfEngineError("INPUT_BUDGET")
    if (
        not root_iris
        or len(root_iris) > limits.max_artifacts
        or any(not isinstance(iri, str) or iri not in identities for iri in root_iris)
        or len(set(root_iris)) != len(root_iris)
    ):
        raise RdfEngineError("INVALID_INPUT")


def _child_environment(work_dir: Path) -> dict[str, str]:
    environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    environment.update(TEMP=str(work_dir), TMP=str(work_dir), TMPDIR=str(work_dir))
    return environment


def canonicalize_rdf(
    artifacts: Sequence[RdfArtifact],
    *,
    root_iris: Sequence[str],
    work_dir: Path,
    limits: RdfLimits = _DEFAULT_LIMITS,
) -> RdfResult:
    """Parse a supplied closure in a capped, killable process; never retrieve IRIs."""
    _validate_inputs(artifacts, root_iris, limits)
    directory = Path(work_dir).resolve()
    worker = Path(__file__).with_name("rdf_engine_worker.py").resolve()
    if os.name == "nt" and any(
        path.drive.lower() != "d:" for path in (directory, worker, Path(sys.executable).resolve())
    ):
        raise RdfEngineError("INVALID_INPUT")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rdf-", dir=directory) as temporary:
        scratch = Path(temporary)
        request, response = scratch / "request.json", scratch / "response.json"
        request.write_text(
            json.dumps(
                {
                    "limits": asdict(limits),
                    "root_iris": sorted(root_iris),
                    "artifacts": [
                        {**asdict(a), "content": base64.b64encode(a.content).decode("ascii")}
                        for a in sorted(artifacts, key=lambda item: item.artifact_iri)
                    ],
                },
                ensure_ascii=True,
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
            str(2 * limits.max_output_bytes + _MIB),
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
                raise RdfEngineError("WALL_TIMEOUT") from None
        if not response.is_file():
            raise RdfEngineError("WORKER_FAILED")
        if response.stat().st_size > 2 * limits.max_output_bytes + _MIB:
            raise RdfEngineError("OUTPUT_BUDGET")
        try:
            result = json.loads(response.read_text(encoding="utf-8"))
            if "error" in result:
                raise RdfEngineError(result["error"])
            if process.returncode != 0:
                raise RdfEngineError("WORKER_FAILED")
            canonical = base64.b64decode(result.pop("canonical_nquads"), validate=True)
            if len(canonical) > limits.max_output_bytes:
                raise RdfEngineError("OUTPUT_BUDGET")
            if hashlib.sha256(canonical).hexdigest() != result["canonical_sha256"]:
                raise RdfEngineError("WORKER_FAILED")
            records = tuple(
                RdfArtifactResult(**{**r, "imports": tuple(r["imports"])})
                for r in result.pop("artifacts")
            )
            return RdfResult(
                canonical_nquads=canonical,
                artifacts=records,
                **{**result, "import_closure": tuple(result["import_closure"])},
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RdfEngineError("WORKER_FAILED") from exc
