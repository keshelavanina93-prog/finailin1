"""Disposable, exactly scoped Oxigraph projection; canonical storage remains PG/S3."""

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from finai_api.services.rdf_engine import _child_environment
    from finai_api.services.rdf_engine_limits import apply_resource_caps
else:
    from finai_api.services.rdf_engine import _child_environment
    from finai_api.services.rdf_engine_limits import apply_resource_caps

_MIB = 1024 * 1024
_HASH = re.compile(r"^[a-f0-9]{64}$")
_WORKERS = threading.BoundedSemaphore(2)
_BUILD_LOCK = threading.Lock()
_ENGINE_VERSION = "0.5.11"
_ERRORS = {
    "INVALID_INPUT": "The ontology index request or limits are invalid.",
    "DATASET_HASH": "Canonical dataset bytes do not match the exact release hash.",
    "DATASET_BUDGET": "The ontology dataset or derived index exceeds its processing budget.",
    "INVALID_DATASET": "The dataset must be canonical RDF 1.1 N-Quads with named graph provenance.",
    "INDEX_MISSING": "This exact index is absent; rebuild it from retained canonical bytes.",
    "INDEX_CORRUPT": "Index integrity verification failed; rebuild it from canonical bytes.",
    "RESULT_BUDGET": "The exact subject result exceeds its response byte budget.",
    "INDEX_BUDGET": "The index cache budget is full; offline cache maintenance is required.",
    "BUSY": "The local ontology index worker limit has been reached.",
    "WALL_TIMEOUT": "The ontology index worker exceeded its wall-clock budget.",
    "RESOURCE_CAP_UNAVAILABLE": "Required ontology index operating-system caps are unavailable.",
    "WORKER_FAILED": "The ontology index worker failed or exceeded its operating-system cap.",
}


class OntologyIndexError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code if code in _ERRORS else "WORKER_FAILED"
        self.message = _ERRORS[self.code]
        super().__init__(self.message)


@dataclass(frozen=True)
class OntologyIndexScope:
    tenant_id: str
    legal_entity_id: str
    release_id: str
    release_version_id: str
    release_content_hash: str
    dataset_sha256: str


@dataclass(frozen=True)
class OntologyIndexLimits:
    max_bytes: int = 16 * _MIB
    max_quads: int = 50_000
    max_subject_quads: int = 100
    max_result_bytes: int = 256 * 1024
    max_index_bytes: int = 256 * _MIB
    max_root_bytes: int = 1024 * _MIB
    wall_timeout_seconds: float = 10.0
    cpu_seconds: int = 8
    memory_bytes: int = 512 * _MIB


_DEFAULT_LIMITS = OntologyIndexLimits()


@dataclass(frozen=True)
class OntologyIndexManifest:
    scope: OntologyIndexScope
    index_key: str
    engine_version: str
    quad_count: int
    graph_iris: tuple[str, ...]
    derived_only: bool = True


@dataclass(frozen=True)
class OntologyIndexQuad:
    subject: str
    predicate: str
    object: str
    graph_iri: str


@dataclass(frozen=True)
class OntologySubjectInspection:
    scope: OntologyIndexScope
    subject_iri: str
    quads: tuple[OntologyIndexQuad, ...]
    truncated: bool
    derived_only: bool = True


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _key(scope: OntologyIndexScope, limits: OntologyIndexLimits) -> str:
    if not isinstance(scope, OntologyIndexScope) or not isinstance(limits, OntologyIndexLimits):
        raise OntologyIndexError("INVALID_INPUT")
    for value in (scope.tenant_id, scope.legal_entity_id):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise OntologyIndexError("INVALID_INPUT")
    try:
        UUID(scope.release_id)
        UUID(scope.release_version_id)
    except (ValueError, TypeError, AttributeError):
        raise OntologyIndexError("INVALID_INPUT") from None
    for value in (scope.release_content_hash, scope.dataset_sha256):
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise OntologyIndexError("INVALID_INPUT")
    for key, ceiling in {
        "max_bytes": 128 * _MIB,
        "max_quads": 250_000,
        "max_subject_quads": 100,
        "max_result_bytes": _MIB,
        "max_index_bytes": 1024 * _MIB,
        "max_root_bytes": 8 * 1024 * _MIB,
        "cpu_seconds": 60,
        "memory_bytes": 2048 * _MIB,
    }.items():
        value = getattr(limits, key)
        if type(value) is not int or not 1 <= value <= ceiling:
            raise OntologyIndexError("INVALID_INPUT")
    if (
        type(limits.wall_timeout_seconds) not in (int, float)
        or not math.isfinite(limits.wall_timeout_seconds)
        or not 0 < limits.wall_timeout_seconds <= 90
    ):
        raise OntologyIndexError("INVALID_INPUT")
    return hashlib.sha256(
        _json({"scope": asdict(scope), "engine_version": _ENGINE_VERSION})
    ).hexdigest()


