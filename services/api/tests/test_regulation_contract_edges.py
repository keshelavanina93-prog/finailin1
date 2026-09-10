"""Frozen, non-authentic fixtures exercise regulatory authority and runtime boundaries.

No publisher request, legal activation, accounting entry, or database mutation occurs.
Storage/Temporal adapters are replaced; parsing, identities, permissions, temporal
assessment, source comparison and application orchestration run as production code.
"""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy

from finai_api.api import regulation_routes as routes
from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.review import Principal
from finai_api.services import regulatory_impact as impact
from finai_api.services import regulatory_licence_context as licences
from finai_api.services import regulatory_monitors as monitors
from finai_api.services import regulatory_sources as sources
from finai_api.services.workspace import WorkspaceError

NOW = datetime(2026, 9, 8, tzinfo=UTC)
DOCUMENT = "doc_" + "a" * 64


@pytest.fixture
def operator():
    return Principal(
        actor_id="regulatory-fixture-operator",
        display_name="Local fixture operator",
        scope=ExactScope(
            tenant_id=UUID("da97d685-1816-4ad4-9cfe-afc72c8a7e54"),
            legal_entity_id="fixture-company",
            period="2026-09",
            currency="GEL",
        ),
        permissions=("read", "ingest", "ontology_read", "ontology_propose"),
    )


def html(text="Original &amp; retained", number="123", publication=0):
    return (
        f'<body class="page-document-view-{number}"><h1>Fixture act</h1>'
        "<table><tr><td>დოკუმენტის ნომერი</td><td>81</td></tr>"
        "<tr><td>Unknown metadata</td><td>ignored</td></tr></table>"
        f"<script>publication_id={publication}</script>"
        f'<div id="maindoc"><div>{text}</div><p>Second paragraph</p></div></body>'
    ).encode()


class Rows:
    """Small adapter double which exposes query arguments for scope assertions."""

    def __init__(self, rows=(), one=None):
        self.rows = list(rows)
        self.one = one
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def cursor(self, **_kwargs):
        return nullcontext(self)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


@pytest.mark.parametrize(
    "content,status,message",
    [
        (b"x" * 8_000_001, 413, "exceeds"),
        (b"\xff", 422, "UTF-8"),
        (b"<html>Sign in</html>", 422, "Recognized"),
        (html() + b'<div id="maindoc">duplicate</div>', 422, "Recognized"),
        (html().replace("დოკუმენტის ნომერი".encode(), b"Other"), 422, "metadata"),
    ],
    ids=["oversize", "invalid-encoding", "login-page", "duplicate-body", "missing-metadata"],
)
def test_parser_refuses_oversize_invalid_or_unregistered_capture(content, status, message):
    with pytest.raises(WorkspaceError, match=message) as error:
        sources.parse(content)
    assert error.value.status == status


def test_parser_retains_body_hash_and_unknown_completeness_without_publication():
    content = (
        html()
        .replace(b"<h1>Fixture act</h1>", b"")
        .replace(b"publication_id=0", b"no publication selector")
    )
    result = sources.parse(b"\xef\xbb\xbf" + content)
    assert result["title"] == "Original & retained"
    assert result["text"] == "Original & retained\nSecond paragraph"
    assert result["text_sha256"] == sha256(result["text"].encode()).hexdigest()
    assert result["publication"] is None
    assert result["completeness"] == "UNVERIFIED_COMPLETENESS"
    assert result["metadata"] == {"დოკუმენტის ნომერი": "81"}
    assert result["current_law_verified"] is False


