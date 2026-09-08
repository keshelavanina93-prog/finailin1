"""Exact retained RDF terms survive native store normalization and cache tampering."""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pyoxigraph as ox
import pytest
from test_ontology_index import published

from finai_api.services import ontology_index as index

S = "urn:lossless:subject"
P = "urn:lossless:predicate"
G = "urn:lossless:graph"
XSD = "http://www.w3.org/2001/XMLSchema#"


def canonical(quads):
    dataset = ox.Dataset(quads)
    dataset.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)
    raw = ox.serialize(dataset, format=ox.RdfFormat.N_QUADS)
    return b"".join(line + b"\n" for line in sorted(raw.splitlines()) if line)


def scope_for(data):
    return index.OntologyIndexScope(
        "synthetic-lossless",
        "synthetic-entity",
        str(uuid4()),
        str(uuid4()),
        "a" * 64,
        hashlib.sha256(data).hexdigest(),
    )


@pytest.fixture
def lexical_dataset(tmp_path):
    terms = [
        ox.Literal("0", datatype=ox.NamedNode(XSD + "nonNegativeInteger")),
        ox.Literal("01", datatype=ox.NamedNode(XSD + "integer")),
        ox.Literal("+000.0100", datatype=ox.NamedNode(XSD + "decimal")),
        ox.Literal("1", datatype=ox.NamedNode(XSD + "boolean")),
        ox.Literal("1.0E+03", datatype=ox.NamedNode(XSD + "double")),
        ox.Literal("2026-09-08T12:00:00+00:00", datatype=ox.NamedNode(XSD + "dateTime")),
        ox.Literal('ქართულად\nquoted "text"', language="ka"),
        ox.Literal("invalid-number", datatype=ox.NamedNode(XSD + "integer")),
        ox.BlankNode("sourceLabel"),
    ]
    data = canonical(
        [ox.Quad(ox.NamedNode(S), ox.NamedNode(P), term, ox.NamedNode(G)) for term in terms]
        + [
            ox.Quad(
                ox.BlankNode("sourceLabel"),
                ox.NamedNode(P),
                ox.Literal("detail"),
                ox.NamedNode("urn:lossless:second-graph"),
            )
        ]
    )
    return scope_for(data), data, tmp_path / "indexes"


def test_typed_lexical_forms_and_graph_blank_nodes_survive_native_roundtrip(lexical_dataset):
    scope, data, root = lexical_dataset
    manifest = index.build_index(scope, data, index_root=root)
    result = index.inspect_subject(scope, S, index_root=root)
    expected = sorted(
        (q for q in ox.parse(data, format=ox.RdfFormat.N_QUADS) if q.subject == ox.NamedNode(S)),
        key=str,
    )
    assert [(r.subject, r.predicate, r.object, r.graph_iri) for r in result.quads] == [
        (str(q.subject), str(q.predicate), str(q.object), q.graph_name.value) for q in expected
    ]
    assert '"01"^^<' + XSD + "integer>" in {q.object for q in result.quads}
    assert '"0"^^<' + XSD + "nonNegativeInteger>" in {q.object for q in result.quads}
    assert manifest.quad_count == 10 and len(manifest.graph_iris) == 2
    pointer, saved, store_path = published(root, manifest)
    store = ox.Store.read_only(str(store_path))
    assert all(q.object.datatype == ox.NamedNode(XSD + "string") for q in store)
    del store
    assert saved["index_encoding"] == "canonical-nquad-envelope/1"
    assert index.build_index(scope, data, index_root=root) == manifest
    assert json.loads(pointer.read_bytes())["generation"] == saved["generation"]


@pytest.mark.parametrize(
    "fault",
    [
        "object",
        "outer-subject",
        "outer-graph",
        "predicate",
        "language",
        "datatype",
        "two-quads",
        "trailing-comment",
        "noncanonical-spacing",
        "malformed",
        "empty",
    ],
)
def test_envelope_and_manifest_tampering_cannot_change_retained_hash(lexical_dataset, fault):
    scope, data, root = lexical_dataset
    manifest = index.build_index(scope, data, index_root=root)
    pointer, saved, store_path = published(root, manifest)
    store = ox.Store(store_path)
    old = next(q for q in store if q.subject == ox.NamedNode(S))
    subject, predicate, term, graph = old.subject, old.predicate, old.object, old.graph_name
    if fault == "object":
        original = next(ox.parse(term.value.encode(), format=ox.RdfFormat.N_QUADS))
        changed = ox.Quad(
            original.subject, original.predicate, ox.Literal("forged"), original.graph_name
        )
        term = ox.Literal(ox.serialize([changed], format=ox.RdfFormat.N_QUADS).decode())
    elif fault == "outer-subject":
        subject = ox.NamedNode("urn:forged:subject")
    elif fault == "outer-graph":
        graph = ox.NamedNode("urn:forged:graph")
    elif fault == "predicate":
        predicate = ox.NamedNode("urn:forged:predicate")
    elif fault == "language":
        term = ox.Literal(term.value, language="en")
    elif fault == "datatype":
        term = ox.Literal(term.value, datatype=ox.NamedNode("urn:forged:datatype"))
    else:
        raw = {
            "two-quads": term.value * 2,
            "trailing-comment": term.value + "# fake provenance\n",
            "noncanonical-spacing": " " + term.value,
            "malformed": "private malformed test text",
            "empty": "",
        }[fault]
        term = ox.Literal(raw)
    store.remove(old)
    store.add(ox.Quad(subject, predicate, term, graph))
    store.flush()
    del store
    # A forged digest is merely cache metadata, never the caller's retained authority.
    pointer.write_text(json.dumps({**saved, "derived_sha256": "b" * 64}), encoding="utf-8")
    with pytest.raises(index.OntologyIndexError) as refused:
        index.inspect_subject(scope, S, index_root=root)
    assert refused.value.code == "INDEX_CORRUPT"
    assert "private" not in str(refused.value)


