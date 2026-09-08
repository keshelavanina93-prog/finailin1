"""Native synthetic retained RDF -> reviewed profiles -> durable validation evidence.

No authentic ontology, business facts, certification or production acceptance is claimed.
"""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from test_definition_history import DB, retained  # noqa: F401
from test_external_ontology_import import (
    REASON,
    approve,
    lifecycle_change,
    native_import,  # noqa: F401
    request_for,
    resource_pin,
)

from finai_api.config import get_settings
from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    GraphSelection,
    OntologyProfileDefinition,
    ValidationRunRequest,
)
from finai_api.services import constraint_validator as engine
from finai_api.services import ontology_import as imports
from finai_api.services import ontology_profiles as profiles
from finai_api.services import ontology_validation_runs as runs
from finai_api.services import report_workflows as records
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def validation_case(native_import, monkeypatch):  # noqa: F811
    case = native_import
    case.maker = case.maker.model_copy(update={"permissions": (*case.maker.permissions, "read")})
    case.checker = case.checker.model_copy(
        update={"permissions": (*case.checker.permissions, "read")}
    )
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps({"synthetic-validator-token": case.maker.model_dump(mode="json")}),
    )
    get_settings.cache_clear()

    def release(request):
        prepared = imports.prepare(case.maker, request)
        approve(case.checker, prepared["proposal"]["proposal"]["proposal_id"])
        return resource_pin(
            resources.get_resource(case.maker, UUID(prepared["release_id"]))["resource"]
        )

    data_pin = release(case.request)

    def build(*, outcome="VIOLATES"):
        target = (
            "sh:targetClass ex:Absent" if outcome == "NOT_EVALUATED" else "sh:targetNode ex:Concept"
        )
        count = 1 if outcome == "CONFORMS" else 2
        raw = (
            f"@prefix ex: <{case.namespace}> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "ex:artifact a owl:Ontology .\n"
            f"ex:ConceptShape a sh:NodeShape; {target}; "
            f"sh:property [ sh:path rdfs:label; sh:minCount {count} ] .\n"
        ).encode()
        document = imports.retained(case.maker, "synthetic-shapes.ttl", raw)
        shape_pin = release(
            request_for(
                resource_pin(case.source_row),
                case.definition,
                document.model_dump(mode="json"),
                case.namespace,
                release="synthetic-shapes-" + uuid4().hex,
            )
        )
        data = GraphSelection(release=data_pin, graph_iris=(case.namespace + "artifact",))
        profile = profiles.propose_profile(
            case.maker,
            OntologyProfileDefinition(
                purpose=REASON,
                domain_pack="synthetic-contract",
                members=(data,),
            ),
        )
        if profile.decision is None:
            approve(case.checker, profile.proposal.proposal_id)
        profile_pin = resource_pin(
            resources.get_resource(
                case.maker,
                profile.proposal.mutations[0].resource_id,
            )["resource"]
        )
        constraint = profiles.propose_constraint_profile(
            case.maker,
            ConstraintProfileDefinition(
                ontology_profile=profile_pin,
                shapes=GraphSelection(release=shape_pin, graph_iris=(case.namespace + "artifact",)),
            ),
        )
        approve(case.checker, constraint.proposal.proposal_id)
        constraint_pin = resource_pin(
            resources.get_resource(
                case.maker,
                constraint.proposal.mutations[0].resource_id,
            )["resource"]
        )
        request = ValidationRunRequest(
            request_id=uuid4(),
            constraint_profile=constraint_pin,
            data=data,
        )
        return SimpleNamespace(**{**vars(case), "request": request})

    yield build
    get_settings.cache_clear()


def context(case, identity):
    return {
        "workflow_id": identity,
        "actor_id": case.maker.actor_id,
        "scope": case.maker.scope.model_dump(mode="json"),
    }


@pytest.fixture
def published_validation_case(validation_case):
    case = validation_case(outcome="CONFORMS")
    case.workflow_id = runs.retain(case.maker, case.request)
    case.terminal = runs.execute_retained(case.maker, case.workflow_id)
    case.publication = runs.publish(context(case, case.workflow_id))
    case.report = runs.publication_context(case.checker, case.workflow_id)[2]
    return case


