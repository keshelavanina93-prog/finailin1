"""Discovery proves retained subject eligibility without source hydration or execution."""
# ruff: noqa: F811 -- pytest fixtures imported from the adapter contract tests

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_semantic_analysis_counts import retained as counts_retained  # noqa: F401
from test_semantic_analysis_objects import retained  # noqa: F401

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services import retained_analyses as service
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def principal():
    return Principal(
        actor_id="reader",
        display_name="Reader",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="scope", period="2026-09", currency="GEL"
        ),
    )


@pytest.fixture(autouse=True)
def cursor_key(monkeypatch):
    monkeypatch.setattr(
        service, "get_settings", lambda: SimpleNamespace(access_tokens=SecretStr("test-cursor-key"))
    )


def prepare(monkeypatch, case):
    history, plan, resolver, company, *_ = case
    plan["implementation"] = {"implementation_id": "ontology.object-set-derived/v1"}
    resolver.read_session = lambda: nullcontext()
    resolver.source_cells = lambda *_: pytest.fail("Discovery must not hydrate source cells")
    monkeypatch.setattr(
        service.semantic_analysis,
        "project",
        lambda *_: pytest.fail("No full projection during discovery"),
    )
    monkeypatch.setattr(service.semantic_analysis, "load", lambda *_: (history, plan, resolver))
    monkeypatch.setattr(service, "_company", lambda *_: None)
    candidate = {
        "request_id": UUID(history["invocation_id"]),
        "recorded_at": datetime.fromisoformat(history["receipt"]["recorded_at"]),
        "implementation": "ontology.object-set-derived/v1",
        "payload_bytes": 2048,
    }
    monkeypatch.setattr(service, "_candidates", lambda *_: [candidate])
    return company, candidate


@pytest.mark.parametrize(
    "fixture_name,contract",
    [("retained", "semantic-analysis/2"), ("counts_retained", "semantic-analysis/1")],
)
def test_exact_shared_subject_without_hydration(
    monkeypatch, principal, request, fixture_name, contract
):
    case = request.getfixturevalue(fixture_name)
    company, candidate = prepare(monkeypatch, case)
    result = service.discover(principal, UUID(company["resource_id"]))
    assert result.returned_count == result.inspected_count == 1
    assert result.not_listed_count == 0 and result.next_cursor is None
    item = result.items[0]
    assert str(item.company.version_id) == company["version_id"]
    assert item.receipt_hash == case[0]["receipt_hash"]
    assert item.run_id == case[0]["output"]["run_id"]
    assert item.recorded_at == candidate["recorded_at"]
    assert item.projection_contract == contract
    assert result.current_use_authorized is result.business_effect_authorized is False


def test_foreign_subject_not_exposed(monkeypatch, principal, retained):
    _, candidate = prepare(monkeypatch, retained)
    foreign = uuid4()
    result = service.discover(principal, foreign)
    assert result.items == [] and result.not_listed_count == 1
    assert str(candidate["request_id"]) not in result.model_dump_json()
    assert retained[3]["display_name"] not in result.model_dump_json()


def test_empty_scanned_page_continues_same_cutoff(monkeypatch, principal, retained):
    company, candidate = prepare(monkeypatch, retained)
    candidates = [
        {**candidate, "request_id": uuid4(), "implementation": "unsupported"} for _ in range(6)
    ]
    calls = []

    def page(_p, cutoff, offset, _boundary):
        calls.append((cutoff, offset))
        return candidates if offset == 0 else []

    monkeypatch.setattr(service, "_candidates", page)
    first = service.discover(principal, UUID(company["resource_id"]))
    assert first.items == [] and first.inspected_count == first.not_listed_count == 5
    assert first.next_cursor
    second = service.discover(principal, UUID(company["resource_id"]), first.next_cursor)
    assert second.recorded_before == first.recorded_before
    assert calls[1] == (first.recorded_before, 5)
    assert second.coverage == "BOUNDED_RETAINED_INVOCATION_PAGE"
    assert all(str(item["request_id"]) not in first.next_cursor for item in candidates)


