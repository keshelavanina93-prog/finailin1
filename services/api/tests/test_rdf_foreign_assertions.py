"""Exact foreign assertions remain publisher evidence, never vocabulary ownership."""

import base64
import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pyoxigraph as ox
import pytest

from finai_api.domain.external_ontology import ImportRequest, ModuleInput
from finai_api.services import ontology_import, rdf_engine_worker
from finai_api.services.rdf_engine import (
    RdfArtifact,
    RdfEngineError,
    RdfForeignAssertion,
    RdfLimits,
    canonicalize_rdf,
)

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
REASON = "Retain the publisher's exact external vocabulary annotation without ownership."


def statement(subject="urn:foreign:Term", predicate=RDFS + "comment", value='"source annotation"'):
    return RdfForeignAssertion(subject, predicate, value, "FOREIGN_ANNOTATION", REASON)


def artifact(declarations=None, text=None):
    item = statement()
    return RdfArtifact(
        "urn:owned:module",
        "TURTLE",
        (text or f"<{item.subject_iri}> <{item.predicate_iri}> {item.object_ntriples} .").encode(),
        ("urn:owned:",),
        foreign_assertions=tuple(declarations if declarations is not None else [item]),
    )


def run(tmp_path, item, **kwargs):
    return canonicalize_rdf([item], root_iris=[item.artifact_iri], work_dir=tmp_path, **kwargs)


def serialized_worker_request(item):
    # Exercise the actual JSON protocol: Python tuples must not mask wire-shape mistakes.
    return json.loads(
        json.dumps(
            {
                "artifacts": [{**asdict(item), "content": base64.b64encode(item.content).decode()}],
                "root_iris": [item.artifact_iri],
                "limits": asdict(RdfLimits()),
            }
        )
    )


def test_serialized_worker_foreign_policy_matches_exact_retained_protocol(tmp_path):
    """Direct execution verifies protocol semantics; isolated execution verifies the real path."""
    annotation = statement(subject="urn:foreign:A", value='"retained annotation"')
    declaration = RdfForeignAssertion(
        "urn:foreign:B", TYPE, f"<{OWL}Class>", "FOREIGN_VOCABULARY_DECLARATION", REASON
    )
    item = artifact(
        [declaration, annotation],
        text=(
            f"<urn:foreign:B> <{TYPE}> <{OWL}Class> .\n"
            f'<urn:foreign:A> <{RDFS}comment> "retained annotation" .\n'
            '<urn:owned:C> <urn:owned:predicate> "owned value" .\n'
        ),
    )
    expected = (
        f'<urn:foreign:A> <{RDFS}comment> "retained annotation" <urn:owned:module> .\n'
        f"<urn:foreign:B> <{TYPE}> <{OWL}Class> <urn:owned:module> .\n"
        '<urn:owned:C> <urn:owned:predicate> "owned value" <urn:owned:module> .\n'
    ).encode()
    direct = rdf_engine_worker.process(serialized_worker_request(item), "PROTOCOL_ONLY")
    isolated = run(tmp_path, item)
    assert base64.b64decode(direct["canonical_nquads"]) == expected
    assert isolated.canonical_nquads == expected
    expected_hash = hashlib.sha256(expected).hexdigest()
    assert direct["canonical_sha256"] == isolated.canonical_sha256 == expected_hash
    expected_report = [
        {
            "artifact_iri": "urn:owned:module",
            "source_sha256": hashlib.sha256(item.content).hexdigest(),
            "assertions": [asdict(annotation), asdict(declaration)],
            "ownership_authorized": False,
            "equivalence_authorized": False,
        }
    ]
    assert direct["foreign_assertions"] == list(isolated.foreign_assertions) == expected_report
    assert direct["artifacts"] == [
        {
            "artifact_iri": "urn:owned:module",
            "sha256": hashlib.sha256(item.content).hexdigest(),
            "imports": [],
            "quad_count": 3,
        }
    ]
    assert direct["quad_count"] == isolated.quad_count == 3
    assert direct["manifest"] == isolated.manifest
    assert direct["manifest"]["foreign_assertion_count"] == 2
    assert direct["manifest"]["foreign_assertion_policy"] == (
        "EXACT_FOREIGN_ANNOTATIONS_DECLARATIONS/1"
    )
    assert (
        not {"owned_namespaces", "canonical_term_id", "business_effect_authorized"} & direct.keys()
    )


