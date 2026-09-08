"""A disposable index cannot outrank exact retained dataset and scope authority."""

import base64
import hashlib
import json
from dataclasses import asdict, replace
from uuid import uuid4

import pyoxigraph as ox
import pytest

from finai_api.services import ontology_index as index
from finai_api.services.rdf_engine import RdfArtifact, canonicalize_rdf

A = "https://example.test/a"
B = "https://example.test/b"
P = "https://example.test/p"


@pytest.fixture
def dataset(tmp_path):
    result = canonicalize_rdf(
        [
            RdfArtifact(
                A,
                "TURTLE",
                f'<{A}#s> <{P}> "first" ; <{P}> _:x . _:x <{P}> "detail" .'.encode(),
                (A + "#",),
            ),
            RdfArtifact(B, "TURTLE", f'<{B}#s> <{P}> "second" .'.encode(), (B + "#",)),
        ],
        root_iris=[A, B],
        work_dir=tmp_path / "engine",
    )
    scope = index.OntologyIndexScope(
        "tenant-public-test",
        "entity-non-uuid",
        str(uuid4()),
        str(uuid4()),
        "a" * 64,
        result.canonical_sha256,
    )
    return scope, result.canonical_nquads, tmp_path / "indexes"


def published(root, manifest):
    pointer = root / (manifest.index_key + ".json")
    data = json.loads(pointer.read_bytes())
    return pointer, data, root / data["generation"]


def test_rebuild_preserves_exact_subject_named_graphs_and_disposable_scope(dataset):
    scope, data, root = dataset
    first = index.build_index(scope, data, index_root=root)
    _, original_pointer, _ = published(root, first)
    assert first.scope == scope and first.graph_iris == (A, B) and first.quad_count == 4
    assert first.derived_only is True
    result = index.inspect_subject(scope, A + "#s", index_root=root)
    assert result.subject_iri == A + "#s" and result.scope == scope
    assert result.truncated is False and len(result.quads) == 2
    assert {quad.object for quad in result.quads} == {'"first"', "_:c14n0"}
    assert {quad.graph_iri for quad in result.quads} == {A}
    assert index.inspect_subject(scope, B + "#s", index_root=root).quads[0].graph_iri == B
    limited = index.inspect_subject(scope, A + "#s", index_root=root, limit=1)
    assert len(limited.quads) == 1 and limited.truncated is True
    assert index.inspect_subject(scope, A + "#absent", index_root=root).quads == ()
    second = index.build_index(scope, data, index_root=root)
    _, new_pointer, _ = published(root, second)
    assert first == second and original_pointer["generation"] == new_pointer["generation"]
    assert index.inspect_subject(scope, A + "#s", index_root=root) == result
    assert not list(root.glob(".build-*")) and not list(root.glob(".read-*"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other-tenant"),
        ("legal_entity_id", "other-company"),
        ("release_id", "11111111-1111-4111-8111-111111111111"),
        ("release_version_id", "22222222-2222-4222-8222-222222222222"),
        ("release_content_hash", "b" * 64),
        ("dataset_sha256", "c" * 64),
    ],
)
def test_every_scope_and_exact_pin_dimension_isolated(dataset, field, value):
    scope, data, root = dataset
    index.build_index(scope, data, index_root=root)
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(replace(scope, **{field: value}), A + "#s", index_root=root)
    assert caught.value.code == "INDEX_MISSING"


def test_valid_other_scope_builds_different_index_without_changing_first(dataset):
    scope, data, root = dataset
    first = index.build_index(scope, data, index_root=root)
    other = replace(scope, legal_entity_id="../outside-directory")
    second = index.build_index(other, data, index_root=root)
    assert first.index_key != second.index_key
    assert index.inspect_subject(scope, A + "#s", index_root=root).scope == scope
    assert index.inspect_subject(other, A + "#s", index_root=root).scope == other
    assert all(path.parent == root for path in root.iterdir())


