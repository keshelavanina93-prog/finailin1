from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.ingest import CanonicalReference, IngestRequest
from finai_api.domain.review import Principal, approval_blockers, workspace_object
from finai_api.services import ingest_binding as binding
from finai_api.services.ingestion import compile_source
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    principal = Principal(
        actor_id="operator",
        display_name="Operator",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="company-a", period="2026-08", currency="GEL"
        ),
    )
    nodes: dict[str, Any] = {}
    for key in ("context", "legal_entity_id", "ledger_id", "period_id", "currency_id", "chart_id"):
        nodes[key] = {"resource_id": uuid4(), "version_id": uuid4(), "attributes": {}}
    attrs = {key: str(nodes[key]["resource_id"]) for key in nodes if key != "context"}
    scope_key = canonical_sha256(principal.scope)
    nodes["context"].update(
        identity_key="context:" + scope_key, attributes={**attrs, "source_scope_key": scope_key}
    )
    nodes["ledger_id"]["attributes"] = {**attrs, "calendar_id": "calendar-a"}
    nodes["chart_id"]["attributes"] = {"legal_entity_id": attrs["legal_entity_id"]}
    nodes["currency_id"]["attributes"] = {"code": "GEL"}
    nodes["period_id"]["attributes"] = {
        "starts_on": "2026-08-01",
        "ends_on": "2026-08-31",
        "calendar_id": "calendar-a",
    }
    accounts = {
        code: {
            "resource_id": uuid4(),
            "version_id": uuid4(),
            "attributes": {"chart_id": attrs["chart_id"], "account_code": code},
        }
        for code in ("001", "002")
    }
    versions = {node["version_id"]: node for node in [*nodes.values(), *accounts.values()]}

    class Connection:
        def execute(self, *args: Any) -> "Connection":
            return self

        def fetchone(self) -> None:
            return None

    @contextmanager
    def connection(_: Principal) -> Any:
        yield Connection()

    monkeypatch.setattr(binding, "resource_connection", connection)
    monkeypatch.setattr(
        binding, "_accepted_version", lambda conn, user, version, kind: versions[version]
    )
    monkeypatch.setattr(
        binding, "_dependency", lambda conn, user, source, field, kind: nodes[field]
    )
    request = IngestRequest(
        scope=principal.scope,
        filename="tb.csv",
        csv_text="account_code,debit,credit\n001,1.25,0\n002,0,1.25\n",
        context_version_id=nodes["context"]["version_id"],
        account_version_ids={code: node["version_id"] for code, node in accounts.items()},
    )
    return {"principal": principal, "nodes": nodes, "accounts": accounts, "request": request}


def test_bound_references_survive_approval_and_serialization(registry: dict[str, Any]) -> None:
    request = registry["request"]
    receipt = binding.bind_receipt(registry["principal"], request, compile_source(request))
    assert receipt.binding_state == "CANONICAL_BOUND"
    assert receipt == binding.bind_receipt(registry["principal"], request, compile_source(request))
    for index, candidate in enumerate(receipt.candidates):
        code = candidate.values["account_code"]
        assert candidate.canonical_references["account_id"] == CanonicalReference(
            resource_id=registry["accounts"][code]["resource_id"],
            version_id=registry["accounts"][code]["version_id"],
        )
        obj = workspace_object(receipt.receipt_id, index, candidate)
        assert obj.canonical_references == candidate.canonical_references
        assert obj.object_id != str(obj.canonical_references["account_id"].resource_id)
        assert obj.model_dump(mode="json")["canonical_references"]["account_id"]["version_id"]
    reviewer = registry["principal"].model_copy(
        update={"actor_id": "reviewer", "permissions": ("review",)}
    )
    assert not approval_blockers(receipt, "operator", reviewer)


@pytest.mark.parametrize("mapping", ["missing", "extra", "duplicate", "wrong_code", "wrong_chart"])
def test_mappings_fail_closed(registry: dict[str, Any], mapping: str) -> None:
    request = registry["request"]
    ids = dict(request.account_version_ids)
    if mapping == "missing":
        ids.pop("001")
    elif mapping == "extra":
        ids["003"] = uuid4()
    elif mapping == "duplicate":
        ids["002"] = ids["001"]
    elif mapping == "wrong_code":
        ids["001"], ids["002"] = ids["002"], ids["001"]
    else:
        registry["accounts"]["001"]["attributes"]["chart_id"] = str(uuid4())
    request = request.model_copy(update={"account_version_ids": ids})
    with pytest.raises(WorkspaceError):
        binding.bind_receipt(registry["principal"], request, compile_source(request))


@pytest.mark.parametrize(
    "invalid", ["scope", "company", "chart_company", "currency", "calendar", "period"]
)
def test_context_accounting_invariants(registry: dict[str, Any], invalid: str) -> None:
    nodes = registry["nodes"]
    if invalid == "scope":
        nodes["context"]["attributes"]["source_scope_key"] = "other"
    elif invalid == "company":
        nodes["ledger_id"]["attributes"]["legal_entity_id"] = str(uuid4())
    elif invalid == "chart_company":
        nodes["chart_id"]["attributes"]["legal_entity_id"] = str(uuid4())
    elif invalid == "currency":
        nodes["currency_id"]["attributes"]["code"] = "USD"
    elif invalid == "calendar":
        nodes["period_id"]["attributes"]["calendar_id"] = "other"
    else:
        nodes["period_id"]["attributes"]["ends_on"] = "2026-08-30"
    with pytest.raises(WorkspaceError):
        request = registry["request"]
        binding.bind_receipt(registry["principal"], request, compile_source(request))


def test_version_choices_change_receipt_identity(registry: dict[str, Any]) -> None:
    request = registry["request"]
    changed = request.model_copy(
        update={"account_version_ids": {**request.account_version_ids, "001": uuid4()}}
    )
    assert compile_source(request).receipt_id != compile_source(changed).receipt_id


def test_source_only_is_explicit_and_cannot_attach_account_maps(registry: dict[str, Any]) -> None:
    request = registry["request"].model_copy(update={"context_version_id": None})
    with pytest.raises(WorkspaceError):
        binding.bind_receipt(registry["principal"], request, compile_source(request))
    request = request.model_copy(update={"account_version_ids": {}})
    receipt = binding.bind_receipt(registry["principal"], request, compile_source(request))
    assert receipt.binding_state == "SOURCE_ONLY"
    assert not receipt.canonical_references


def test_legacy_bound_receipt_requires_account_rebinding(registry: dict[str, Any]) -> None:
    request = registry["request"]
    receipt = compile_source(request).model_copy(
        update={"context_version_id": request.context_version_id}
    )
    reviewer = registry["principal"].model_copy(
        update={"actor_id": "reviewer", "permissions": ("review",)}
    )
    assert any(
        "bindings" in blocker for blocker in approval_blockers(receipt, "operator", reviewer)
    )