def test_decoded_bytes_and_encoding_manifest_are_bounded(lexical_dataset):
    scope, data, root = lexical_dataset
    manifest = index.build_index(scope, data, index_root=root)
    with pytest.raises(index.OntologyIndexError) as refusal:
        index.inspect_subject(
            scope, S, index_root=root, limits=index.OntologyIndexLimits(max_bytes=len(data) - 1)
        )
    assert refusal.value.code == "DATASET_BUDGET"
    pointer, saved, _ = published(root, manifest)
    for encoding in (None, "future-unknown-encoding"):
        pointer.write_text(json.dumps({**saved, "index_encoding": encoding}), encoding="utf-8")
        with pytest.raises(index.OntologyIndexError) as refusal:
            index.inspect_subject(scope, S, index_root=root)
        assert refusal.value.code == "INDEX_CORRUPT"


def test_pre_envelope_index_is_preserved_but_requires_separate_rebuild(lexical_dataset):
    scope, data, root = lexical_dataset
    root.mkdir()
    old_key = hashlib.sha256(
        index._json(
            {
                "scope": asdict(scope),
                "engine_version": "0.5.11",
            }
        )
    ).hexdigest()
    generation = old_key + "-" + uuid4().hex
    store = ox.Store(root / generation)
    store.extend(ox.parse(data, format=ox.RdfFormat.N_QUADS))
    store.flush()
    del store
    pointer = root / (old_key + ".json")
    old = index._json(
        {
            "scope": asdict(scope),
            "index_key": old_key,
            "engine_version": "0.5.11",
            "generation": generation,
        }
    )
    pointer.write_bytes(old)
    with pytest.raises(index.OntologyIndexError) as refusal:
        index.inspect_subject(scope, S, index_root=root)
    assert refusal.value.code == "INDEX_MISSING"
    manifest = index.build_index(scope, data, index_root=root)
    assert manifest.index_key != old_key and pointer.read_bytes() == old
    assert (root / generation).is_dir()
    assert index.inspect_subject(scope, S, index_root=root).quads


def test_original_prov_exact_dataset_build_and_read(tmp_path):
    configured = os.getenv("G8_PROV_ARTIFACT_PATH")
    if not configured:
        pytest.skip("Offline acceptance requires the existing public PROV artifact")
    original = Path(configured).read_bytes()
    assert hashlib.sha256(original).hexdigest() == (
        "3d03c8e15753178541fb8cd59fbefecaf1861f9c37ef75190c6e938b85fb0c3d"
    )
    graph = ox.NamedNode("http://www.w3.org/ns/prov-o#")
    data = canonical(
        ox.Quad(q.subject, q.predicate, q.object, graph)
        for q in ox.parse(
            original,
            format=ox.RdfFormat.TURTLE,
            base_iri=graph.value,
        )
    )
    assert hashlib.sha256(data).hexdigest() == (
        "0a4814bb0648e8ee3465db44d1818723336c721bc51c04439ca201815a82499e"
    )
    scope, root = scope_for(data), tmp_path / "prov-index"
    manifest = index.build_index(scope, data, index_root=root)
    assert manifest.quad_count == 1146
    subject = "http://www.w3.org/2002/07/owl#Thing"
    result = index.inspect_subject(scope, subject, index_root=root)
    assert [asdict(q) for q in result.quads] == [
        {
            "subject": "<" + subject + ">",
            "predicate": "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
            "object": "<http://www.w3.org/2002/07/owl#Class>",
            "graph_iri": graph.value,
        }
    ]
    assert index.build_index(scope, data, index_root=root) == manifest
    assert Path(configured).read_bytes() == original