def test_wrong_hash_never_publishes_and_failed_rebuild_preserves_pointer(dataset):
    scope, data, root = dataset
    manifest = index.build_index(scope, data, index_root=root)
    pointer, _, _ = published(root, manifest)
    before = pointer.read_bytes()
    with pytest.raises(index.OntologyIndexError) as caught:
        index.build_index(scope, data + b"#altered", index_root=root)
    assert caught.value.code == "DATASET_HASH"
    with pytest.raises(index.OntologyIndexError) as caught:
        index.build_index(
            scope, data, index_root=root, limits=index.OntologyIndexLimits(max_quads=1)
        )
    assert caught.value.code == "DATASET_BUDGET"
    assert pointer.read_bytes() == before
    assert index.inspect_subject(scope, A + "#s", index_root=root).quads


@pytest.mark.parametrize(
    "change",
    [
        {"generation": "../private"},
        {"derived_only": False},
        {"engine_version": "moving"},
        {"quad_count": 999},
        {"graph_iris": ["https://example.test/forged"]},
        {"scope": {"tenant_id": "other"}},
    ],
)
def test_tampered_manifest_refused(dataset, change):
    scope, data, root = dataset
    manifest = index.build_index(scope, data, index_root=root)
    pointer, saved, _ = published(root, manifest)
    pointer.write_text(json.dumps({**saved, **change}))
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(scope, A + "#s", index_root=root)
    assert caught.value.code == "INDEX_CORRUPT"


def test_store_tampering_cannot_be_hidden_by_rewriting_local_manifest(dataset):
    scope, data, root = dataset
    manifest = index.build_index(scope, data, index_root=root)
    pointer, saved, store_path = published(root, manifest)
    store = ox.Store(store_path)
    store.add(
        ox.Quad(
            ox.NamedNode(A + "#s"), ox.NamedNode(P), ox.Literal("forged private"), ox.NamedNode(A)
        )
    )
    store.flush()
    del store
    pointer.write_text(json.dumps({**saved, "quad_count": 5}))
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(scope, A + "#s", index_root=root)
    assert caught.value.code == "INDEX_CORRUPT" and "forged private" not in str(caught.value)
    index.build_index(scope, data, index_root=root)
    assert len(index.inspect_subject(scope, A + "#s", index_root=root).quads) == 2


def test_missing_or_corrupted_database_refuses_and_rebuild_restores(dataset):
    scope, data, root = dataset
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(scope, A + "#s", index_root=root)
    assert caught.value.code == "INDEX_MISSING"
    manifest = index.build_index(scope, data, index_root=root)
    _, _, store_path = published(root, manifest)
    current = store_path / "CURRENT"
    assert current.is_file()
    current.write_bytes(b"invalid index manifest\n")
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(scope, A + "#s", index_root=root)
    assert caught.value.code == "INDEX_CORRUPT"
    index.build_index(scope, data, index_root=root)
    assert index.inspect_subject(scope, B + "#s", index_root=root).quads[0].object == '"second"'