def _root(index_root: Path) -> Path:
    root = Path(index_root).resolve()
    if os.name == "nt" and any(
        path.drive.lower() != "d:"
        for path in (
            root,
            Path(sys.executable).resolve(),
            Path(__file__).resolve(),
        )
    ):
        raise OntologyIndexError("INVALID_INPUT")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _worker(payload: dict[str, Any], scratch: Path, limits: OntologyIndexLimits) -> dict[str, Any]:
    if not _WORKERS.acquire(blocking=False):
        raise OntologyIndexError("BUSY")
    try:
        request, response = scratch / "request.json", scratch / "response.json"
        request.write_bytes(_json(payload))
        command = [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            str(request),
            str(response),
            str(limits.cpu_seconds),
            str(limits.memory_bytes),
            str(limits.max_index_bytes),
        ]
        with subprocess.Popen(
            command,
            cwd=scratch,
            env=_child_environment(scratch),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        ) as process:
            try:
                process.wait(timeout=limits.wall_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise OntologyIndexError("WALL_TIMEOUT") from None
        if not response.is_file():
            raise OntologyIndexError(
                "INDEX_CORRUPT" if payload["operation"] == "inspect" else "WORKER_FAILED"
            )
        if response.stat().st_size > limits.max_result_bytes:
            raise OntologyIndexError("RESULT_BUDGET")
        result = json.loads(response.read_bytes())
        if "error" in result:
            raise OntologyIndexError(result["error"])
        if process.returncode != 0:
            raise OntologyIndexError("WORKER_FAILED")
        return result
    except (OSError, json.JSONDecodeError):
        raise OntologyIndexError("WORKER_FAILED") from None
    finally:
        _WORKERS.release()


def build_index(
    scope: OntologyIndexScope,
    canonical_nquads: bytes,
    *,
    index_root: Path,
    limits: OntologyIndexLimits = _DEFAULT_LIMITS,
) -> OntologyIndexManifest:
    """Build off-path, then atomically publish a pointer to an immutable generation."""
    key = _key(scope, limits)
    if not isinstance(canonical_nquads, bytes):
        raise OntologyIndexError("INVALID_INPUT")
    if len(canonical_nquads) > limits.max_bytes:
        raise OntologyIndexError("DATASET_BUDGET")
    if hashlib.sha256(canonical_nquads).hexdigest() != scope.dataset_sha256:
        raise OntologyIndexError("DATASET_HASH")
    root = _root(index_root)
    if not _BUILD_LOCK.acquire(blocking=False):
        raise OntologyIndexError("BUSY")
    try:
        existing = _reuse(scope, root, key, limits)
        if existing is not None:
            return existing
        _storage_budget(root, key, limits)
        return _publish(scope, canonical_nquads, root, key, limits)
    finally:
        _BUILD_LOCK.release()


def _reuse(
    scope: OntologyIndexScope, root: Path, key: str, limits: OntologyIndexLimits
) -> OntologyIndexManifest | None:
    pointer = root / (key + ".json")
    if (
        not pointer.is_file()
        or pointer.is_symlink()
        or pointer.stat().st_size > limits.max_result_bytes
    ):
        return None
    previous = pointer.read_bytes()
    try:
        inspect_subject(
            scope, "urn:g8:index:integrity-check", index_root=root, limit=1, limits=limits
        )
    except OntologyIndexError as exc:
        if exc.code in ("INDEX_CORRUPT", "INDEX_MISSING", "INVALID_DATASET"):
            return None
        raise
    if pointer.read_bytes() != previous:
        raise OntologyIndexError("BUSY")
    manifest = json.loads(previous)
    return OntologyIndexManifest(
        scope=scope,
        index_key=key,
        engine_version=manifest["engine_version"],
        quad_count=manifest["quad_count"],
        graph_iris=tuple(manifest["graph_iris"]),
    )


def _storage_budget(root: Path, key: str, limits: OntologyIndexLimits) -> None:
    # Reservation is serialized within this process. Separate processes can race this scan;
    # deployment must bound worker-process count. Never delete a generation used by readers.
    total = count = generations = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                count += 1
                if (
                    path.is_symlink()
                    or path.is_junction()
                    or not path.resolve().is_relative_to(root)
                ):
                    raise OntologyIndexError("INDEX_CORRUPT")
                if entry.is_dir():
                    pending.append(path)
                    if directory == root and re.fullmatch(key + r"-[a-f0-9]{32}", entry.name):
                        generations += 1
                else:
                    total += entry.stat().st_size
                if count > 10_000 or total > limits.max_root_bytes or generations >= 2:
                    raise OntologyIndexError("INDEX_BUDGET")
    reserve = limits.max_index_bytes + 2 * limits.max_bytes + limits.max_result_bytes
    if total + reserve > limits.max_root_bytes:
        raise OntologyIndexError("INDEX_BUDGET")


def _publish(
    scope: OntologyIndexScope,
    canonical_nquads: bytes,
    root: Path,
    key: str,
    limits: OntologyIndexLimits,
) -> OntologyIndexManifest:
    with tempfile.TemporaryDirectory(prefix=".build-", dir=root) as temporary:
        scratch = Path(temporary)
        result = _worker(
            {
                "operation": "build",
                "scope": asdict(scope),
                "limits": asdict(limits),
                "index_key": key,
                "store": str(scratch / "store"),
                "canonical_nquads": base64.b64encode(canonical_nquads).decode("ascii"),
            },
            scratch,
            limits,
        )
        manifest = OntologyIndexManifest(
            scope=scope,
            index_key=key,
            **{
                **result,
                "graph_iris": tuple(result["graph_iris"]),
            },
        )
        generation = key + "-" + uuid4().hex
        destination = root / generation
        # Older generations remain disposable for concurrent readers; no in-place DB updates.
        pointer = scratch / "manifest.json"
        pointer.write_bytes(_json({**asdict(manifest), "generation": generation}))
        if pointer.stat().st_size > limits.max_result_bytes:
            raise OntologyIndexError("RESULT_BUDGET")
        (scratch / "store").rename(destination)
        os.replace(pointer, root / (key + ".json"))
        return manifest


def inspect_subject(
    scope: OntologyIndexScope,
    subject_iri: str,
    *,
    index_root: Path,
    limit: int = 50,
    limits: OntologyIndexLimits = _DEFAULT_LIMITS,
) -> OntologySubjectInspection:
    """Read only after the caller authorizes the exact release and recheck after return."""
    key = _key(scope, limits)
    if (
        type(limit) is not int
        or not 1 <= limit <= limits.max_subject_quads
        or not isinstance(subject_iri, str)
        or not 1 <= len(subject_iri) <= 2048
    ):
        raise OntologyIndexError("INVALID_INPUT")
    root = _root(index_root)
    pointer = root / (key + ".json")
    if pointer.is_symlink() or pointer.resolve().parent != root:
        raise OntologyIndexError("INDEX_CORRUPT")
    if not pointer.is_file():
        raise OntologyIndexError("INDEX_MISSING")
    try:
        if pointer.stat().st_size > limits.max_result_bytes:
            raise OntologyIndexError("INDEX_CORRUPT")
        manifest = json.loads(pointer.read_bytes())
        if not isinstance(manifest, dict):
            raise OntologyIndexError("INDEX_CORRUPT")
        if (
            manifest.get("scope") != asdict(scope)
            or manifest.get("index_key") != key
            or manifest.get("engine_version") != "0.5.11"
            or manifest.get("derived_only") is not True
            or not re.fullmatch(key + r"-[a-f0-9]{32}", manifest.get("generation", ""))
        ):
            raise OntologyIndexError("INDEX_CORRUPT")
        store = root / manifest["generation"]
        if store.is_symlink() or store.resolve().parent != root or not store.is_dir():
            raise OntologyIndexError("INDEX_CORRUPT")
        with tempfile.TemporaryDirectory(prefix=".read-", dir=root) as temporary:
            result = _worker(
                {
                    "operation": "inspect",
                    "scope": asdict(scope),
                    "limits": asdict(limits),
                    "store": str(store),
                    "manifest": manifest,
                    "subject_iri": subject_iri,
                    "limit": limit,
                },
                Path(temporary),
                limits,
            )
        inspection = OntologySubjectInspection(
            scope=scope,
            subject_iri=subject_iri,
            quads=tuple(OntologyIndexQuad(**quad) for quad in result["quads"]),
            truncated=result["truncated"],
        )
        if len(_json(asdict(inspection))) > limits.max_result_bytes:
            raise OntologyIndexError("RESULT_BUDGET")
        return inspection
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        raise OntologyIndexError("INDEX_CORRUPT") from None


def _safe_tree(store: Path, limits: OntologyIndexLimits) -> None:
    total = count = 0
    for directory, dirs, files in os.walk(store, followlinks=False):
        for name in (*dirs, *files):
            child = Path(directory) / name
            count += 1
            if (
                child.is_symlink()
                or child.is_junction()
                or child.resolve().is_relative_to(store) is False
            ):
                raise OntologyIndexError("INDEX_CORRUPT")
            if child.is_file():
                total += child.stat().st_size
            if count > 4096 or total > limits.max_index_bytes:
                raise OntologyIndexError("DATASET_BUDGET")


def _process(payload: dict[str, Any]) -> dict[str, Any]:
    import pyoxigraph as ox

    if ox.__version__ != "0.5.11":
        raise OntologyIndexError("INDEX_CORRUPT")
    limits = OntologyIndexLimits(**payload["limits"])
    path = Path(payload["store"])
    expected_hash = payload["scope"]["dataset_sha256"]
    if payload["operation"] == "build":
        data = base64.b64decode(payload["canonical_nquads"], validate=True)
        if len(data) > limits.max_bytes:
            raise OntologyIndexError("DATASET_BUDGET")
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise OntologyIndexError("DATASET_HASH")
        dataset = ox.Dataset()
        for index, quad in enumerate(ox.parse(input=data, format=ox.RdfFormat.N_QUADS)):
            if index >= limits.max_quads:
                raise OntologyIndexError("DATASET_BUDGET")
            dataset.add(quad)
        dataset.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)
    else:
        _safe_tree(path, limits)
        try:
            store = ox.Store.read_only(str(path))
        except (OSError, RuntimeError, ValueError):
            raise OntologyIndexError("INDEX_CORRUPT") from None
        dataset = ox.Dataset()
        for index, quad in enumerate(store):
            if index >= limits.max_quads:
                raise OntologyIndexError("DATASET_BUDGET")
            dataset.add(quad)
    graphs: set[str] = set()
    for quad in dataset:
        if (
            not isinstance(quad.graph_name, ox.NamedNode)
            or isinstance(quad.subject, ox.Triple)
            or isinstance(quad.object, ox.Triple)
            or (isinstance(quad.object, ox.Literal) and quad.object.direction is not None)
        ):
            raise OntologyIndexError("INVALID_DATASET")
        graphs.add(quad.graph_name.value)
    serialized = ox.serialize(dataset, format=ox.RdfFormat.N_QUADS)
    if not isinstance(serialized, bytes) or len(serialized) > limits.max_bytes:
        raise OntologyIndexError("DATASET_BUDGET")
    canonical = b"".join(line + b"\n" for line in sorted(serialized.split(b"\n")) if line)
    if hashlib.sha256(canonical).hexdigest() != expected_hash:
        raise OntologyIndexError(
            "INVALID_DATASET" if payload["operation"] == "build" else "INDEX_CORRUPT"
        )
    stats = {
        "quad_count": len(dataset),
        "graph_iris": sorted(graphs),
        "engine_version": ox.__version__,
    }
    if payload["operation"] == "build":
        store = ox.Store(path)
        store.extend(dataset)
        store.flush()
        del store
        _safe_tree(path, limits)
        return stats
    if any(payload["manifest"].get(key) != value for key, value in stats.items()):
        raise OntologyIndexError("INDEX_CORRUPT")
    try:
        subject = ox.NamedNode(payload["subject_iri"])
    except ValueError:
        raise OntologyIndexError("INVALID_INPUT") from None
    # Return from the verified snapshot, never from a second potentially changed store read.
    matches = sorted(dataset.quads_for_subject(subject), key=str)
    rows = []
    for quad in matches[: payload["limit"]]:
        if not isinstance(quad.graph_name, ox.NamedNode):
            raise OntologyIndexError("INDEX_CORRUPT")
        rows.append(
            {
                "subject": str(quad.subject),
                "predicate": str(quad.predicate),
                "object": str(quad.object),
                "graph_iri": quad.graph_name.value,
            }
        )
    return {
        "quads": rows,
        "truncated": len(matches) > payload["limit"],
    }


def _main() -> int:
    response = Path(sys.argv[2])
    try:
        try:
            apply_resource_caps(*(int(value) for value in sys.argv[3:6]))
        except (OSError, ValueError):
            raise OntologyIndexError("RESOURCE_CAP_UNAVAILABLE") from None
        payload = json.loads(Path(sys.argv[1]).read_bytes())
        result = _process(payload)
        if len(_json(result)) > payload["limits"]["max_result_bytes"]:
            raise OntologyIndexError("RESULT_BUDGET")
    except OntologyIndexError as exc:
        response.write_bytes(_json({"error": exc.code}))
        return 1
    except (OSError, SyntaxError):
        response.write_bytes(_json({"error": "INDEX_CORRUPT"}))
        return 1
    except Exception:
        response.write_bytes(_json({"error": "WORKER_FAILED"}))
        return 1
    response.write_bytes(_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