@pytest.mark.parametrize(
    "declarations,code",
    [
        (
            [replace(statement(), object_ntriples='"private unterminated')],
            "FOREIGN_ASSERTION_POLICY",
        ),
        ([replace(statement(), object_ntriples="_:unscoped")], "FOREIGN_ASSERTION_POLICY"),
        (
            [replace(statement(), predicate_iri=OWL + "sameAs", object_ntriples="<urn:owned:C>")],
            "FOREIGN_ASSERTION_POLICY",
        ),
        ([statement(), statement()], "FOREIGN_ASSERTION_POLICY"),
        ([statement(subject="urn:owned:C")], "FOREIGN_ASSERTION_POLICY"),
        ([statement(), statement(subject="urn:foreign:Unused")], "UNUSED_FOREIGN_ASSERTION"),
    ],
)
def test_serialized_worker_policy_refusals_match_isolated_controller(tmp_path, declarations, code):
    item = artifact(declarations)
    with pytest.raises(RdfEngineError) as direct:
        rdf_engine_worker.process(serialized_worker_request(item), "PROTOCOL_ONLY")
    with pytest.raises(RdfEngineError) as isolated:
        run(tmp_path, item)
    assert direct.value.code == isolated.value.code == code
    assert "private" not in str(direct.value) and "private" not in str(isolated.value)


def test_exact_exception_preserves_graph_and_adds_no_ownership(tmp_path):
    item = artifact()
    result = run(tmp_path, item)
    assert (
        result.canonical_nquads
        == (
            f'<urn:foreign:Term> <{RDFS}comment> "source annotation" <urn:owned:module> .\n'
        ).encode()
    )
    assert result.quad_count == 1
    assert result.manifest["foreign_assertion_count"] == 1
    entry = result.foreign_assertions[0]
    assert entry == {
        "artifact_iri": item.artifact_iri,
        "source_sha256": hashlib.sha256(item.content).hexdigest(),
        "assertions": [asdict(statement())],
        "ownership_authorized": False,
        "equivalence_authorized": False,
    }
    assert result.artifacts[0].sha256 == hashlib.sha256(item.content).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        lambda s: replace(s, object_ntriples='"changed"'),
        lambda s: replace(s, predicate_iri=RDFS + "label"),
        lambda s: replace(s, subject_iri="urn:foreign:Other"),
    ],
)
def test_changed_exact_triple_still_refuses(tmp_path, change):
    with pytest.raises(RdfEngineError, match="outside"):
        run(tmp_path, artifact([change(statement())]))


@pytest.mark.parametrize(
    "predicate,value,classification",
    [
        (OWL + "sameAs", "<urn:owned:Entity>", "FOREIGN_ANNOTATION"),
        (OWL + "equivalentClass", "<urn:owned:Entity>", "FOREIGN_ANNOTATION"),
        (OWL + "imports", "<urn:owned:module>", "FOREIGN_ANNOTATION"),
        (RDFS + "subClassOf", "<urn:owned:Entity>", "FOREIGN_ANNOTATION"),
        (RDFS + "comment", "_:unscoped", "FOREIGN_ANNOTATION"),
        (RDFS + "comment", '"x" . <urn:owned:x> <urn:owned:p> "injected"', "FOREIGN_ANNOTATION"),
        (TYPE, f"<{OWL}FunctionalProperty>", "FOREIGN_VOCABULARY_DECLARATION"),
        (TYPE, f"<{OWL}Class>", "FOREIGN_ANNOTATION"),
    ],
)
def test_exception_cannot_authorize_import_equivalence_structure_or_blank_objects(
    tmp_path, predicate, value, classification
):
    item = replace(
        statement(), predicate_iri=predicate, object_ntriples=value, classification=classification
    )
    with pytest.raises(RdfEngineError) as refusal:
        run(tmp_path, artifact([item]))
    assert refusal.value.code == "FOREIGN_ASSERTION_POLICY"