@DB
@pytest.mark.parametrize("outcome", ["CONFORMS", "VIOLATES", "NOT_EVALUATED"])
def test_native_report_publication_replay_and_outcome_evidence(
    validation_case, monkeypatch, outcome
):
    case = validation_case(outcome=outcome)
    identity = runs.retain(case.maker, case.request)
    assert runs.retain(case.maker, case.request) == identity
    assert runs.read(case.maker, identity)["state"] == "INTENT_RETAINED"
    assert runs.load(context(case, identity))["plan_sha256"]
    frozen = runs.read(case.maker, identity)["request"]
    records.event(case.maker, identity, "validation:started", {"state": "RUNNING"})
    with pytest.raises(psycopg.errors.RaiseException):
        records.event(
            case.maker,
            identity,
            runs.TERMINAL,
            {
                "state": "COMPLETED",
                "report": {
                    "contract": "ontology-validation-report/1",
                    "workflow_id": identity,
                    "request_sha256": frozen["plan"]["request_sha256"],
                    "plan_sha256": "0" * 64,
                    "report": frozen["plan"]["data"]["canonical_dataset"],
                    "outcome": "CONFORMS",
                    "business_effect_authorized": False,
                },
            },
        )
    with pytest.raises(WorkspaceError, match="completed report"):
        runs.publish(context(case, identity))
    terminal = runs.execute(context(case, identity))
    assert terminal["outcome"] == outcome
    retained_report = runs.read(case.maker, identity)
    assert retained_report["state"] == "COMPLETED"
    assert retained_report["report"]["result"]["conforms"] is (
        True if outcome == "CONFORMS" else False if outcome == "VIOLATES" else None
    )
    assert retained_report["business_effect_authorized"] is False
    assert retained_report["current_use_authorized"] is False
    if outcome != "NOT_EVALUATED":
        assert retained_report["report"]["result"]["evaluated_constraint_count"] > 0
    else:
        assert retained_report["report"]["result"]["evaluated_constraint_count"] == 0

    def no_reexecution(*_args, **_kwargs):
        pytest.fail("A retained terminal must survive a lost activity acknowledgement")

    monkeypatch.setattr(engine, "validate_constraints", no_reexecution)
    assert runs.execute_retained(case.maker, identity) == terminal
    publication = runs.publish(context(case, identity))
    assert runs.publish(context(case, identity)) == publication
    request, plan, report = runs.publication_context(case.checker, identity)
    assert request == case.request and report.model_dump(mode="json") == terminal
    assert plan.constraint_profile == case.request.constraint_profile
    assert runs.read(case.maker, identity)["state"] == "PUBLISHED"
    with pytest.raises(WorkspaceError, match="cannot be cancelled"):
        runs.cancel(case.maker, identity, uuid4(), REASON)


@DB
def test_native_intent_scope_actor_content_and_permission_boundaries(validation_case):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    with pytest.raises(HTTPException) as permission:
        runs.retain(case.maker.model_copy(update={"permissions": ("ontology_read",)}), case.request)
    assert permission.value.status_code == 403
    with pytest.raises(WorkspaceError, match="used differently"):
        runs.retain(case.checker, case.request)
    with pytest.raises(WorkspaceError) as other_actor:
        runs.read(case.checker, identity)
    assert other_actor.value.status == 403
    wrong_scope = case.maker.model_copy(
        update={
            "scope": case.maker.scope.model_copy(
                update={"period": "2026-07"},
            )
        }
    )
    with pytest.raises(WorkspaceError) as scoped:
        runs.read(wrong_scope, identity)
    assert scoped.value.status == 404
    with pytest.raises(psycopg.Error), records.scope_connection(case.maker) as conn:
        records.set_scope(conn, case.maker)
        conn.execute(
            "INSERT INTO workflow_events(tenant_id,workflow_id,exact_scope,event_id,payload) "
            "VALUES(%s,%s,%s,'validation:started',%s)",
            (
                case.maker.scope.tenant_id,
                identity,
                Jsonb(wrong_scope.scope.model_dump(mode="json")),
                Jsonb({"state": "RUNNING"}),
            ),
        )
    changed = case.request.model_copy(
        update={
            "data": case.request.data.model_copy(
                update={"graph_iris": (case.namespace + "not-member",)},
            )
        }
    )
    with pytest.raises(WorkspaceError):
        runs.retain(case.maker, changed)
    assert runs.read(case.maker, identity)["state"] == "INTENT_RETAINED"
    with pytest.raises(WorkspaceError, match="owner"):
        runs.execute_retained(case.checker, identity)
    with pytest.raises(WorkspaceError, match="owner"):
        runs.cancel(case.checker, identity, uuid4(), REASON)


