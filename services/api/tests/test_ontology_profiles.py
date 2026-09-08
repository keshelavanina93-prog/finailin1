"""Synthetic exact profile authority through native independent resource publication."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_definition_history import DB, retained  # noqa: F401
from test_external_ontology_import import (
    approve,
    dependency_rows,
    lifecycle_change,
    native_import,  # noqa: F401
    proposal_from,
    resource_pin,
    scoped_versions,
)
from test_ontology_validation_runs import published_validation_case, validation_case  # noqa: F401

from finai_api.config import get_settings
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    GraphSelection,
    OntologyProfileDefinition,
    ValidationRunRequest,
)
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.main import app
from finai_api.services import ontology_import as imports
from finai_api.services import ontology_profiles as profiles
from finai_api.services import ontology_validation_runs as runs
from finai_api.services import resources
from finai_api.services.operator_workbench import listing as workbench_listing
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def profile_case(native_import):  # noqa: F811
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    approve(case.checker, proposal_from(prepared).proposal_id)
    case.release = resources.get_resource(case.reader, UUID(prepared["release_id"]))["resource"]
    case.graph = GraphSelection(
        release=resource_pin(case.release),
        graph_iris=(case.namespace + "artifact",),
    )
    case.profile = OntologyProfileDefinition(
        purpose="Synthetic retained profile for exact external meaning only",
        domain_pack="synthetic-fixture",
        members=(case.graph,),
    )
    return case


def approved_profiles(case):
    proposed = profiles.propose_profile(case.maker, case.profile)
    approve(case.checker, proposed.proposal.proposal_id)
    profile = resources.get_resource(case.reader, proposed.proposal.mutations[0].resource_id)[
        "resource"
    ]
    definition = ConstraintProfileDefinition(
        ontology_profile=resource_pin(profile), shapes=case.graph
    )
    constrained = profiles.propose_constraint_profile(case.maker, definition)
    approve(case.checker, constrained.proposal.proposal_id)
    constraint = resources.get_resource(case.reader, constrained.proposal.mutations[0].resource_id)[
        "resource"
    ]
    return profile, constraint, definition


@DB
def test_exact_profile_review_dependencies_runtime_membership_and_replay(profile_case):
    case = profile_case
    proposed = profiles.propose_profile(case.maker, case.profile)
    before = scoped_versions(case.maker)
    assert profiles.propose_profile(case.maker, case.profile) == proposed
    with pytest.raises(WorkspaceError) as self_review:
        approve(case.maker, proposed.proposal.proposal_id)
    assert self_review.value.status == 403
    assert scoped_versions(case.maker) == before
    profile, constraint, definition = approved_profiles(case)
    expected = {
        "ONTOLOGY_PROFILE:PROFILE": resource_pin(profile),
        "ONTOLOGY_PROFILE:MEMBER:0": case.graph.release,
        "ONTOLOGY_PROFILE:SHAPES": case.graph.release,
        "ONTOLOGY_PROFILE:MEMBER:0:PUBLISHER:0": resource_pin(case.source_row),
        "ONTOLOGY_PROFILE:SHAPES:PUBLISHER:1": resource_pin(case.source_row),
    }
    deps = {row["relation"]: row for row in dependency_rows(case.reader, constraint["version_id"])}
    for relation, pin in expected.items():
        assert str(deps[relation]["target_resource_id"]) == str(pin.resource_id)
        assert str(deps[relation]["target_version_id"]) == str(pin.version_id)
    request = ValidationRunRequest(
        request_id=uuid4(),
        constraint_profile=resource_pin(constraint),
        data=case.graph,
    )
    resolved = profiles.resolve_run(case.reader, request)
    assert resolved[0] == case.profile
    assert resolved[1] == definition
    assert resolved[2] == resolved[3]
    assert (
        resolved[2].canonical_dataset.sha256
        == case.release["attributes"]["definition"]["canonical_dataset"]["sha256"]
    )
    assert not resolved[0].business_effect_authorized
    accepted = scoped_versions(case.maker)
    assert profiles.propose_profile(case.maker, case.profile).decision == "APPROVED"
    assert profiles.propose_constraint_profile(case.maker, definition).decision == "APPROVED"
    assert scoped_versions(case.maker) == accepted


@DB
def test_profiles_refuse_wrong_pins_graphs_and_cross_scope_without_publication(profile_case):
    case = profile_case
    before = scoped_versions(case.maker)
    for pin in (
        case.graph.release.model_copy(update={"content_hash": "a" * 64}),
        case.graph.release.model_copy(update={"version_id": uuid4()}),
        resource_pin(case.source_row),
    ):
        definition = case.profile.model_copy(
            update={
                "members": (case.graph.model_copy(update={"release": pin}),),
            }
        )
        with pytest.raises(WorkspaceError) as refused:
            profiles.propose_profile(case.maker, definition)
        assert refused.value.status in {404, 409}
    unknown = case.profile.model_copy(
        update={
            "members": (case.graph.model_copy(update={"graph_iris": (case.namespace + "absent",)}),)
        }
    )
    with pytest.raises(WorkspaceError, match="not members"):
        profiles.propose_profile(case.maker, unknown)
    other = case.maker.model_copy(
        update={
            "scope": case.maker.scope.model_copy(
                update={
                    "legal_entity_id": "synthetic-other-" + uuid4().hex,
                }
            )
        }
    )
    with pytest.raises(WorkspaceError) as refused:
        profiles.propose_profile(other, case.profile)
    assert refused.value.status == 409
    with pytest.raises(HTTPException) as permission:
        profiles.propose_profile(case.reader, case.profile)
    assert permission.value.status_code == 403
    assert scoped_versions(case.maker) == before


@DB
def test_constraints_require_existing_approved_profile_and_exact_runtime_membership(profile_case):
    case = profile_case
    pending = profiles.propose_profile(case.maker, case.profile)
    item = pending.proposal.mutations[0]
    from uuid import uuid5

    constraint = ConstraintProfileDefinition(
        ontology_profile={
            "resource_id": item.resource_id,
            "version_id": uuid5(pending.proposal.proposal_id, str(item.resource_id)),
            "content_hash": "b" * 64,
        },
        shapes=case.graph,
    )
    with pytest.raises(WorkspaceError) as refused:
        profiles.propose_constraint_profile(case.maker, constraint)
    assert refused.value.status == 404
    _, accepted, _ = approved_profiles(case)
    bad_data = case.graph.model_copy(update={"graph_iris": (case.namespace + "unreviewed",)})
    with pytest.raises(WorkspaceError, match="outside the reviewed profile"):
        profiles.resolve_run(
            case.reader,
            ValidationRunRequest(
                request_id=uuid4(),
                constraint_profile=resource_pin(accepted),
                data=bad_data,
            ),
        )


@DB
@pytest.mark.parametrize("dependency", ["publisher", "release", "profile"])
def test_generic_profile_proposals_cannot_mutate_dependencies_atomically(profile_case, dependency):
    case = profile_case
    profile, _, definition = approved_profiles(case)
    item = profiles.mutation(case.maker, "ExternalConstraintProfile", definition)
    row = {"publisher": case.source_row, "release": case.release, "profile": profile}[dependency]
    altered = ResourceMutation(
        resource_id=row["resource_id"],
        expected_version_id=row["version_id"],
        object_type=row["object_type"],
        identity_key=row["identity_key"],
        display_name=row["display_name"],
        attributes=row["attributes"],
        valid_from=datetime.now(UTC),
        authority_state="REVOKED",
        evidence_class=row["evidence_class"],
    )
    proposal = ResourceProposal(
        title="Synthetic invalid atomic profile mutation",
        rationale="A dependency withdrawal must never be hidden inside a consuming proposal",
        access_entity=case.maker.scope.legal_entity_id,
        mutations=[item, altered],
    )
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError, match="cannot also mutate") as refused:
        resources.propose(case.maker, proposal)
    assert refused.value.status == 409
    assert scoped_versions(case.maker) == before


@DB
def test_publisher_withdrawal_blocks_pending_profile_review_and_current_run(profile_case):
    case = profile_case
    _, constraint, _ = approved_profiles(case)
    changed = case.profile.model_copy(update={"purpose": "Different synthetic observation purpose"})
    pending = profiles.propose_profile(case.maker, changed)
    lifecycle_change(case, "OBSERVED", availability="UNAVAILABLE")
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        approve(case.checker, pending.proposal.proposal_id)
    assert refused.value.status == 409
    assert resources.proposal_detail(case.maker, pending.proposal.proposal_id).decision is None
    with pytest.raises(WorkspaceError) as refused:
        profiles.resolve_run(
            case.reader,
            ValidationRunRequest(
                request_id=uuid4(),
                constraint_profile=resource_pin(constraint),
                data=case.graph,
            ),
        )
    assert refused.value.status == 409
    assert scoped_versions(case.maker) == before


@DB
def test_current_profile_uses_effective_publisher_despite_future_editing_head(profile_case):
    case = profile_case
    attributes = deepcopy(case.source_row["attributes"])
    attributes["definition"]["publisher"] = "Synthetic future publisher metadata"
    future = ResourceMutation(
        resource_id=case.source_id,
        expected_version_id=case.source_row["version_id"],
        object_type="ExternalOntologySource",
        identity_key=case.source_row["identity_key"],
        display_name="Future synthetic publisher",
        attributes=attributes,
        valid_from=datetime.now(UTC) + timedelta(days=30),
    )
    case.publish(future)
    proposed = profiles.propose_profile(case.maker, case.profile)
    approve(case.checker, proposed.proposal.proposal_id)
    row = resources.get_resource(case.reader, proposed.proposal.mutations[0].resource_id)[
        "resource"
    ]
    publishers = [
        d for d in dependency_rows(case.reader, row["version_id"]) if "PUBLISHER:" in d["relation"]
    ]
    assert publishers and all(
        str(p["target_version_id"]) == case.source_row["version_id"] for p in publishers
    )


@DB
def test_profile_revision_requires_new_content_identity_preserving_original(profile_case):
    case = profile_case
    original, _, _ = approved_profiles(case)
    changed = case.profile.model_copy(update={"purpose": "A newly reviewed synthetic purpose"})
    mutation = profiles.mutation(case.maker, "OntologyProfile", changed)
    forged = mutation.model_copy(
        update={
            "resource_id": UUID(original["resource_id"]),
            "identity_key": original["identity_key"],
            "expected_version_id": UUID(original["version_id"]),
        }
    )
    with pytest.raises(WorkspaceError) as refused:
        case.publish(forged)
    assert refused.value.status == 422
    proposed = profiles.propose_profile(case.maker, changed)
    approve(case.checker, proposed.proposal.proposal_id)
    assert str(proposed.proposal.mutations[0].resource_id) != original["resource_id"]
    assert (
        resources.get_resource(case.reader, UUID(original["resource_id"]))["resource"] == original
    )


@DB
def test_profile_replay_refuses_reserved_proposal_with_different_authority(profile_case):
    case = profile_case
    item = profiles.mutation(case.maker, "OntologyProfile", case.profile)
    proposal = ResourceProposal(
        proposal_id=canonical_id(
            case.maker.scope.tenant_id,
            "OntologyProfileProposal",
            case.maker.scope.legal_entity_id + ":" + item.identity_key,
        ),
        title="Synthetic different authority reservation",
        rationale="A same-content reservation must not disguise a different authority transition",
        access_entity=case.maker.scope.legal_entity_id,
        mutations=[item.model_copy(update={"authority_state": "REVOKED"})],
    )
    resources.propose(case.maker, proposal)
    with pytest.raises(WorkspaceError, match="reserved for other content"):
        profiles.propose_profile(case.maker, case.profile)
    assert resources.proposal_detail(case.maker, proposal.proposal_id).decision is None


@DB
def test_retained_report_proposal_requires_exact_execution_and_independent_review(
    published_validation_case,  # noqa: F811
):
    case = published_validation_case
    before = scoped_versions(case.maker)
    for changes in (
        {"outcome": "VIOLATES"},
        {"plan_sha256": "a" * 64},
        {"report": case.report.report.model_copy(update={"sha256": "b" * 64})},
    ):
        forged = profiles.mutation(
            case.maker, "OntologyValidationReport", case.report.model_copy(update=changes)
        )
        proposal = ResourceProposal(
            title="Synthetic forged validation observation",
            rationale="A caller cannot replace the exact retained validation outcome or bytes",
            access_entity=case.maker.scope.legal_entity_id,
            mutations=[forged],
        )
        with pytest.raises(WorkspaceError, match="differs from its retained execution") as refusal:
            resources.propose(case.maker, proposal)
        assert refusal.value.status == 409
    assert scoped_versions(case.maker) == before
    proposed = profiles.propose_report(case.maker, case.workflow_id)
    assert proposed.decision is None
    assert profiles.propose_report(case.maker, case.workflow_id) == proposed
    with pytest.raises(WorkspaceError) as refused:
        approve(case.maker, proposed.proposal.proposal_id)
    assert refused.value.status == 403
    assert scoped_versions(case.maker) == before
    approve(case.checker, proposed.proposal.proposal_id)
    report_item = next(
        i for i in proposed.proposal.mutations if i.object_type == "OntologyValidationReport"
    )
    report = resources.get_resource(case.reader, report_item.resource_id)["resource"]
    assert report["attributes"]["definition"] == case.report.model_dump(mode="json")
    assert report["evidence_class"] == "SOURCE_BOUND"
    assert report["attributes"]["definition"]["business_effect_authorized"] is False
    evidence_id = canonical_id(
        case.maker.scope.tenant_id, "SourceEvidence", case.report.report.sha256
    )
    assert report["attributes"]["evidence_id"] == str(evidence_id)
    request, plan, _ = runs.publication_context(case.checker, case.workflow_id)
    dependencies = {d["relation"]: d for d in dependency_rows(case.reader, report["version_id"])}
    for relation, pin in {
        "ONTOLOGY_PROFILE:PROFILE": plan.ontology_profile,
        "ONTOLOGY_PROFILE:CONSTRAINT": request.constraint_profile,
        "ONTOLOGY_PROFILE:DATA": plan.data.release,
        "ONTOLOGY_PROFILE:SHAPES": plan.shapes.release,
    }.items():
        assert str(dependencies[relation]["target_resource_id"]) == str(pin.resource_id)
        assert str(dependencies[relation]["target_version_id"]) == str(pin.version_id)
    assert dependencies["ONTOLOGY_VALIDATION_EVIDENCE"]["target_resource_id"] == evidence_id
    accepted = scoped_versions(case.maker)
    assert len(set(accepted) - set(before)) == 2
    assert profiles.propose_report(case.maker, case.workflow_id).decision == "APPROVED"
    assert scoped_versions(case.maker) == accepted


@DB
def test_shared_work_lists_hide_validation_metadata_without_ontology_permission(
    validation_case,  # noqa: F811
    monkeypatch,
):
    case = validation_case()
    identity = runs.retain(case.maker, case.request)
    limited = case.maker.model_copy(update={"permissions": ("read",)})
    allowed = case.maker.model_copy(update={"permissions": ("read", "ontology_read")})
    other_actor = allowed.model_copy(update={"actor_id": "another-validation-operator"})
    visible = workbench_listing(allowed, None, True)["items"]
    owned = next(item for item in visible if item["workflow_id"] == identity)
    assert owned["validation_request"] == case.request.model_dump(mode="json")
    assert identity not in json.dumps(workbench_listing(other_actor, None, True))
    restricted = workbench_listing(limited, None, True)
    assert identity not in {item["workflow_id"] for item in restricted["items"]}
    assert "ontology-validation:" not in json.dumps(restricted)
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "synthetic-restricted-worklist": limited.model_dump(mode="json"),
                "synthetic-ontology-worklist": allowed.model_dump(mode="json"),
                "synthetic-other-actor-worklist": other_actor.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    with TestClient(app) as client:
        for route in ("/v1/workspace/workflows", "/v1/workspace/workflows/workbench"):
            unauthorized = client.get(
                route,
                headers={
                    "Authorization": "Bearer synthetic-restricted-worklist",
                },
            )
            authorized = client.get(
                route,
                headers={
                    "Authorization": "Bearer synthetic-ontology-worklist",
                },
            )
            assert unauthorized.status_code == authorized.status_code == 200
            assert identity not in unauthorized.text
            assert "ontology-validation:" not in unauthorized.text
            assert identity in authorized.text
            foreign = client.get(
                route, headers={"Authorization": "Bearer synthetic-other-actor-worklist"},
            )
            assert foreign.status_code == 200
            assert identity not in foreign.text
    get_settings.cache_clear()