def test_unused_duplicate_and_owned_subject_declarations_refuse(tmp_path):
    cases = [
        (
            artifact([statement(), statement(subject="urn:foreign:Unused")]),
            "UNUSED_FOREIGN_ASSERTION",
        ),
        (artifact([statement(), statement()]), "FOREIGN_ASSERTION_POLICY"),
        (artifact([statement(subject="urn:owned:Term")]), "FOREIGN_ASSERTION_POLICY"),
        (artifact([statement(subject="urn:owned:module")]), "FOREIGN_ASSERTION_POLICY"),
    ]
    for item, code in cases:
        with pytest.raises(RdfEngineError) as refusal:
            run(tmp_path, item)
        assert refusal.value.code == code


def test_statement_remains_foreign_in_publisher_graph_when_other_module_owns_term(tmp_path):
    first = artifact()
    second = RdfArtifact(
        "urn:foreign:module",
        "TURTLE",
        f'<urn:foreign:Term> <{RDFS}label> "Owner label" .'.encode(),
        ("urn:foreign:",),
    )
    result = canonicalize_rdf(
        [first, second], root_iris=[first.artifact_iri, second.artifact_iri], work_dir=tmp_path
    )
    assert result.quad_count == 2 and len(result.foreign_assertions) == 1
    assert result.foreign_assertions[0]["artifact_iri"] == "urn:owned:module"
    assert result.foreign_assertions[0]["ownership_authorized"] is False
    assert b"<urn:foreign:module>" in result.canonical_nquads


def test_no_exception_worker_wire_matches_pre_extension_golden_bytes(tmp_path):
    item = RdfArtifact(
        "urn:fixture:module",
        "TURTLE",
        b'<urn:fixture:s> <urn:fixture:p> "old" .',
        ("urn:fixture:",),
    )
    payload = {
        "artifacts": [{**asdict(item), "content": base64.b64encode(item.content).decode()}],
        "root_iris": [item.artifact_iri],
        "limits": asdict(RdfLimits()),
    }
    output = rdf_engine_worker.process(payload, "TEST")
    assert "foreign_assertions" not in output
    assert "foreign_assertion_policy" not in output["manifest"]
    assert "foreign_assertion_count" not in output["manifest"]
    assert hashlib.sha256(ontology_import.encoded(output)).hexdigest() == (
        "740103a8ed9e6bc4bab367fce49af66213cf678d81f2153db555204a7ba12e67"
    )
    native = run(tmp_path, item)
    assert (
        native.canonical_sha256
        == "38170cc23c6b07a239c96b5997bbe387c389c6e77cc4c27ea54de656e26ee447"
    )
    assert not native.foreign_assertions and "foreign_assertion_policy" not in native.manifest


def legacy_module():
    pin = {
        "resource_id": "00000000-0000-4000-8000-000000000001",
        "version_id": "00000000-0000-4000-8000-000000000002",
        "content_hash": "a" * 64,
    }
    return {
        "source": pin,
        "artifact_iri": "urn:owned:module",
        "document": {"document_id": "doc_" + "b" * 64, "sha256": "b" * 64, "byte_length": 200},
        "format": "TURTLE",
        "owned_namespaces": ["urn:owned:"],
        "permitted_import_iris": [],
        "source_url": "https://example.test/module.ttl",
        "license": "Synthetic fixture",
        "retrieved_at": "2026-09-08T00:00:00Z",
    }