@pytest.mark.parametrize(
    "change", ["company", "scope", "actor", "permissions", "signature", "future"]
)
def test_cursor_is_bound_to_exact_access_and_snapshot(principal, change):
    company, now = uuid4(), datetime.now(UTC)
    cutoff = now + timedelta(seconds=1) if change == "future" else now - timedelta(days=1)
    cursor = service._cursor(principal, company, cutoff, 5, "a" * 64)
    if change == "company":
        company = uuid4()
    elif change == "scope":
        principal = principal.model_copy(
            update={"scope": principal.scope.model_copy(update={"period": "2026-08"})}
        )
    elif change == "actor":
        principal = principal.model_copy(update={"actor_id": "another"})
    elif change == "permissions":
        principal = principal.model_copy(
            update={"permissions": ("ontology_read", "ontology_admin")}
        )
    elif change == "signature":
        cursor = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    with pytest.raises(WorkspaceError) as failure:
        service._position(principal, company, cursor, now)
    assert failure.value.status == 422


def test_oversize_skipped_before_load_and_uninspected_budget_not_lost(
    monkeypatch, principal, retained
):
    company, candidate = prepare(monkeypatch, retained)
    candidates = [
        {**candidate, "request_id": uuid4(), "payload_bytes": size}
        for size in [
            service.MAX_RESULT_BYTES + 1,
            service.MAX_RESULT_BYTES,
            service.MAX_RESULT_BYTES,
            1,
        ]
    ]
    monkeypatch.setattr(service, "_candidates", lambda *_: candidates)
    loaded = []

    def unavailable(_p, _c, item):
        loaded.append(item["request_id"])
        raise WorkspaceError(404, "private candidate name")

    monkeypatch.setattr(service, "_reference", unavailable)
    result = service.discover(principal, UUID(company["resource_id"]))
    assert result.inspected_count == 3 and result.not_listed_count == 3
    assert loaded == [candidates[1]["request_id"], candidates[2]["request_id"]]
    assert (
        service._position(
            principal, UUID(company["resource_id"]), result.next_cursor, datetime.now(UTC)
        )[1]
        == 3
    )
    assert "private" not in result.model_dump_json()


def test_corrupt_receipt_or_time_never_exposed(monkeypatch, principal, retained):
    company, candidate = prepare(monkeypatch, retained)
    candidate["recorded_at"] += timedelta(microseconds=1)
    assert service.discover(principal, UUID(company["resource_id"])).items == []
    monkeypatch.setattr(
        service.semantic_analysis,
        "load",
        lambda *_: (_ for _ in ()).throw(WorkspaceError(409, "foreign-proof-id")),
    )
    result = service.discover(principal, UUID(company["resource_id"]))
    assert result.not_listed_count == 1 and "foreign-proof-id" not in result.model_dump_json()


def test_company_gate_refuses_non_company_or_template(monkeypatch, principal):
    company = uuid4()
    monkeypatch.setattr(service.resources, "resource_connection", lambda *_: nullcontext(object()))
    for kind, authority, evidence in [
        ("EnterpriseGroup", "APPROVED", "SOURCE_BOUND"),
        ("LegalEntity", "APPROVED", "REFERENCE_TEMPLATE"),
    ]:
        monkeypatch.setattr(
            service.resources,
            "_get",
            lambda *_, kind=kind, authority=authority, evidence=evidence: dict(
                resource_id=company,
                object_type=kind,
                authority_state=authority,
                evidence_class=evidence,
            ),
        )
        with pytest.raises(WorkspaceError) as failure:
            service._company(principal, company)
        assert failure.value.status == 404
    monkeypatch.setattr(
        service.resources,
        "_get",
        lambda *_: dict(
            resource_id=company,
            object_type="LegalEntity",
            authority_state="REVOKED",
            evidence_class="SOURCE_BOUND",
        ),
    )
    service._company(principal, company)  # Historical discovery grants no current-use authority.


def test_mixed_company_revisions_are_not_eligible(monkeypatch, principal, retained):
    company, _ = prepare(monkeypatch, retained)
    resolver = retained[2]
    original_field = resolver.field
    counter = [0]

    def field(source, name):
        result = original_field(source, name)
        if result["object_type"] == "LegalEntity":
            counter[0] += 1
            if counter[0] > 1:
                return {**result, "version_id": str(uuid4())}
        return result

    resolver.field = field
    result = service.discover(principal, UUID(company["resource_id"]))
    assert result.items == [] and result.not_listed_count == 1


def test_deadline_refuses_whole_page_without_advancing_cursor(monkeypatch, principal, retained):
    company, _ = prepare(monkeypatch, retained)

    def expired(*_):
        raise service.ReadBudgetExceeded("Read budget exceeded")

    monkeypatch.setattr(service, "_reference", expired)
    with pytest.raises(WorkspaceError) as failure:
        service.discover(principal, UUID(company["resource_id"]))
    assert failure.value.status == 503