@pytest.mark.parametrize("failure", [None, "http", "size", "identity", "publication"])
def test_capture_retains_only_exact_requested_bytes(monkeypatch, operator, failure):
    content = html(
        number="456" if failure == "identity" else "123",
        publication=1 if failure == "publication" else 0,
    )
    response = Mock()
    response.iter_bytes.return_value = [b"x" * 8_000_001] if failure == "size" else [content]
    if failure == "http":
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Fixture HTTP error",
            request=httpx.Request("GET", "https://matsne.gov.ge"),
            response=httpx.Response(503),
        )
    stream = Mock(return_value=nullcontext(response))
    retain = Mock(return_value={"document_id": DOCUMENT})
    monkeypatch.setattr(sources.httpx, "stream", stream)
    monkeypatch.setattr(sources.source_documents, "retain_document", retain)
    request = sources.Capture(document_number="123")
    if failure:
        with pytest.raises(WorkspaceError) as error:
            sources.capture(operator, request)
        assert error.value.status == {"http": 502, "size": 413}.get(failure, 409)
        retain.assert_not_called()
    else:
        result = sources.capture(operator, request)
        retain.assert_called_once_with(operator, "matsne-123-publication-0.html", content)
        assert result["observation"]["current_law_verified"] is False
    stream.assert_called_once_with(
        "GET",
        "https://matsne.gov.ge/ka/document/view/123?publication=0",
        timeout=45,
        follow_redirects=False,
    )


def test_capture_permission_refusal_happens_before_network(monkeypatch, operator):
    stream = Mock(side_effect=AssertionError("No publisher call permitted"))
    monkeypatch.setattr(sources.httpx, "stream", stream)
    with pytest.raises(HTTPException) as error:
        sources.capture(
            operator.model_copy(update={"permissions": ("read",)}),
            sources.Capture(document_number="123"),
        )
    assert error.value.status_code == 403
    stream.assert_not_called()


def test_source_inspect_uses_retained_document_bytes(monkeypatch, operator):
    content = html()
    metadata = {"source_sha256": sha256(content).hexdigest()}
    read = Mock(return_value=(metadata, content))
    monkeypatch.setattr(sources.source_documents, "document_bytes", read)
    actual, observed = sources.inspect(operator, DOCUMENT)
    read.assert_called_once_with(operator, DOCUMENT)
    assert actual == metadata
    assert observed["matsne_id"] == "123"


@pytest.mark.parametrize("mode", ["changed", "unchanged", "missing", "other_act", "hash"])
def test_publication_compare_refuses_unscoped_cross_act_or_changed_parser_content(
    monkeypatch, operator, mode
):
    before, after = uuid4(), uuid4()
    left, right = sources.parse(html()), sources.parse(html("Changed paragraph"))
    if mode == "unchanged":
        right = deepcopy(left)
    rows = [
        {
            "version_id": version,
            "attributes": {
                "act_id": "act" if i == 0 or mode != "other_act" else "other-act",
                "document_id": f"document-{i}",
                "observation": value,
            },
        }
        for i, (version, value) in enumerate([(before, left), (after, right)])
    ]
    database = Rows(rows[:1] if mode == "missing" else rows)
    monkeypatch.setattr(sources.resources, "resource_connection", lambda *_: nullcontext(database))
    parsed = [deepcopy(left), deepcopy(right)]
    if mode == "hash":
        parsed[1]["text_sha256"] = "f" * 64
    monkeypatch.setattr(sources, "inspect", lambda _p, doc: ({}, parsed[int(doc[-1])]))
    request = sources.Comparison(before_version=before, after_version=after)
    if mode in {"missing", "other_act", "hash"}:
        with pytest.raises(WorkspaceError) as error:
            sources.compare(operator, request)
        assert error.value.status == {"missing": 404, "other_act": 422, "hash": 409}[mode]
    else:
        result = sources.compare(operator, request)
        assert result["state"] == (
            "DOCUMENT_TEXT_UNCHANGED" if mode == "unchanged" else "DOCUMENT_TEXT_CHANGED"
        )
        assert bool(result["diff"]) == (mode == "changed")
        assert result["legal_change_verified"] is False
        assert result["accounting_effects_created"] is False
        assert result["before"]["version_id"] == before
        assert result["after"]["version_id"] == after
    assert database.calls[0][1] == (operator.scope.tenant_id, [before, after])


def publication_fixture(monkeypatch):
    observed = sources.parse(html())
    metadata = {"source_sha256": sha256(html()).hexdigest()}
    monkeypatch.setattr(sources, "inspect", lambda *_: (metadata, deepcopy(observed)))
    return metadata, observed


