"""Opt-in public-source retention proof with synthetic actors in a disposable database."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pyoxigraph as ox
import pytest
from psycopg.conninfo import conninfo_to_dict
from test_definition_history import retained  # noqa: F401
from test_external_ontology_import import (
    approve,
    dependency_rows,
    lifecycle_change,
    proposal_from,
    request_for,
    resource_pin,
    scoped_versions,
    source_definition,
)

from finai_api.domain.external_ontology import (
    ImportRequest,
    ReleaseInspectionRequest,
    RetainedDocument,
    SourceDefinition,
)
from finai_api.services import external_ontology_queries as queries
from finai_api.services import ontology_import as imports
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

PROV_SHA = "3d03c8e15753178541fb8cd59fbefecaf1861f9c37ef75190c6e938b85fb0c3d"
PROV_GRAPH = "http://www.w3.org/ns/prov-o#"
PROV_NAMESPACE = "http://www.w3.org/ns/prov#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
BASELINE_COMMIT = "e4a7e47eea5834773704f353c178a09014c2cfa1"
BASELINE_TREE_SHA = "a0cc256680c7c055d30614fe0ea89f3e26ea1700f7a9c0ca2fd174975e75e574"


def verified_baseline(path: Path, commit: str) -> Path:
    """Verify every archived source file before executing the pinned legacy importer."""
    assert commit == BASELINE_COMMIT, "The explicit pre-extension commit pin differs"
    baseline = path.resolve(strict=True)
    assert baseline.is_dir() and baseline.drive.lower() == "d:", "Baseline must reside on D:"
    files = sorted(p for p in baseline.rglob("*") if p.is_file())
    assert len(files) == 184, "Baseline source file inventory differs from the pinned commit"
    records = []
    for source in files:
        assert not source.is_symlink() and not source.is_junction()
        assert source.resolve().is_relative_to(baseline)
        assert source.stat().st_size <= 2 * 1024 * 1024, "Unexpected baseline source size"
        records.append(
            source.relative_to(baseline).as_posix()
            + "\0"
            + sha256(source.read_bytes()).hexdigest()
            + "\n"
        )
    actual = sha256("".join(sorted(records)).encode("utf-8")).hexdigest()
    assert actual == BASELINE_TREE_SHA, "Baseline source hashes differ from the pinned commit"
    return baseline


@pytest.mark.skipif(
    os.getenv("G8_FOREIGN_ASSERTIONS_NATIVE") != "1",
    reason="Explicit disposable public-source acceptance only",
)
def test_original_prov_review_replay_withdrawal_and_pre_extension_release(request):
    connection_info = conninfo_to_dict(os.environ["FINAI_DATABASE_URL"])
    assert connection_info["host"] == "127.0.0.1" and connection_info["port"] == "55441"
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as connection:
        directory = connection.execute("SHOW data_directory").fetchone()[0]
    assert directory.replace("\\", "/").lower() == ("d:/finai/g8-ci-repair/.finai/data/postgres-ci")
    assert os.environ["FINAI_S3_ENDPOINT"] == "http://127.0.0.1:9064"
    artifact = Path(os.environ["G8_PROV_ARTIFACT_PATH"])
    original = artifact.read_bytes()
    assert sha256(original).hexdigest() == PROV_SHA
    baseline = verified_baseline(
        Path(os.environ["G8_PRE_EXTENSION_SRC"]), os.environ["G8_PRE_EXTENSION_COMMIT"]
    )
    # No fixture writes occur until the physical database and input hashes are verified.
    reader, _ = request.getfixturevalue("retained")
    entity = os.environ["G8_FOREIGN_ASSERTIONS_ENTITY"]
    assert entity.startswith("synthetic-")
    reader = reader.model_copy(
        update={"scope": reader.scope.model_copy(update={"legal_entity_id": entity})}
    )
    maker = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
                "ingest",
            )
        }
    )
    checker = maker.model_copy(update={"actor_id": "synthetic-independent-prov-checker"})
    namespace = "https://example.invalid/legacy-" + uuid4().hex + "/"
    legacy_definition = source_definition(namespace)
    legacy_proposal = imports.propose_source(maker, legacy_definition)
    approve(checker, legacy_proposal.proposal.proposal_id)
    legacy_source = resources.get_resource(
        reader, legacy_proposal.proposal.mutations[0].resource_id
    )["resource"]
    legacy_document = imports.retained(
        maker, "legacy.ttl", (f'<{namespace}Term> <{RDFS}label> "legacy fixture" .').encode()
    )
    case = SimpleNamespace(
        maker=maker,
        checker=checker,
        reader=reader,
        request=request_for(
            resource_pin(legacy_source),
            legacy_definition,
            legacy_document.model_dump(mode="json"),
            namespace,
        ),
    )
    assert case.maker.actor_id != case.checker.actor_id
    payload = {
        "maker": case.maker.model_dump(mode="json"),
        "checker": case.checker.model_dump(mode="json"),
        "request": case.request.model_dump(mode="json"),
    }
    environment = dict(os.environ, PYTHONPATH=str(baseline), PYTHONDONTWRITEBYTECODE="1")
    # Execute the actual pre-extension importer, approval hook, and capped worker.
    old = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json, sys
from uuid import UUID
from finai_api.domain.review import Principal
from finai_api.domain.resources import ResourceReview
from finai_api.domain.external_ontology import ImportRequest
from finai_api.services import ontology_import as imports, resources
value=json.load(sys.stdin)
maker=Principal.model_validate(value['maker'])
checker=Principal.model_validate(value['checker'])
prepared=imports.prepare(maker,ImportRequest.model_validate(value['request']))
assert prepared['status']=='REVIEW_REQUIRED'
resources.review(checker,UUID(prepared['proposal']['proposal']['proposal_id']),
 ResourceReview(decision='APPROVED',rationale='Independent pre-extension retained replay fixture.'))
print(json.dumps(prepared))
""",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=environment,
        timeout=60,
        cwd=Path(os.environ["FINAI_RUNTIME_ROOT"]),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert old.returncode == 0, "Pre-extension native publication failed"
    previous = json.loads(old.stdout)
    before = scoped_versions(case.maker)
    replay = imports.prepare(case.maker, case.request)
    assert replay["status"] == "ALREADY_RETAINED"
    for field in ("release_id", "canonical_dataset", "report"):
        assert replay[field] == previous[field]
    assert scoped_versions(case.maker) == before
    old_report = json.loads(
        imports.read_document(case.maker, RetainedDocument.model_validate(previous["report"]))
    )
    assert "foreign_assertions" not in old_report
    assert "foreign_assertion_policy" not in old_report["engine_manifest"]

    definition = SourceDefinition(
        publisher="W3C PROV Working Group (public artifact; synthetic local review)",
        source_url="https://www.w3.org/TR/2013/REC-prov-o-20130430/",
        namespaces=[PROV_NAMESPACE],
        license="Public W3C PROV-O local verification artifact; no licensing conclusion",
        supported_formats=["TURTLE"],
    )
    proposal = imports.propose_source(case.maker, definition)
    with pytest.raises(WorkspaceError) as self_review:
        approve(case.maker, proposal.proposal.proposal_id)
    assert self_review.value.status == 403
    approve(case.checker, proposal.proposal.proposal_id)
    source_id = proposal.proposal.mutations[0].resource_id
    source_row = resources.get_resource(case.reader, source_id)["resource"]
    document = imports.retained(case.maker, artifact.name, original)
    triples = list(ox.parse(original, format=ox.RdfFormat.TURTLE, base_iri=PROV_GRAPH))
    assert len(triples) == 1146
    assertions = []
    for triple in triples:
        if isinstance(triple.subject, ox.NamedNode) and (
            triple.subject.value != PROV_GRAPH
            and not triple.subject.value.startswith(PROV_NAMESPACE)
        ):
            assertions.append(
                {
                    "subject_iri": triple.subject.value,
                    "predicate_iri": triple.predicate.value,
                    "object_ntriples": str(triple.object),
                    "classification": "FOREIGN_VOCABULARY_DECLARATION"
                    if triple.predicate.value == RDF_TYPE
                    else "FOREIGN_ANNOTATION",
                    "reason": "Retain this exact W3C artifact assertion without foreign ownership.",
                }
            )
    assert len(assertions) == 11
    assert {entry["subject_iri"] for entry in assertions} == {
        RDFS + "comment",
        RDFS + "isDefinedBy",
        RDFS + "label",
        RDFS + "seeAlso",
        OWL + "Thing",
        OWL + "versionInfo",
    }
    source_pin = resource_pin(source_row).model_dump(mode="json")
    value = ImportRequest.model_validate(
        {
            "source": source_pin,
            "release_label": "PROV-O-2013-04-30-native-proof-" + uuid4().hex,
            "publication_status": "DEVELOPMENT",
            "modules": [
                {
                    "source": source_pin,
                    "artifact_iri": PROV_GRAPH,
                    "document": document.model_dump(mode="json"),
                    "format": "TURTLE",
                    "owned_namespaces": [PROV_NAMESPACE],
                    "permitted_import_iris": [],
                    "source_url": definition.source_url,
                    "license": definition.license,
                    "retrieved_at": datetime.fromtimestamp(
                        artifact.stat().st_mtime, UTC
                    ).isoformat(),
                    "foreign_assertions": assertions,
                }
            ],
        }
    )
    prepared = imports.prepare(case.maker, value)
    release_proposal = proposal_from(prepared)
    assert {m.object_type for m in release_proposal.mutations} == {
        "SourceEvidence",
        "ExternalOntologyRelease",
        "ExternalOntologyModule",
        "OntologyImportRun",
    }
    with pytest.raises(WorkspaceError) as self_review:
        approve(case.maker, release_proposal.proposal_id)
    assert self_review.value.status == 403
    approve(case.checker, release_proposal.proposal_id)
    row = resources.get_resource(case.reader, UUID(prepared["release_id"]))["resource"]
    pin = resource_pin(row)
    declared = row["attributes"]["definition"]
    assert declared["request"]["modules"][0]["owned_namespaces"] == [PROV_NAMESPACE]
    assert len(declared["request"]["modules"][0]["foreign_assertions"]) == 11
    assert imports.read_document(case.maker, document) == original == artifact.read_bytes()
    dataset = imports.read_document(case.maker, RetainedDocument(**prepared["canonical_dataset"]))
    report = json.loads(imports.read_document(case.maker, RetainedDocument(**prepared["report"])))
    assert len(list(ox.parse(dataset, format=ox.RdfFormat.N_QUADS))) == 1146
    assert report["quad_count"] == 1146 and report["business_effect_authorized"] is False
    assert report["foreign_assertions"][0]["source_sha256"] == PROV_SHA
    assert report["foreign_assertions"][0]["ownership_authorized"] is False
    assert report["foreign_assertions"][0]["equivalence_authorized"] is False
    dependencies = dependency_rows(case.reader, row["version_id"])
    assert any(str(d["target_version_id"]) == source_pin["version_id"] for d in dependencies)
    before = scoped_versions(case.maker)
    repeated = imports.prepare(case.maker, value)
    assert repeated["status"] == "ALREADY_RETAINED"
    assert repeated["report"] == prepared["report"]
    assert repeated["canonical_dataset"] == prepared["canonical_dataset"]
    assert scoped_versions(case.maker) == before
    inspection = ReleaseInspectionRequest(release=pin)
    assert queries.release_metadata(case.reader, inspection)["definition"] == declared
    foreign = [
        q
        for q in ox.parse(dataset, format=ox.RdfFormat.N_QUADS)
        if q.subject == ox.NamedNode(OWL + "Thing")
    ]
    assert foreign == [
        ox.Quad(
            ox.NamedNode(OWL + "Thing"),
            ox.NamedNode(RDF_TYPE),
            ox.NamedNode(OWL + "Class"),
            ox.NamedNode(PROV_GRAPH),
        )
    ]
    known_at = datetime.now(UTC)
    lifecycle_change(
        SimpleNamespace(
            maker=case.maker,
            checker=case.checker,
            source_id=source_id,
            source_row=source_row,
        ),
        "OBSERVED",
        availability="UNAVAILABLE",
    )
    for current in (
        lambda: queries.release_metadata(case.reader, inspection),
        lambda: imports.prepare(case.maker, value),
    ):
        with pytest.raises(WorkspaceError) as refusal:
            current()
        assert refusal.value.status == 409
    historical = queries.release_metadata(
        case.reader,
        inspection.model_copy(
            update={
                "mode": "HISTORICAL_INSPECTION",
                "known_at": known_at,
            }
        ),
    )
    assert historical["definition"] == declared
    output = Path(os.environ["G8_FOREIGN_ASSERTIONS_EVIDENCE"])
    assert output.is_absolute() and output.drive.lower() == "d:"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "evidence_class": "PUBLIC_SOURCE_SYNTHETIC_ACTORS_DISPOSABLE_NATIVE",
                "scope": case.maker.scope.model_dump(mode="json"),
                "maker": case.maker.actor_id,
                "checker": case.checker.actor_id,
                "source_pin": source_pin,
                "release_pin": pin.model_dump(mode="json"),
                "source_sha256": PROV_SHA,
                "dataset": prepared["canonical_dataset"],
                "report": prepared["report"],
                "quad_count": 1146,
                "exact_foreign_assertions": 11,
                "legacy_release_id": previous["release_id"],
                "legacy_report": previous["report"],
                "legacy_dataset": previous["canonical_dataset"],
                "old_release_replay": "UNCHANGED",
                "self_review": "REFUSED",
                "publisher_withdrawal_current_use": "REFUSED",
                "historical_exact_release": "RETAINED",
                "ownership_authorized": False,
                "equivalence_authorized": False,
                "constraint_validation": "NOT_PERFORMED",
                "standards_conformance": "NOT_ESTABLISHED",
                "business_effect_authorized": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
