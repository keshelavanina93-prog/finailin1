"""Small retained foreign-assertion review journey for the native PR gate."""

import json
from hashlib import sha256
from uuid import UUID

import pyoxigraph as ox
import pytest
from test_definition_history import DB, retained  # noqa: F401
from test_external_ontology_import import approve, native_import, proposal_from  # noqa: F401

from finai_api.domain.external_ontology import ImportRequest, RetainedDocument
from finai_api.services import ontology_import as imports
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


@DB
def test_review_retains_exact_foreign_assertions_and_order_independent_replay(request):
    case = request.getfixturevalue("native_import")
    subject = "urn:synthetic:foreign:Class"
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    label = "http://www.w3.org/2000/01/rdf-schema#label"
    class_iri = "http://www.w3.org/2002/07/owl#Class"
    raw = case.raw + (
        f'<{subject}> <{label}> "Foreign publisher assertion" .\n'
        f"<{subject}> <{rdf_type}> <{class_iri}> .\n"
    ).encode()
    document = imports.retained(case.maker, "synthetic-foreign-assertions.ttl", raw)
    declarations = [
        {
            "subject_iri": subject,
            "predicate_iri": predicate,
            "object_ntriples": value,
            "classification": classification,
            "reason": "Preserve this exact source assertion without foreign namespace ownership.",
        }
        for predicate, value, classification in (
            (label, '"Foreign publisher assertion"', "FOREIGN_ANNOTATION"),
            (rdf_type, f"<{class_iri}>", "FOREIGN_VOCABULARY_DECLARATION"),
        )
    ]
    submitted = case.request.model_dump(mode="json")
    submitted["modules"][0].update(
        document=document.model_dump(mode="json"), foreign_assertions=declarations
    )
    first = imports.prepare(case.maker, ImportRequest.model_validate(submitted))
    proposal = proposal_from(first)
    submitted["modules"][0]["foreign_assertions"] = list(reversed(declarations))
    reordered = ImportRequest.model_validate(submitted)
    assert imports.prepare(case.maker, reordered) == first
    with pytest.raises(WorkspaceError) as denied:
        approve(case.maker, proposal.proposal_id)
    assert denied.value.status == 403
    approve(case.checker, proposal.proposal_id)

    release = resources.get_resource(case.reader, UUID(first["release_id"]))["resource"]
    module = release["attributes"]["definition"]["request"]["modules"][0]
    expected = sorted(declarations, key=lambda item: (item["subject_iri"], item["predicate_iri"]))
    assert module["foreign_assertions"] == expected
    assert module["owned_namespaces"] == [case.namespace]
    assert module["source"] == case.request.source.model_dump(mode="json")
    dataset = imports.read_document(case.reader, RetainedDocument(**first["canonical_dataset"]))
    foreign = [
        q for q in ox.parse(dataset, format=ox.RdfFormat.N_QUADS)
        if q.subject == ox.NamedNode(subject)
    ]
    assert {(q.predicate.value, str(q.object), q.graph_name.value) for q in foreign} == {
        (label, '"Foreign publisher assertion"', module["artifact_iri"]),
        (rdf_type, f"<{class_iri}>", module["artifact_iri"]),
    }
    report = json.loads(imports.read_document(case.reader, RetainedDocument(**first["report"])))
    assert report["foreign_assertions"] == [{
        "artifact_iri": module["artifact_iri"], "source_sha256": sha256(raw).hexdigest(),
        "assertions": expected, "ownership_authorized": False, "equivalence_authorized": False,
    }]
    replay = imports.prepare(case.maker, reordered)
    assert replay["status"] == "ALREADY_RETAINED"
    assert replay["canonical_dataset"] == first["canonical_dataset"]
    assert replay["report"] == first["report"]