def test_publication_proposal_uses_shared_identity_and_preserves_review_boundary(
    monkeypatch, operator
):
    metadata, observed = publication_fixture(monkeypatch)
    missing = Mock(side_effect=WorkspaceError(404, "Not yet retained"))
    proposed = Mock(side_effect=lambda _p, proposal: proposal)
    monkeypatch.setattr(sources.resources, "get_resource", missing)
    monkeypatch.setattr(sources.resources, "propose", proposed)
    request = sources.Publication(document_id=DOCUMENT, rationale="Review frozen test capture")
    proposal = sources.propose(operator, request)
    assert proposal.access_entity == operator.scope.legal_entity_id
    evidence, act, observation = proposal.mutations
    assert evidence.resource_id == canonical_id(
        operator.scope.tenant_id, "SourceEvidence", metadata["source_sha256"]
    )
    assert act.resource_id == canonical_id(
        operator.scope.tenant_id, "RegulatoryAct", "GE:MATSNE:123"
    )
    assert observation.attributes["act_id"] == str(act.resource_id)
    assert observation.attributes["evidence_id"] == str(evidence.resource_id)
    assert "text" not in observation.attributes["observation"]
    assert observation.attributes["observation"]["text_sha256"] == observed["text_sha256"]
    assert all(item.evidence_class == "SOURCE_BOUND" for item in proposal.mutations)
    assert all(item.expected_version_id is None for item in proposal.mutations)

    versions = {item.resource_id: uuid4() for item in proposal.mutations}
    existing = {item.resource_id: item.attributes for item in proposal.mutations}
    monkeypatch.setattr(
        sources.resources,
        "get_resource",
        lambda _p, rid: {"resource": {"attributes": existing[rid], "version_id": versions[rid]}},
    )
    with pytest.raises(WorkspaceError, match="already retained") as error:
        sources.propose(operator, request)
    assert error.value.status == 409
    existing[act.resource_id] = {"reference": "previous capture"}
    successor = sources.propose(operator, request)
    assert len(successor.mutations) == 1
    assert successor.mutations[0].expected_version_id == versions[act.resource_id]

    def target(rid, *_):
        return {"attributes": existing[UUID(rid)]}

    existing[act.resource_id] = act.attributes
    sources.validate(operator, observation, target)
    existing[evidence.resource_id] = {"sha256": "f" * 64}
    with pytest.raises(WorkspaceError, match="retained original"):
        sources.validate(operator, observation, target)


def test_publication_proposal_preserves_nonmissing_storage_error(monkeypatch, operator):
    publication_fixture(monkeypatch)
    monkeypatch.setattr(
        sources.resources, "get_resource", Mock(side_effect=WorkspaceError(403, "Context denied"))
    )
    with pytest.raises(WorkspaceError, match="Context denied") as error:
        sources.propose(
            operator,
            sources.Publication(document_id=DOCUMENT, rationale="Review frozen test capture"),
        )
    assert error.value.status == 403


def monitor_request(**changes):
    return monitors.MonitorRequest(
        document_number="123",
        request_id=UUID("246b6fe4-5e06-4b16-8da4-9508fa6cfcdb"),
        name="Fixture official source",
        cadence_hours=24,
        rationale="Monitor exact publication without automatic activation",
        **changes,
    )


def test_monitor_identity_reuses_exact_actor_scope_and_rejects_changed_payload(
    monkeypatch, operator
):
    request = monitor_request()
    database = Rows(one=(request.model_dump(mode="json") | {"definition": {"old": "metadata"}},))
    monkeypatch.setattr(monitors.records, "scope_connection", lambda *_: nullcontext(database))
    scopes = []
    monkeypatch.setattr(monitors.records, "set_scope", lambda _c, p: scopes.append(p.scope))
    identity = monitors.retain(operator, request)
    assert monitors.retain(operator, request) == identity
    assert (
        monitors.retain(operator.model_copy(update={"actor_id": "another-operator"}), request)
        != identity
    )
    alternate_scope = operator.scope.model_copy(update={"period": "2026-08"})
    assert (
        monitors.retain(operator.model_copy(update={"scope": alternate_scope}), request) != identity
    )
    insert = database.calls[0][1]
    assert insert[0] == operator.scope.tenant_id
    assert insert[2].obj == operator.scope.model_dump(mode="json")
    assert insert[5].obj["definition"]["automatic_legal_activation"] is False
    assert insert[5].obj["definition"]["source_identity"] == "GE:MATSNE:123"
    database.one = (request.model_dump(mode="json") | {"cadence_hours": 12},)
    with pytest.raises(WorkspaceError, match="different retained configuration"):
        monitors.retain(operator, request)
    database.one = None
    with pytest.raises(WorkspaceError, match="different retained configuration"):
        monitors.retain(operator, request)
    assert scopes


