"""Historical regulatory company binding; synthetic adapters, no legal or database writes."""

from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID

import pytest
from test_company_home import resource, uid

from finai_api.api import regulation_routes as routes
from finai_api.domain.review import Principal
from finai_api.services.workspace import WorkspaceError

AT = datetime.fromisoformat("2025-01-31T23:01:02.123456+04:00")
KNOWN = datetime.fromisoformat("2025-02-10T23:01:02.654321+04:00")


@pytest.fixture
def case(monkeypatch):
    principal = Principal(
        actor_id="historical-regulation-reader",
        display_name="Synthetic reader",
        scope={
            "tenant_id": uid("tenant"),
            "legal_entity_id": "entity-ge-001",
            "period": "2025-01",
            "currency": "GEL",
        },
        permissions=("ontology_read",),
    )
    company = resource("Historical company", "LegalEntity")
    resolved = {"canonical_id": company["resource_id"], "version_id": company["version_id"]}
    resolver = Mock(return_value=resolved)
    inspect = Mock(return_value={"resource": company})
    listing = Mock(return_value=[])
    monkeypatch.setattr(routes.resources, "resolve_identity", resolver)
    monkeypatch.setattr(routes.operator_inspection, "inspect", inspect)
    monkeypatch.setattr(routes.resources, "list_resources", listing)
    monkeypatch.setattr(routes, "licence_bindings", Mock(return_value=([], True)))
    current = Mock(side_effect=AssertionError("Current company fallback forbidden"))
    monkeypatch.setattr(routes.resources, "get_resource", current)
    return principal, company, resolver, inspect, listing, current


def test_rules_bind_exact_historical_company_and_keep_incomplete_scenario(case):
    principal, company, resolver, inspect, listing, current = case
    identity = UUID(company["resource_id"])
    result = routes.rules(principal, identity, at=AT, known_at=KNOWN)
    resolver.assert_called_once_with(principal, identity, known_at=KNOWN, valid_at=AT)
    inspect.assert_called_once_with(
        principal, identity, version_id=UUID(company["version_id"]), known_at=KNOWN
    )
    listing.assert_called_once_with(principal, "RegulatoryRule", "", 0, KNOWN, KNOWN)
    assert result["company"] == {
        key: company[key] for key in ("resource_id", "version_id", "display_name")
    }
    assert result["at"] == AT and result["known_at"] == KNOWN
    assert result["context_basis"] == "INCOMPLETE_CONTEXT"
    assert result["activity"] is None and result["accounting_effects_created"] is False
    assert result["rules"] == [] and result["next_offset"] is None
    current.assert_not_called()


@pytest.mark.parametrize("status", [403, 404])
def test_missing_historical_or_scope_denied_company_never_falls_back(case, status):
    principal, company, resolver, inspect, listing, current = case
    resolver.side_effect = WorkspaceError(status, "Unavailable in authorized historical scope")
    with pytest.raises(WorkspaceError) as error:
        routes.rules(principal, UUID(company["resource_id"]), at=AT, known_at=KNOWN)
    assert error.value.status == status
    inspect.assert_not_called()
    listing.assert_not_called()
    current.assert_not_called()


def test_resolved_identity_redirect_requires_explicit_company_choice(case):
    principal, company, resolver, inspect, listing, _ = case
    resolver.return_value = {
        "canonical_id": str(uid("other-company")),
        "version_id": company["version_id"],
    }
    with pytest.raises(WorkspaceError, match="select it explicitly") as error:
        routes.rules(principal, UUID(company["resource_id"]), at=AT, known_at=KNOWN)
    assert error.value.status == 409
    inspect.assert_not_called()
    listing.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"resource_id": str(uid("other-company"))},
        {"version_id": str(uid("new-version"))},
        {"authority_state": "REVOKED"},
        {"evidence_class": "REFERENCE_TEMPLATE"},
    ],
)
def test_exact_read_mismatch_or_unapproved_company_refuses_before_rules(case, change):
    principal, company, _, inspect, listing, _ = case
    inspect.return_value = {"resource": {**company, **change}}
    with pytest.raises(WorkspaceError) as error:
        routes.rules(principal, UUID(company["resource_id"]), at=AT, known_at=KNOWN)
    assert error.value.status == 409
    listing.assert_not_called()


@pytest.mark.parametrize("field", ["at", "known_at"])
def test_naive_cutoff_refused_before_any_company_read(case, field):
    principal, company, resolver, inspect, _, _ = case
    cutoffs = {"at": AT, "known_at": KNOWN, field: datetime(2025, 1, 1)}
    with pytest.raises(WorkspaceError, match="timezone"):
        routes.rules(principal, UUID(company["resource_id"]), **cutoffs)
    resolver.assert_not_called()
    inspect.assert_not_called()


@pytest.mark.parametrize("visible", [True, False])
def test_real_asof_resolver_uses_authorized_connection_and_both_cutoffs(monkeypatch, visible):
    """Exercise actual resolver + inspection SQL contracts, not a substitute temporal algorithm."""
    principal = Principal(
        actor_id="scoped-reader",
        display_name="Synthetic reader",
        scope={
            "tenant_id": uid("scope-tenant"),
            "legal_entity_id": "entity-ge-001",
            "period": "2025-01",
            "currency": "GEL",
        },
        permissions=("ontology_read",),
    )
    company = resource("Historical company", "LegalEntity")
    queries, actors = [], []

    class Cursor:
        def cursor(self, **_):
            return nullcontext(self)

        def execute(self, query, params):
            queries.append((query, params))
            return self

        def fetchone(self):
            return company if visible else None

        def fetchall(self):
            return []

    def scoped_connection(actor):
        actors.append(actor)
        return nullcontext(Cursor())

    monkeypatch.setattr(routes.resources, "resource_connection", scoped_connection)
    monkeypatch.setattr(routes.operator_inspection, "resource_connection", scoped_connection)
    monkeypatch.setattr(
        routes.resources, "get_resource", Mock(side_effect=AssertionError("No head"))
    )
    identity = UUID(company["resource_id"])
    if visible:
        result = routes._company_at(principal, identity, AT, KNOWN)
        assert result["version_id"] == company["version_id"]
        assert actors == [principal, principal]
        exact_reads = [(sql, params) for sql, params in queries if "v.version_id=%s" in sql]
        assert len(exact_reads) == 1
        assert exact_reads[0][1] == (
            principal.scope.tenant_id,
            identity,
            KNOWN,
            UUID(company["version_id"]),
            UUID(company["version_id"]),
        )
    else:
        with pytest.raises(WorkspaceError) as error:
            routes._company_at(principal, identity, AT, KNOWN)
        assert error.value.status == 404
        assert actors == [principal]
    sql, params = queries[0]
    assert params == (principal.scope.tenant_id, identity, KNOWN, AT, AT)
    assert "system_from<=%s" in sql and "valid_from<=%s" in sql and "valid_to>%s" in sql
    assert "resource_heads" not in sql
    assert AT.astimezone(UTC).microsecond == 123456
    assert KNOWN.astimezone(UTC).microsecond == 654321
