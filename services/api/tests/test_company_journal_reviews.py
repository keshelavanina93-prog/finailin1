"""Company review visibility uses exact production intent, never a fabricated workflow."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from fastapi import HTTPException
from psycopg import OperationalError
from psycopg.errors import UndefinedTable
from test_journal_production import synthetic_candidate

from finai_api.domain.review import Principal
from finai_api.services import company_journal_reviews as service
from finai_api.services.journal_production import compile_row
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(monkeypatch):
    pair, source, targets, request = synthetic_candidate()
    row, proposal = compile_row(pair, source, targets, request, "synthetic")
    assert proposal is not None
    principal = Principal(
        actor_id="independent-reader",
        display_name="Authorized company reviewer",
        scope={
            "tenant_id": uuid4(),
            "legal_entity_id": "synthetic",
            "period": "2026-08",
            "currency": "GEL",
        },
        permissions=("ontology_read",),
    )
    payload = {
        "contract": "source-journal-production/1",
        "request": request.model_dump(mode="json"),
        "invocation_id": str(request.invocation_id),
        "rows": [{**row, "proposal": proposal.model_dump(mode="json")}],
        "submitted": [
            {
                "coordinate": row["coordinate"],
                "proposal_id": str(proposal.proposal_id),
                "decision": None,
            }
        ],
    }
    receipt = {
        "tenant_id": principal.scope.tenant_id,
        "request_id": request.request_id,
        "exact_scope": principal.scope.model_dump(mode="json"),
        "phase": "SUBMITTED",
        "recorded_at": datetime(2026, 8, 1, tzinfo=UTC),
        "actor_id": "original-maker",
        "request_hash": service.digest(payload["request"]),
        "payload": payload,
    }
    reseal(receipt)
    detail = SimpleNamespace(
        proposal=proposal,
        decision="APPROVED",
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
        submitted_by="original-maker",
    )
    receipts, calls = [receipt], []
    monkeypatch.setattr(service, "_receipts", lambda *_: receipts)

    def read(actor, identity):
        assert actor is principal
        calls.append(identity)
        return detail

    monkeypatch.setattr(service.resources, "proposal_detail", read)
    return SimpleNamespace(
        principal=principal,
        request=request,
        receipt=receipt,
        detail=detail,
        receipts=receipts,
        calls=calls,
        row=row,
    )


def reseal(receipt):
    payload = receipt["payload"]
    payload["receipt_hash"] = service.digest(
        {k: v for k, v in payload.items() if k != "receipt_hash"}
    )
    receipt["receipt_hash"] = payload["receipt_hash"]
    receipt["payload_bytes"] = len(service.json.dumps(payload).encode())


def observe(case):
    return service.observe(case.principal, case.request.company_id)


@pytest.mark.parametrize(
    "decision,state",
    [(None, "PENDING_REVIEW"), ("APPROVED", "PUBLISHED"), ("REJECTED", "REJECTED")],
)
def test_live_canonical_decision_and_another_reader_preserve_exact_review_identity(
    case, decision, state
):
    case.detail.decision = decision
    result = observe(case)
    assert result.state == "AVAILABLE" and not result.truncated
    (item,) = result.items
    assert (item.request_id, item.proposal_id, item.invocation_id, item.company_id) == (
        case.request.request_id,
        case.detail.proposal.proposal_id,
        case.request.invocation_id,
        case.request.company_id,
    )
    assert item.state == state and item.coordinate == "Base!S2"
    assert item.created_at == case.detail.created_at
    assert item.basis == "EXPLICIT_JOURNAL_PRODUCTION_REQUEST"
    text = result.model_dump_json()
    assert all(key not in text for key in ("workflow_id", "mutations", "exact_scope", "amount"))


def test_prepared_crash_window_reads_actual_proposal_and_missing_means_only_prepared(
    case, monkeypatch
):
    case.receipt["phase"] = "PREPARED"
    del case.receipt["payload"]["submitted"]
    reseal(case.receipt)
    assert observe(case).items[0].state == "PUBLISHED"

    def missing(*_):
        raise WorkspaceError(404, "not visible")

    monkeypatch.setattr(service.resources, "proposal_detail", missing)
    result = observe(case)
    assert result.items[0].state == "PREPARED"
    assert "not established" in result.items[0].reason


@pytest.mark.parametrize("status", [403, 404, 409, 503])
def test_submitted_but_unavailable_detail_never_becomes_prepared_or_empty(
    case, monkeypatch, status
):
    def refused(*_):
        raise WorkspaceError(status, "private source detail must not escape")

    monkeypatch.setattr(service.resources, "proposal_detail", refused)
    result = observe(case)
    assert result.state == "UNAVAILABLE" and result.items == []
    assert "private source" not in result.model_dump_json()


@pytest.mark.parametrize(
    "change",
    [
        "tenant",
        "scope",
        "company",
        "request_id",
        "invocation",
        "request_hash",
        "receipt_hash",
        "payload",
        "proposal_id",
        "submitted",
        "duplicate_row",
        "unselected",
        "access",
    ],
)
def test_tampered_or_foreign_association_refuses_before_proposal_read(case, change):
    receipt, payload = case.receipt, case.receipt["payload"]
    if change == "tenant":
        receipt["tenant_id"] = uuid4()
    elif change == "scope":
        receipt["exact_scope"]["period"] = "other-period"
    elif change == "company":
        payload["request"]["company_id"] = str(uuid4())
    elif change == "request_id":
        receipt["request_id"] = uuid4()
    elif change == "invocation":
        payload["invocation_id"] = str(uuid4())
    elif change == "request_hash":
        receipt["request_hash"] = "0" * 64
    elif change == "receipt_hash":
        receipt["receipt_hash"] = "0" * 64
    elif change == "payload":
        payload["request"]["rationale"] = "changed retained request"
    elif change == "proposal_id":
        payload["rows"][0]["proposal_id"] = str(uuid4())
    elif change == "submitted":
        payload["submitted"][0]["proposal_id"] = str(uuid4())
    elif change == "duplicate_row":
        payload["rows"].append(deepcopy(payload["rows"][0]))
    elif change == "unselected":
        payload["submitted"][0]["coordinate"] = "Base!S999"
    else:
        payload["rows"][0]["proposal"]["access_entity"] = "foreign"
    if change not in ("receipt_hash", "payload"):
        reseal(receipt)
    assert observe(case).state == "UNAVAILABLE"
    assert case.calls == []


@pytest.mark.parametrize("change", ["content", "decision"])
def test_canonical_proposal_substitution_and_unknown_decision_refuse(case, change):
    if change == "content":
        case.detail.proposal = case.detail.proposal.model_copy(
            update={"rationale": "Different intent"}
        )
    else:
        case.detail.decision = "UNREVIEWED_PUBLICATION"
    assert observe(case).state == "UNAVAILABLE"


def test_excluded_or_blocked_rows_without_proposal_are_not_review_tasks(case):
    payload = case.receipt["payload"]
    payload["rows"][0].pop("proposal")
    payload["submitted"] = []
    reseal(case.receipt)
    assert observe(case).items == [] and not case.calls


def test_bounds_limit_canonical_detail_reads_and_disclose_scan_truncation(case):
    original = deepcopy(case.receipt)
    case.receipts.clear()
    for _ in range(26):
        row = deepcopy(original)
        request_id = uuid4()
        row["request_id"] = request_id
        row["payload"]["request"]["request_id"] = str(request_id)
        proposal_id = str(uuid5(request_id, "Base!S2"))
        row["payload"]["rows"][0]["proposal_id"] = proposal_id
        row["payload"]["rows"][0]["proposal"]["proposal_id"] = proposal_id
        row["payload"]["submitted"][0]["proposal_id"] = proposal_id
        row["request_hash"] = service.digest(row["payload"]["request"])
        reseal(row)
        case.receipts.append(row)
    candidates, truncated = service._candidates(
        case.principal, case.request.company_id, case.receipts
    )
    assert truncated and len(candidates) == 25
    case.receipts[0]["payload_bytes"] = service.MAX_BYTES + 1
    assert observe(case).state == "UNAVAILABLE" and case.calls == []


@pytest.mark.parametrize("failure", [OperationalError, UndefinedTable])
def test_storage_failure_is_independent_unavailable_and_permissions_still_required(
    case, monkeypatch, failure,
):
    def failed(*_):
        raise failure("private database diagnostics")

    monkeypatch.setattr(service, "_receipts", failed)
    assert observe(case).state == "UNAVAILABLE"
    case.principal = case.principal.model_copy(update={"permissions": ()})
    with pytest.raises(HTTPException) as denied:
        observe(case)
    assert denied.value.status_code == 403


def test_query_uses_exact_scope_company_submitted_preference_and_server_byte_cap(case, monkeypatch):
    statements = []

    class Cursor:
        def execute(self, query, params=None):
            statements.append((query, params))
            return self

        def fetchall(self):
            return []

        @contextmanager
        def cursor(self, **_):
            yield self

    @contextmanager
    def connection(_):
        yield Cursor()

    monkeypatch.setattr(service.resources, "resource_connection", connection)
    # Fixture replaces the observer seam; exercise the actual query function directly.
    assert actual_receipts(case.principal, case.request.company_id) == []
    query, params = statements[-1]
    assert "tenant_id=%s AND exact_scope=%s" in query
    assert "payload->'request'->>'company_id'=%s" in query
    assert "(phase='SUBMITTED') DESC" in query and "LIMIT 26" in query
    assert "sum(payload_bytes) OVER ()<=%s" in query
    assert params[0] == case.principal.scope.tenant_id
    assert params[1].obj == case.principal.scope.model_dump(mode="json")
    assert params[2:] == (str(case.request.company_id), service.MAX_BYTES)


actual_receipts = service._receipts