def test_monitor_listing_and_read_keep_scoped_definition_boundary(monkeypatch, operator):
    record = {"definition": {"version": monitors.VERSION}, "request": {"publication": 0}}
    monkeypatch.setattr(monitors.records, "read", lambda *_: record)
    assert monitors.read(operator, "monitor") == record
    record["definition"]["version"] = "unrelated-workflow/1"
    with pytest.raises(WorkspaceError) as error:
        monitors.read(operator, "monitor")
    assert error.value.status == 404
    database = Rows([("monitor", {"publication": 0}, NOW)])
    monkeypatch.setattr(monitors.records, "scope_connection", lambda *_: nullcontext(database))
    monkeypatch.setattr(
        monitors.records, "set_scope", lambda _c, p: p.scope.model_dump(mode="json")
    )
    assert monitors.listing(operator) == [
        {"workflow_id": "monitor", "request": {"publication": 0}, "created_at": NOW.isoformat()}
    ]
    params = database.calls[0][1]
    assert params[0] == operator.scope.tenant_id
    assert params[1].obj == operator.scope.model_dump(mode="json")
    assert params[2] == monitors.VERSION


@pytest.mark.parametrize("previous_state", ["none", "same", "different"])
def test_monitor_success_records_observation_change_without_legal_activation(
    monkeypatch, operator, previous_state
):
    observation = sources.parse(html())
    signature = {
        key: observation[key] for key in ("text_sha256", "advertised_publications", "completeness")
    }
    previous = (
        []
        if previous_state == "none"
        else [
            {
                "event_id": "source-check:previous",
                "signature": signature
                | (
                    {"completeness": "OLDER_PUBLICATION_ONLY"}
                    if previous_state == "different"
                    else {}
                ),
            }
        ]
    )
    events = []
    monkeypatch.setattr(monitors.records, "current_principal", lambda *_: operator)
    monkeypatch.setattr(
        monitors,
        "read",
        lambda *_: {"events": previous, "request": {"document_number": "123", "publication": 0}},
    )
    monkeypatch.setattr(monitors.activity, "info", lambda: SimpleNamespace(attempt=2))
    monkeypatch.setattr(monitors.records, "event", lambda *args: events.append(args))
    monkeypatch.setattr(
        monitors.sources,
        "capture",
        lambda *_: {
            "observation": observation,
            "document": {"document_id": DOCUMENT},
            "source_url": "https://matsne.gov.ge/ka/document/view/123?publication=0",
        },
    )
    result = monitors.check(
        {"actor_id": operator.actor_id, "scope": {}, "workflow_id": "monitor", "check_id": "next"}
    )
    assert (
        result["state"]
        == {"none": "INITIAL_CAPTURE", "same": "UNCHANGED", "different": "SOURCE_CHANGED"}[
            previous_state
        ]
    )
    assert events[0][2] == "source-check:next:attempt:2:started"
    assert events[1][2] == "source-check:next"
    retained = events[1][3]
    assert retained["signature"] == signature
    assert retained["previous_check"] == (None if not previous else "source-check:previous")
    assert retained["legal_change_verified"] is False
    assert retained["accounting_effects"] is False


