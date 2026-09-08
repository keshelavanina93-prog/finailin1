"""Financial discovery isolation and reference-only historical result contracts."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import company_financial_results as service
from finai_api.services.workspace import WorkspaceError


def fixture():
    company = {
        "resource_id": str(uuid4()),
        "version_id": str(uuid4()),
        "content_hash": "a" * 64,
        "object_type": "LegalEntity",
        "attributes": {},
    }
    principal = Principal(
        actor_id="reader",
        display_name="Reader",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id=company["resource_id"],
            period="2025-01",
            currency="GEL",
        ),
    )
    manifest = service.function_execution.manifest(service.FINANCIAL_IMPLEMENTATIONS[1])
    definition = {
        k: manifest[k]
        for k in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    definition["company"] = {k: company[k] for k in ("resource_id", "version_id")}
    function = {
        "reference": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
        "content_hash": "b" * 64,
        "display_name": "Reviewed movements",
        "attributes": {"definition": definition},
    }
    context = {"company": company, "accounting_sources": []}
    identity = uuid4()
    scope = principal.scope.model_dump(mode="json")
    plan = {
        "exact_scope": scope,
        "request": {
            "request_id": str(identity),
            "valid_at": "2025-01-31T00:00:00Z",
            "known_at": "2026-09-08T00:00:00Z",
        },
        "implementation": definition,
        "function": {**function["reference"], "content_hash": "b" * 64},
        "accepted_movements": {
            "company_id": company["resource_id"],
            "journal_observed_at": "2026-09-08T01:00:00Z",
            "source_invocation_id": str(uuid4()),
            "contributors": ["not catalog payload"],
        },
    }
    plan["plan_hash"] = service.function_execution._digest(plan)
    payload = {
        "exact_scope": scope,
        "plan_hash": plan["plan_hash"],
        "function": plan["function"],
        "request_id": str(identity),
        "status": "SUCCEEDED",
        "run_id": "fcr_" + "d" * 64,
    }
    retained = {
        "request_id": identity,
        "exact_scope": scope,
        "plan": plan,
        "plan_hash": plan["plan_hash"],
        "payload": payload,
        "proof_hash": service.function_invocations._digest(payload),
        "recorded_at": datetime.now(UTC),
    }
    return principal, context, function, retained


def test_reviewed_company_function_is_discovered_without_source_profile():
    _, context, function, _ = fixture()
    value = service.capability(function, [context["company"]], context)
    assert value["kind"] == "ACCEPTED_JOURNAL_MOVEMENTS"
    assert value["state"] == "DISCOVERED"
    assert value["source_scope"] is None
    assert not value["current_use_authorized"] and not value["business_effect_authorized"]


@pytest.mark.parametrize(
    "change", ["other_company", "generic", "missing_pin", "changed_pin", "code"]
)
def test_no_inferred_financial_capability(change):
    _, context, function, _ = fixture()
    deps = [deepcopy(context["company"])]
    if change == "other_company":
        function["attributes"]["definition"]["company"]["resource_id"] = str(uuid4())
    elif change == "generic":
        function["attributes"]["definition"]["implementation_id"] = (
            "source.retained-xls-worksheet/v1"
        )
    elif change == "missing_pin":
        deps = []
    elif change == "changed_pin":
        deps[0]["version_id"] = str(uuid4())
    else:
        function["attributes"]["definition"]["code_sha256"] = "f" * 64
    if change in ("other_company", "generic"):
        assert service.capability(function, deps, context) is None
    else:
        with pytest.raises(WorkspaceError):
            service.capability(function, deps, context)


def test_retained_result_keeps_own_clocks_and_does_not_need_current_catalog():
    principal, context, _, row = fixture()
    before = deepcopy(row)
    value = service.retained_item(row, principal, UUID(context["company"]["resource_id"]))
    assert value["valid_at"] == "2025-01-31T00:00:00Z"
    assert value["source"]["journal_observed_at"] == "2026-09-08T01:00:00Z"
    assert value["reopen"] == "FUNCTION_HISTORY"
    assert "contributors" not in value["source"]
    assert not value["current_use_authorized"]
    assert row == before


@pytest.mark.parametrize("change", ["scope", "plan", "receipt", "malformed", "foreign_source"])
def test_retained_discovery_refuses_tamper_and_cross_company(change):
    principal, context, _, row = fixture()
    company = UUID(context["company"]["resource_id"])
    if change == "scope":
        row["exact_scope"] = {**row["exact_scope"], "tenant_id": str(uuid4())}
    elif change == "plan":
        row["plan"]["request"]["valid_at"] = "2030-01-01T00:00:00Z"
    elif change == "receipt":
        row["payload"]["run_id"] = "fcr_" + "e" * 64
    elif change == "malformed":
        del row["proof_hash"]
    else:
        assert service.retained_item(row, principal, uuid4()) is None
        return
    with pytest.raises(WorkspaceError):
        service.retained_item(row, principal, company)


def test_discovery_scope_precedes_catalog_and_storage(monkeypatch):
    principal, _, _, _ = fixture()

    def unexpected(*args, **kwargs):
        raise AssertionError("Out-of-company discovery must not read")

    monkeypatch.setattr(service.company_context, "resolve", unexpected)
    with pytest.raises(WorkspaceError) as error:
        service.discover(principal, uuid4())
    assert error.value.status == 404


def test_discovery_keeps_historical_result_without_current_function(monkeypatch):
    principal, context, _, row = fixture()
    company = UUID(context["company"]["resource_id"])

    def resolve(*args):
        return {
            "context": context,
            "valid_at": "2026-09-08T01:00:00Z",
            "known_at": "2026-09-08T01:00:00Z",
        }

    monkeypatch.setattr(service.company_context, "resolve", resolve)
    monkeypatch.setattr(
        service.function_catalog, "discover", lambda *args: {"items": [], "next_cursor": None}
    )

    class Cursor:
        def execute(self, sql, args):
            assert "i.exact_scope=%s::jsonb" in sql and "r.exact_scope=i.exact_scope" in sql
            assert args[0] == principal.scope.tenant_id
            return SimpleNamespace(fetchall=lambda: [row])

    @contextmanager
    def database(p):
        assert p == principal
        yield Cursor()

    monkeypatch.setattr(service.function_invocations, "_database", database)
    result = service.discover(principal, company)
    assert result["capabilities"] == []
    assert len(result["results"]) == 1
    assert result["results"][0]["valid_at"] != result["valid_at"]
    assert result["next_invocation_cursor"] is None


def posted_fixture():
    from test_source_accounting_context import context as accounting_context

    _principal, company_context, item, _ = fixture()
    mutation, targets, ids = accounting_context()
    company = company_context["company"]
    company["resource_id"] = ids["company"]
    binding_id, evidence_id, dimension_id = map(str, (uuid4(), uuid4(), uuid4()))
    config = mutation.attributes
    config.update(
        dimension_mapping_id=dimension_id,
        amount_field="source_amount",
        amount_semantics="DEBIT_CREDIT",
        vat_treatment="AS_POSTED",
        supplementary_amount_field="annotated_amount",
        supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
    )
    scope = targets[ids["scope"]]
    scope["object_type"] = "SourceAccountingScope"
    scope["attributes"].update(
        document_id="doc_" + "c" * 64,
        worksheet="Base",
        evidence_id=evidence_id,
        source_profile="seg_expense_base",
    )
    account_id = str(uuid4())
    targets[account_id] = {
        "object_type": "LocalAccount",
        "attributes": {"chart_id": ids["chart"], "account_code": "1000"},
    }
    targets[binding_id] = {"object_type": "SourceAccountingBinding", "attributes": config}
    targets[evidence_id] = {"object_type": "SourceEvidence", "attributes": {"sha256": "d" * 64}}
    targets[dimension_id] = {
        "object_type": "MappingVersion",
        "attributes": {
            "definition": {
                "kind": "PRESERVE_SOURCE_DIMENSION_COORDINATES",
                "company_id": ids["company"],
                "aggregation_dimensions": [],
            }
        },
    }
    for identity, row in targets.items():
        row.setdefault("evidence_class", "USER_ASSERTED")
        row.update(
            resource_id=identity,
            version_id=str(uuid4()),
            content_hash="e" * 64,
            authority_state="APPROVED",
        )
    targets[ids["mapping"]]["attributes"]["definition"] = {
        "kind": "EXACT_SOURCE_ACCOUNT_IDENTITIES",
        "version": 1,
        "company_id": ids["company"],
        "chart_id": ids["chart"],
        "accounts": {
            "1000": {key: targets[account_id][key] for key in ("resource_id", "version_id")}
        },
    }
    manifest = service.function_execution.manifest(service.FINANCIAL_IMPLEMENTATIONS[0])
    definition = {
        key: manifest[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    definition.update(
        document_id="doc_" + "c" * 64, source_sha256="d" * 64, sheet="Base", max_source_rows=100
    )
    item["attributes"] = {
        "definition": definition,
        "accounting_binding_id": binding_id,
        "source_scope_id": ids["scope"],
        "evidence_id": evidence_id,
        "minimum_authority_state": "OBSERVED",
    }
    binding = targets[binding_id]
    company_context["accounting_sources"] = [
        {
            "scope": scope,
            "bindings": [binding],
            "binding_eligibility": {
                binding["version_id"]: {
                    "eligible_for_accounting": True,
                    "state": "ELIGIBLE_FOR_GUARDED_USE",
                    "binding_version_id": binding["version_id"],
                }
            },
        }
    ]
    return item, targets, company_context


@pytest.mark.parametrize("eligible", [True, False])
def test_source_capability_consumes_binding_eligibility_without_granting_authority(eligible):
    item, targets, context = posted_fixture()
    status = next(iter(context["accounting_sources"][0]["binding_eligibility"].values()))
    status.update(eligible_for_accounting=eligible, reason="Existing guard result")
    value = service.capability(item, list(targets.values()), context)
    assert value["state"] == ("DISCOVERED" if eligible else "ACCOUNTING_BINDING_BLOCKED")
    assert value["accounting_binding"]["version_id"] == status["binding_version_id"]
    assert not value["current_use_authorized"]


def test_generic_source_cannot_borrow_posted_function_capability():
    item, targets, context = posted_fixture()
    context["accounting_sources"][0]["scope"]["attributes"]["source_profile"] = "generic_table"
    with pytest.raises(WorkspaceError, match="matching source"):
        service.capability(item, list(targets.values()), context)