@pytest.mark.parametrize("failure", [service.ReadBudgetExceeded, service.QueryCanceled])
def test_completed_prefix_continues_before_interrupted_candidate(
    monkeypatch, principal, retained, failure
):
    company, candidate = prepare(monkeypatch, retained)
    next_candidate = {**candidate, "request_id": uuid4()}
    monkeypatch.setattr(service, "_candidates", lambda *_: [candidate, next_candidate])
    reference = service._reference

    def partial(p, c, item):
        if item is next_candidate:
            raise failure("private candidate query must not leak")
        return reference(p, c, item)

    monkeypatch.setattr(service, "_reference", partial)
    first = service.discover(principal, UUID(company["resource_id"]))
    assert first.inspected_count == first.returned_count == 1
    assert first.not_listed_count == 0
    assert first.items[0].invocation_id == candidate["request_id"]
    position = service._position(
        principal, UUID(company["resource_id"]), first.next_cursor, datetime.now(UTC)
    )
    assert position == (first.recorded_before, 1, service._boundary(candidate))
    assert "private" not in first.model_dump_json()


def test_other_storage_failure_does_not_masquerade_as_partial_page(
    monkeypatch, principal, retained
):
    company, candidate = prepare(monkeypatch, retained)
    monkeypatch.setattr(service, "_candidates", lambda *_: [candidate, candidate])
    reference, calls = service._reference, []

    def unavailable(p, c, item):
        if calls:
            raise WorkspaceError(503, "Storage unavailable")
        calls.append(item)
        return reference(p, c, item)

    monkeypatch.setattr(service, "_reference", unavailable)
    with pytest.raises(WorkspaceError) as result:
        service.discover(principal, UUID(company["resource_id"]))
    assert result.value.status == 503


def test_late_commit_shifting_boundary_refuses_before_next_page(monkeypatch, principal):
    cutoff = datetime.now(UTC)
    prior = {"request_id": uuid4(), "recorded_at": cutoff - timedelta(seconds=5)}
    next_row = {"request_id": uuid4(), "recorded_at": cutoff - timedelta(seconds=6)}
    rows, calls = [prior, next_row], []

    class Cursor:
        def execute(self, query, args):
            calls.append(args)
            return self

        def fetchall(self):
            return rows

    monkeypatch.setattr(service.function_invocations, "_database", lambda *_: nullcontext(Cursor()))
    assert service._candidates(principal, cutoff, 5, service._boundary(prior)) == [next_row]
    assert calls[0][-2:] == (7, 4)
    rows[0] = {"request_id": uuid4(), "recorded_at": cutoff - timedelta(seconds=4)}
    with pytest.raises(WorkspaceError) as refusal:
        service._candidates(principal, cutoff, 5, service._boundary(prior))
    assert refusal.value.status == 409
    assert str(rows[0]["request_id"]) not in refusal.value.detail


def test_candidates_query_binds_exact_scope_and_byte_size(monkeypatch, principal):
    calls = []

    class Cursor:
        def execute(self, query, args):
            calls.append((query, args))
            return self

        def fetchall(self):
            return []

    monkeypatch.setattr(service.function_invocations, "_database", lambda *_: nullcontext(Cursor()))
    cutoff = datetime.now(UTC)
    assert service._candidates(principal, cutoff, 0, None) == []
    query, args = calls[0]
    assert "octet_length(f.payload::text)" in query and "pg_column_size" not in query
    assert all(f"{alias}.exact_scope=%s" in query for alias in ("i", "r", "f"))
    assert "r.recorded_at<=%s" in query and "ORDER BY r.recorded_at DESC,i.request_id DESC" in query
    assert args[-3:] == (cutoff, 6, 0)


def test_api_no_credentials_and_company_refusal(monkeypatch, principal):
    from finai_api import security
    from finai_api.api import retained_analysis_routes

    monkeypatch.setattr(
        security, "get_settings", lambda: SimpleNamespace(access_tokens=SecretStr('{"test": {}}'))
    )
    client = TestClient(app)
    assert client.get(f"/v1/ontology/retained-analyses?company_id={uuid4()}").status_code == 401
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:

        def refuse(*_):
            raise WorkspaceError(404, "Company unavailable")

        monkeypatch.setattr(retained_analysis_routes, "discover", refuse)
        response = client.get(f"/v1/ontology/retained-analyses?company_id={uuid4()}")
        assert response.status_code == 404 and "items" not in response.json()
    finally:
        app.dependency_overrides.clear()