def test_licence_lookup_uses_time_and_exact_approved_version(monkeypatch, operator):
    company, licence_id, version = uuid4(), uuid4(), uuid4()
    relation = str(canonical_id(operator.scope.tenant_id, "LinkType", "HOLDS_LICENSE"))
    approved = SimpleNamespace(
        resource_id=licence_id,
        version_id=version,
        authority_state="APPROVED",
        evidence_class="SOURCE_BOUND",
    )
    rejected = SimpleNamespace(
        resource_id=uuid4(),
        version_id=uuid4(),
        authority_state="REVOKED",
        evidence_class="SOURCE_BOUND",
    )
    template = SimpleNamespace(
        resource_id=uuid4(),
        version_id=uuid4(),
        authority_state="APPROVED",
        evidence_class="REFERENCE_TEMPLATE",
    )

    def holder(**attrs):
        return SimpleNamespace(
            resource_id=uuid4(),
            version_id=uuid4(),
            evidence_class="SOURCE_BOUND",
            attributes={
                "relation_id": relation,
                "source_id": str(company),
                "evidence_id": str(uuid4()),
                **attrs,
            },
        )

    matching, old, unrelated = holder(), holder(), holder(source_id=str(uuid4()))
    pages = {"Licence": [approved, rejected, template], "Relationship": [matching, old, unrelated]}
    listing = Mock(side_effect=lambda _p, kind, *_args: pages[kind])
    monkeypatch.setattr(licences.resources, "list_resources", listing)
    monkeypatch.setattr(
        licences.resources,
        "version_references",
        lambda _p, vid: {
            "target_id": {
                "resource_id": str(licence_id),
                "version_id": str(version if vid == matching.version_id else uuid4()),
            }
        },
    )
    result, complete = licences.licence_bindings(operator, company, NOW, NOW + timedelta(days=1))
    assert complete is True
    assert [item["resource_id"] for item in result] == [str(matching.resource_id)]
    assert all(call.args[-2:] == (NOW, NOW + timedelta(days=1)) for call in listing.call_args_list)


@pytest.mark.parametrize("overflow", ["Licence", "Relationship"])
def test_licence_scan_capacity_never_claims_complete(monkeypatch, operator, overflow):
    row = SimpleNamespace(
        resource_id=uuid4(),
        version_id=uuid4(),
        authority_state="REVOKED",
        evidence_class="REFERENCE_TEMPLATE",
        attributes={},
    )
    calls = []

    def listing(_p, kind, _search, offset, *_time):
        calls.append((kind, offset))
        return [row] * 100 if kind == overflow else []

    monkeypatch.setattr(licences.resources, "list_resources", listing)
    assert licences.licence_bindings(operator, uuid4(), NOW, NOW) == ([], False)
    assert (overflow, 4900) in calls
    assert all(offset < 5000 for _, offset in calls)


def test_dependency_impact_retains_exact_rule_references_without_amount(monkeypatch, operator):
    metadata, observed = publication_fixture(monkeypatch)
    version, rule_version = uuid4(), uuid4()
    affected = [
        {"object_type": "Report", "version_id": str(uuid4())},
        {"object_type": "RegulatoryRule", "version_id": str(rule_version)},
    ]
    references = [{"relation": "FIELD:licence_id", "version_id": uuid4()}]
    database = Rows(references)
    connection = Mock(return_value=nullcontext(database))
    monkeypatch.setattr(impact.resources, "resource_connection", connection)
    monkeypatch.setattr(
        impact.resources,
        "_get",
        lambda *_: {"version_id": version, "display_name": "Frozen fixture act"},
    )
    dependency = Mock(return_value={"affected": affected})
    monkeypatch.setattr(impact, "current_impact", dependency)
    retain = Mock(side_effect=lambda _p, result, **_kwargs: result)
    monkeypatch.setattr(impact, "retain_run", retain)
    result = impact.assess(operator, impact.ImpactRequest(document_id=DOCUMENT))
    connection.assert_called_once_with(operator, repeatable_read=True)
    act_id = canonical_id(operator.scope.tenant_id, "RegulatoryAct", "GE:MATSNE:123")
    dependency.assert_called_once_with(database, operator, {str(act_id): str(version)})
    assert database.calls[0][1] == (operator.scope.tenant_id, rule_version)
    assert result["rule_contexts"] == [{"rule": affected[1], "references": references}]
    assert result["source"]["sha256"] == metadata["source_sha256"]
    assert result["source"]["completeness"] == observed["completeness"]
    assert result["financial_impact"]["state"] == "UNAVAILABLE"
    assert result["financial_impact"]["amount"] is None
    assert result["legal_change_verified"] is result["accounting_effects"] is False
    assert retain.call_args.kwargs == {"runtime": "regulatory-dependency-impact/1"}