@DB
def test_native_cancellation_arbitrates_completion_and_publication(validation_case, monkeypatch):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    engine_validate = engine.validate_constraints
    command_id = uuid4()

    def cancel_after_work(*args, **kwargs):
        result = engine_validate(*args, **kwargs)
        runs.cancel(case.maker, identity, command_id, REASON)
        return result

    monkeypatch.setattr(engine, "validate_constraints", cancel_after_work)
    with pytest.raises(WorkspaceError, match="cancelled before"):
        runs.execute_retained(case.maker, identity)
    assert runs.cancel(case.maker, identity, command_id, REASON)["state"] == "CANCELLED"
    with pytest.raises(WorkspaceError, match="conflicts"):
        runs.cancel(case.maker, identity, uuid4(), REASON)
    result = runs.read(case.maker, identity)
    assert result["state"] == "CANCELLED" and result["terminal"] is None
    assert result["publications"] == []
    with pytest.raises(WorkspaceError, match="cancelled"):
        runs.load(context(case, identity))


@DB
def test_native_current_publisher_withdrawal_blocks_report_completion(validation_case, monkeypatch):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    engine_validate = engine.validate_constraints
    withdrawn = []

    def withdraw_after_work(*args, **kwargs):
        result = engine_validate(*args, **kwargs)
        observed = lifecycle_change(case, "OBSERVED")
        lifecycle_change(case, "REVOKED", expected=observed)
        withdrawn.append(True)
        return result

    monkeypatch.setattr(engine, "validate_constraints", withdraw_after_work)
    with pytest.raises(WorkspaceError) as refusal:
        runs.execute_retained(case.maker, identity)
    assert withdrawn == [True], refusal.value.detail
    assert runs.read(case.maker, identity)["terminal"] is None
    with pytest.raises(WorkspaceError):
        runs.retain(case.maker, case.request.model_copy(update={"request_id": uuid4()}))


@DB
def test_native_withdrawal_after_completion_preserves_history_and_blocks_publication(
    validation_case,
):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    terminal = runs.execute_retained(case.maker, identity)
    observed = lifecycle_change(case, "OBSERVED")
    lifecycle_change(case, "REVOKED", expected=observed)
    with pytest.raises(WorkspaceError):
        runs.publish(context(case, identity))
    result = runs.read(case.maker, identity)
    assert result["terminal"] == terminal and result["publications"] == []
    assert result["current_use_authorized"] is False


@DB
def test_native_actor_grant_removed_during_validation_blocks_completion(
    validation_case, monkeypatch
):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    engine_validate = engine.validate_constraints
    revoked = []

    def remove_grant_after_work(*args, **kwargs):
        result = engine_validate(*args, **kwargs)
        monkeypatch.setenv("FINAI_ACCESS_TOKENS", "{}")
        get_settings.cache_clear()
        revoked.append(True)
        return result

    monkeypatch.setattr(engine, "validate_constraints", remove_grant_after_work)
    with pytest.raises(WorkspaceError, match="no longer has access"):
        runs.execute_retained(case.maker, identity)
    assert revoked == [True]
    assert runs.read(case.maker, identity)["terminal"] is None


@DB
def test_native_worker_refusal_is_retained_but_transient_failure_is_retryable(
    validation_case, monkeypatch
):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)

    def infrastructure(*_args, **_kwargs):
        raise engine.ConstraintValidatorError("WORKER_FAILED", "must not retain source or secrets")

    monkeypatch.setattr(engine, "validate_constraints", infrastructure)
    with pytest.raises(WorkspaceError) as failed:
        runs.execute_retained(case.maker, identity)
    assert failed.value.status == 503
    assert runs.read(case.maker, identity)["terminal"] is None

    def refused(*_args, **_kwargs):
        raise engine.ConstraintValidatorError(
            "UNSUPPORTED_SHAPES", "must not retain source or secrets"
        )

    monkeypatch.setattr(engine, "validate_constraints", refused)
    terminal = runs.execute_retained(case.maker, identity)
    assert terminal["outcome"] == "REFUSED"
    envelope = runs.read(case.maker, identity)["report"]
    assert envelope["conforms"] is None and envelope["refusal_code"] == "UNSUPPORTED_SHAPES"
    assert "must not retain" not in json.dumps(envelope)
    assert runs.publish(context(case, identity))["publication_id"]