@pytest.mark.parametrize(
    "data",
    [
        b'<https://example.test/s> <https://example.test/p> "default graph" .\n',
        b'_:notcanonical <https://example.test/p> "x" <https://example.test/g> .\n',
        b"private malformed source",
    ],
)
def test_only_canonical_named_graph_dataset_may_build(dataset, data):
    scope, _, root = dataset
    scope = replace(scope, dataset_sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises(index.OntologyIndexError) as caught:
        index.build_index(scope, data, index_root=root)
    assert caught.value.code in {"INVALID_DATASET", "INDEX_CORRUPT"}
    assert not list(root.glob("*.json")) and "private" not in str(caught.value)


def test_byte_quad_result_and_physical_index_budgets(dataset):
    scope, data, root = dataset
    for limits in [
        index.OntologyIndexLimits(max_bytes=1),
        index.OntologyIndexLimits(max_quads=1),
        index.OntologyIndexLimits(max_index_bytes=1),
    ]:
        with pytest.raises(index.OntologyIndexError) as caught:
            index.build_index(scope, data, index_root=root, limits=limits)
        assert caught.value.code in {"DATASET_BUDGET", "WORKER_FAILED", "INDEX_CORRUPT"}
    # A long literal remains exact; the response fails instead of truncating its value.
    long_data = (f'<{A}#s> <{P}> "' + "x" * 10000 + f'" <{A}> .\n').encode()
    long_scope = replace(scope, dataset_sha256=hashlib.sha256(long_data).hexdigest())
    index.build_index(long_scope, long_data, index_root=root)
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(
            long_scope,
            A + "#s",
            index_root=root,
            limits=index.OntologyIndexLimits(max_result_bytes=4096),
        )
    assert caught.value.code == "RESULT_BUDGET"


def test_finite_concurrency_and_timeout_leave_existing_index_readable(dataset):
    scope, data, root = dataset
    index.build_index(scope, data, index_root=root)
    assert index._WORKERS.acquire(blocking=False) and index._WORKERS.acquire(blocking=False)
    try:
        with pytest.raises(index.OntologyIndexError) as caught:
            index.inspect_subject(scope, A + "#s", index_root=root)
        assert caught.value.code == "BUSY"
    finally:
        index._WORKERS.release()
        index._WORKERS.release()
    with pytest.raises(index.OntologyIndexError) as caught:
        index.inspect_subject(
            scope,
            A + "#s",
            index_root=root,
            limits=index.OntologyIndexLimits(wall_timeout_seconds=0.000001),
        )
    assert caught.value.code == "WALL_TIMEOUT"
    assert index.inspect_subject(scope, A + "#s", index_root=root).quads


def test_direct_index_processing_matches_subprocess_snapshot(dataset, tmp_path):
    scope, data, root = dataset
    limits = index.OntologyIndexLimits()
    store = tmp_path / "direct-store"
    payload = {
        "operation": "build",
        "scope": asdict(scope),
        "limits": asdict(limits),
        "store": str(store),
        "canonical_nquads": base64.b64encode(data).decode(),
    }
    stats = index._process(payload)
    assert stats["quad_count"] == 4
    direct = index._process(
        {
            "operation": "inspect",
            "scope": asdict(scope),
            "limits": asdict(limits),
            "store": str(store),
            "manifest": stats,
            "subject_iri": A + "#s",
            "limit": 1,
        }
    )
    index.build_index(scope, data, index_root=root)
    isolated = index.inspect_subject(scope, A + "#s", index_root=root, limit=1)
    assert direct["quads"] == [asdict(q) for q in isolated.quads]
    assert direct["truncated"] == isolated.truncated


def test_repeated_replay_reuses_generation_and_corrupt_rebuilds_stop_at_budget(dataset):
    scope, data, root = dataset
    manifest = index.build_index(scope, data, index_root=root)
    pointer, original, store = published(root, manifest)
    for _ in range(3):
        assert index.build_index(scope, data, index_root=root) == manifest
    assert json.loads(pointer.read_bytes())["generation"] == original["generation"]
    assert len(list(root.glob(manifest.index_key + "-*"))) == 1
    (store / "CURRENT").write_bytes(b"broken\n")
    index.build_index(scope, data, index_root=root)
    pointer, second, store = published(root, manifest)
    assert second["generation"] != original["generation"]
    (store / "CURRENT").write_bytes(b"broken again\n")
    with pytest.raises(index.OntologyIndexError) as caught:
        index.build_index(scope, data, index_root=root)
    assert caught.value.code == "INDEX_BUDGET"
    assert len(list(root.glob(manifest.index_key + "-*"))) == 2


def test_global_cache_reservation_and_engine_version_key_are_explicit(dataset, monkeypatch):
    scope, data, root = dataset
    with pytest.raises(index.OntologyIndexError) as caught:
        index.build_index(
            scope, data, index_root=root, limits=index.OntologyIndexLimits(max_root_bytes=1024)
        )
    assert caught.value.code == "INDEX_BUDGET"
    assert not list(root.iterdir())
    first = index._key(scope, index.OntologyIndexLimits())
    monkeypatch.setattr(index, "_ENGINE_VERSION", "future-pinned-version")
    assert index._key(scope, index.OntologyIndexLimits()) != first