@pytest.mark.parametrize("already_running", [False, True])
def test_monitor_start_persists_before_schedule_and_disallows_overlap(
    monkeypatch, operator, already_running
):
    calls = []
    monkeypatch.setattr(monitors, "retain", lambda *_: calls.append("retain") or "monitor")

    async def create(identity, schedule, **kwargs):
        calls.append("schedule")
        assert identity == "monitor"
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.spec.intervals[0].every == timedelta(hours=24)
        assert schedule.action.args[0]["actor_id"] == operator.actor_id
        assert schedule.action.args[0]["scope"] == operator.scope.model_dump(mode="json")
        assert kwargs == {"trigger_immediately": True}
        if already_running:
            raise ScheduleAlreadyRunningError()

    monkeypatch.setattr(
        routes, "client", AsyncMock(return_value=SimpleNamespace(create_schedule=create))
    )
    assert asyncio.run(routes.start_monitor(operator, monitor_request())) == {
        "workflow_id": "monitor"
    }
    assert calls == ["retain", "schedule"]


@pytest.mark.parametrize("command,applied", [("pause", False), ("resume", False), ("pause", True)])
def test_monitor_control_retains_intent_before_action_and_reuses_applied_marker(
    monkeypatch, operator, command, applied
):
    request = routes.MonitorControl(
        command=command, reason="Fixture operational control", idempotency_key=uuid4()
    )
    key = "control:" + str(request.idempotency_key)
    monkeypatch.setattr(
        monitors, "read", lambda *_: {"events": [{"event_id": key + ":applied"}] if applied else []}
    )
    calls = []
    monkeypatch.setattr(
        routes.records, "event", lambda _p, _i, event, _payload: calls.append(event)
    )
    handle = SimpleNamespace(
        pause=AsyncMock(side_effect=lambda **_: calls.append("pause")),
        unpause=AsyncMock(side_effect=lambda **_: calls.append("resume")),
    )
    runtime = AsyncMock(return_value=SimpleNamespace(get_schedule_handle=lambda _: handle))
    monkeypatch.setattr(routes, "client", runtime)
    result = asyncio.run(routes.control_monitor("monitor", operator, request))
    assert result["state"] == ("ALREADY_APPLIED" if applied else "APPLIED")
    assert calls == ([key] if applied else [key, command, key + ":applied"])
    if applied:
        runtime.assert_not_called()


def test_monitor_unobservable_runtime_preserves_last_source_evidence(monkeypatch, operator):
    successful = {
        "event_id": "source-check:old",
        "check_id": "old",
        "state": "INITIAL_CAPTURE",
        "signature": {"text_sha256": "a" * 64},
        "checked_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
    }
    monkeypatch.setattr(
        monitors,
        "read",
        lambda *_: {
            "events": [successful],
            "created_at": NOW.isoformat(),
            "request": {"cadence_hours": 24},
        },
    )
    monkeypatch.setattr(routes, "client", AsyncMock(side_effect=ConnectionError("Fixture outage")))
    result = asyncio.run(routes.read_monitor("monitor", operator))
    assert result["runtime"] == {"state": "UNOBSERVABLE", "next_checks": []}
    assert result["freshness"] == "OVERDUE"
    assert result["last_success"] == result["last_new_item"] == successful
    assert result["source_health"] == "INITIAL_CAPTURE"


def definition(**changes):
    return {
        "legal_status": "ENACTED",
        "source_version": "fixture-publication",
        "source_version_complete": True,
        "provision": "Fixture provision",
        "activity": "DISTRIBUTION",
        "effective_from": "2026-01-01",
        "obligation": "Fixture obligation",
        **changes,
    }