def test_old_module_request_serialization_and_hash_remain_exact():
    old = legacy_module()
    module = ModuleInput.model_validate(old)
    assert module.model_dump(mode="json") == old
    assert "foreign_assertions" not in json.loads(module.model_dump_json())
    request = {
        "source": old["source"],
        "release_label": "old",
        "publication_status": "DEVELOPMENT",
        "modules": [old],
    }
    parsed = ImportRequest.model_validate(request)
    assert ontology_import.digest(
        ontology_import.normalize(parsed).model_dump(mode="json")
    ) == ontology_import.digest(request)
    assert ontology_import.digest(module.model_dump(mode="json")) == ontology_import.digest(old)
    with pytest.raises(ValueError):
        ModuleInput.model_validate({**old, "foreign_assertions": []})
    with pytest.raises(ValueError):
        ModuleInput.model_validate(
            {**old, "foreign_assertions": [asdict(statement()), asdict(statement())]}
        )


def test_exception_budget_is_bounded_before_worker(tmp_path):
    with pytest.raises(RdfEngineError) as refusal:
        run(tmp_path, artifact([statement(subject=f"urn:foreign:{i}") for i in range(129)]))
    assert refusal.value.code == "FOREIGN_ASSERTION_BUDGET"


def test_original_prov_bytes_retain_all_1146_triples(tmp_path):
    configured = os.environ.get("G8_PROV_ARTIFACT_PATH")
    if not configured:
        pytest.skip(
            "Offline acceptance must supply the exact PROV artifact; tests never download it"
        )
    original = Path(configured).read_bytes()
    assert (
        hashlib.sha256(original).hexdigest()
        == "3d03c8e15753178541fb8cd59fbefecaf1861f9c37ef75190c6e938b85fb0c3d"
    )
    artifact_iri = "http://www.w3.org/ns/prov-o#"
    subject_predicates = {
        RDFS + "comment": [TYPE, RDFS + "comment", RDFS + "isDefinedBy"],
        RDFS + "isDefinedBy": [TYPE],
        RDFS + "label": [TYPE, RDFS + "comment", RDFS + "isDefinedBy"],
        RDFS + "seeAlso": [TYPE, RDFS + "comment"],
        OWL + "Thing": [TYPE],
        OWL + "versionInfo": [TYPE],
    }
    exceptions = []
    for subject, predicates in subject_predicates.items():
        for predicate in predicates:
            value = f"<{OWL}Class>" if subject == OWL + "Thing" else f"<{OWL}AnnotationProperty>"
            if predicate == RDFS + "comment":
                value = '""@en'
            if predicate == RDFS + "isDefinedBy":
                value = f"<{artifact_iri}>"
            exceptions.append(
                RdfForeignAssertion(
                    subject,
                    predicate,
                    value,
                    "FOREIGN_VOCABULARY_DECLARATION" if predicate == TYPE else "FOREIGN_ANNOTATION",
                    REASON,
                )
            )
    item = RdfArtifact(
        artifact_iri,
        "TURTLE",
        original,
        ("http://www.w3.org/ns/prov#",),
        foreign_assertions=tuple(exceptions),
    )
    result = run(tmp_path, item)
    assert result.quad_count == 1146 and result.manifest["foreign_assertion_count"] == 11
    source = ox.Dataset(
        ox.Quad(q.subject, q.predicate, q.object, ox.NamedNode(artifact_iri))
        for q in ox.parse(original, format=ox.RdfFormat.TURTLE, base_iri=artifact_iri)
    )
    source.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)
    serialized = ox.serialize(source, format=ox.RdfFormat.N_QUADS)
    expected = b"".join(line + b"\n" for line in sorted(serialized.splitlines()) if line)
    assert result.canonical_nquads == expected
    assert Path(configured).read_bytes() == original
    with pytest.raises(RdfEngineError):
        run(tmp_path, replace(item, foreign_assertions=()))