def test_rule_proposal_keeps_scope_of_resolved_company_and_source_review(monkeypatch, operator):
    request = routes.RuleProposal(
        name="Fixture rule",
        key="fixture-rule",
        act_id=uuid4(),
        legal_entity_id=uuid4(),
        licence_id=uuid4(),
        evidence_id=uuid4(),
        definition=definition(),
        rationale="Review fixture interpretation",
    )
    entity = {"object_type": "LegalEntity", "access_entity": "resolved-company"}
    monkeypatch.setattr(routes.resources, "get_resource", lambda *_: {"resource": entity})
    proposed = Mock(side_effect=lambda _p, value: value)
    monkeypatch.setattr(routes.resources, "propose", proposed)
    result = routes.propose_rule(operator, request)
    assert result.access_entity == "resolved-company"
    mutation = result.mutations[0]
    assert mutation.object_type == "RegulatoryRule"
    assert mutation.evidence_class == "SOURCE_BOUND"
    assert mutation.attributes["definition"]["effective_from"] == "2026-01-01"
    assert mutation.attributes["legal_entity_id"] == str(request.legal_entity_id)
    entity["object_type"] = "Industry"
    with pytest.raises(WorkspaceError, match="legal entity"):
        routes.propose_rule(operator, request)
    assert proposed.call_count == 1


@pytest.mark.parametrize(
    "state", ["bound", "missing", "incomplete", "future", "different_activity"]
)
def test_rule_assessment_distinguishes_temporal_interpretation_and_holder_authority(
    monkeypatch, operator, state
):
    company, company_version, licence_id, licence_version = uuid4(), uuid4(), uuid4(), uuid4()
    entity = {
        "object_type": "LegalEntity",
        "resource_id": company,
        "version_id": company_version,
        "display_name": "Fixture company",
    }
    refs = {
        "legal_entity_id": {"resource_id": str(company), "version_id": str(company_version)},
        "licence_id": {"resource_id": str(licence_id), "version_id": str(licence_version)},
    }
    matching = SimpleNamespace(
        version_id=uuid4(),
        attributes={
            "legal_entity_id": str(company),
            "definition": definition(effective_from="2027-01-01")
            if state == "future"
            else definition(),
        },
    )
    other = SimpleNamespace(attributes={"legal_entity_id": str(uuid4())})
    monkeypatch.setattr(routes, "_company_at", lambda *_: entity)
    listing = Mock(return_value=[matching, other])
    monkeypatch.setattr(routes.resources, "list_resources", listing)
    monkeypatch.setattr(routes.resources, "version_references", lambda *_: refs)
    holders = (
        []
        if state == "missing"
        else [
            {"references": {"source_id": refs["legal_entity_id"], "target_id": refs["licence_id"]}}
        ]
    )
    monkeypatch.setattr(routes, "licence_bindings", lambda *_: (holders, state != "incomplete"))
    known = NOW + timedelta(days=5)
    result = routes.rules(
        operator,
        company,
        "SUPPLY" if state == "different_activity" else "DISTRIBUTION",
        None,
        NOW,
        known,
        0,
    )
    listing.assert_called_once_with(operator, "RegulatoryRule", "", 0, known, known)
    assert len(result["rules"]) == 1
    assessed = result["rules"][0]["assessment"]
    assert assessed["effective_obligation"] == (state == "bound")
    expected = {
        "bound": [],
        "missing": ["LICENCE_BINDING_REQUIRED"],
        "incomplete": ["LICENCE_SCAN_INCOMPLETE"],
        "future": ["FUTURE_EFFECTIVE"],
        "different_activity": ["NOT_APPLICABLE"],
    }
    assert assessed["blocking_reasons"] == expected[state]
    assert result["accounting_effects_created"] is False
    assert result["company"]["resource_id"] == company


def test_rule_assessment_refuses_naive_time_and_noncompany(monkeypatch, operator):
    read = Mock(return_value={"object_type": "Industry"})
    monkeypatch.setattr(routes, "_company_at", read)
    with pytest.raises(WorkspaceError, match="timezone"):
        routes.rules(operator, uuid4(), at=datetime(2026, 9, 8), known_at=NOW)
    read.assert_not_called()
    with pytest.raises(WorkspaceError, match="legal entity"):
        routes.rules(operator, uuid4(), at=NOW, known_at=NOW)


@pytest.mark.parametrize("overflow", [False, True])
def test_retained_assessment_requires_complete_authorized_scan(monkeypatch, operator, overflow):
    seen = []

    def page(_p, _company, _activity, _count, at, known, offset):
        seen.append((at, known, offset))
        return {
            "rules": [{"fixture_index": offset}],
            "next_offset": offset + 100 if overflow or offset == 0 else None,
            "accounting_effects_created": False,
        }

    monkeypatch.setattr(routes, "rules", page)
    retain = Mock(side_effect=lambda _p, value, **_kwargs: value)
    monkeypatch.setattr(routes, "retain_run", retain)
    request = routes.AssessmentRequest(legal_entity_id=uuid4(), activity="DISTRIBUTION")
    if overflow:
        with pytest.raises(WorkspaceError, match="complete assessment capacity"):
            routes.retain_assessment(operator, request)
        retain.assert_not_called()
        assert seen[-1][-1] == 9900
    else:
        result = routes.retain_assessment(operator, request)
        assert result["coverage"] == "COMPLETE_AUTHORIZED_RULE_SCAN"
        assert result["rules"] == [{"fixture_index": 0}, {"fixture_index": 100}]
        assert result["next_offset"] is None
        assert result["no_rules_found"] is False
        assert len({(at, known) for at, known, _ in seen}) == 1


@pytest.mark.parametrize(
    "reader,contract",
    [
        (routes.read_impact, "regulatory-dependency-impact/1"),
        (routes.read_assessment, "regulatory-assessment/1"),
    ],
)
def test_retained_regulatory_result_refuses_other_runtime_contract(
    monkeypatch, operator, reader, contract
):
    result = {"contract": contract, "run_id": "retained-fixture"}
    monkeypatch.setattr(routes, "read_run", lambda *_: result)
    assert reader(operator, "retained-fixture") == result
    result["contract"] = "another-contract/1"
    with pytest.raises(WorkspaceError) as error:
        reader(operator, "retained-fixture")
    assert error.value.status == 404


def test_source_routes_preserve_source_identity_and_retained_comparison(monkeypatch, operator):
    metadata, observed = publication_fixture(monkeypatch)
    inspected = routes.inspect_source(operator, DOCUMENT)
    assert inspected["document"] == {"document_id": DOCUMENT, "sha256": metadata["source_sha256"]}
    assert inspected["source_url"] == "https://matsne.gov.ge/ka/document/view/123?publication=0"
    assert inspected["observation"] == observed
    listing = Mock(return_value=list(range(100)))
    monkeypatch.setattr(routes.resources, "list_resources", listing)
    assert routes.source_publications(operator, 100)["next_offset"] == 200
    listing.assert_called_once_with(operator, "SourceRegulatoryPublication", "", 100)
    listing.return_value = []
    assert routes.source_publications(operator, 200)["next_offset"] is None
    compare = {"contract": "regulatory-document-diff/1", "legal_change_verified": False}
    request = sources.Comparison(before_version=uuid4(), after_version=uuid4())
    monkeypatch.setattr(sources, "compare", Mock(return_value=compare))
    retain = Mock(side_effect=lambda _p, result, **_kw: result)
    monkeypatch.setattr(routes, "retain_run", retain)
    assert routes.compare_sources(operator, request) == compare
    retain.assert_called_once_with(operator, compare, runtime="regulatory-source-comparison/1")


def test_api_service_dispatch_keeps_principal_and_typed_request(monkeypatch, operator):
    cases = [
        (routes.capture_source, sources, "capture", sources.Capture(document_number="123")),
        (routes.source_impact, impact, "assess", impact.ImpactRequest(document_id=DOCUMENT)),
        (
            routes.publish_source,
            sources,
            "propose",
            sources.Publication(document_id=DOCUMENT, rationale="Review frozen source fixture"),
        ),
    ]
    for endpoint, module, name, request in cases:
        service = Mock(return_value={"fixture": name})
        monkeypatch.setattr(module, name, service)
        assert endpoint(operator, request) == {"fixture": name}
        service.assert_called_once_with(operator, request)
    listing = Mock(return_value=[{"workflow_id": "monitor"}])
    monkeypatch.setattr(monitors, "listing", listing)
    assert routes.list_monitors(operator) == [{"workflow_id": "monitor"}]
    listing.assert_called_once_with(operator)
