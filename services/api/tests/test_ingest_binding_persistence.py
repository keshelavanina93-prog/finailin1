"""Opt-in PostgreSQL acceptance with isolated, explicitly synthetic enterprise resources."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services import resources


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)
@pytest.mark.parametrize("alias_mode", ["none", "account_revoked", "alias_revoked", "dimensions"])
def test_persistent_binding_review_export_and_revocation(
    monkeypatch: pytest.MonkeyPatch, alias_mode: str
) -> None:
    scope = ExactScope(
        tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
        legal_entity_id="synthetic-binding-" + uuid4().hex,
        period="2026-08",
        currency="GEL",
    )
    permissions = (
        "read",
        "ingest",
        "review",
        "export",
        "ontology_read",
        "ontology_admin",
        "ontology_propose",
        "ontology_review",
    )
    operator = Principal(
        actor_id="synthetic-operator",
        display_name="Synthetic operator",
        scope=scope,
        permissions=permissions,
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-reviewer"})
    ids = {
        key: uuid4()
        for key in (
            "entity",
            "calendar",
            "period",
            "currency",
            "chart",
            "ledger",
            "001",
            "002",
            "context",
        )
    }
    attrs = {
        "entity": ("LegalEntity", {}),
        "calendar": ("FiscalCalendar", {"code": "SYNTHETIC"}),
        "period": (
            "FiscalPeriod",
            {
                "calendar_id": str(ids["calendar"]),
                "starts_on": "2026-08-01",
                "ends_on": "2026-08-31",
            },
        ),
        "currency": ("Currency", {"code": "GEL"}),
        "chart": (
            "LocalChartOfAccounts",
            {"legal_entity_id": str(ids["entity"]), "code": "SYNTHETIC"},
        ),
        "ledger": (
            "Ledger",
            {
                "legal_entity_id": str(ids["entity"]),
                "chart_id": str(ids["chart"]),
                "currency_id": str(ids["currency"]),
                "calendar_id": str(ids["calendar"]),
            },
        ),
        "context": (
            "ContextBinding",
            {
                "legal_entity_id": str(ids["entity"]),
                "ledger_id": str(ids["ledger"]),
                "currency_id": str(ids["currency"]),
                "period_id": str(ids["period"]),
                "source_scope_key": canonical_sha256(scope),
            },
        ),
        **{
            code: ("LocalAccount", {"chart_id": str(ids["chart"]), "account_code": code})
            for code in ("001", "002")
        },
    }
    mutations = [
        ResourceMutation(
            resource_id=ids[key],
            object_type=kind,
            identity_key="context:" + canonical_sha256(scope)
            if key == "context"
            else "synthetic:" + str(ids[key]),
            display_name="SYNTHETIC binding acceptance " + key,
            attributes=attributes,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )
        for key, (kind, attributes) in attrs.items()
    ]
    if alias_mode == "dimensions":
        for key in ("department", "dept01", "dept02", "rule"):
            ids[key] = uuid4()
        for key, kind, attributes in (
            ("department", "DimensionDefinition", {"code": "DEPT"}),
            ("dept01", "DimensionMember", {"dimension_id": str(ids["department"]), "code": "01"}),
            ("dept02", "DimensionMember", {"dimension_id": str(ids["department"]), "code": "02"}),
            (
                "rule",
                "AccountDimensionRule",
                {
                    "account_id": str(ids["001"]),
                    "dimension_id": str(ids["department"]),
                    "required": True,
                },
            ),
        ):
            mutations.append(
                ResourceMutation(
                    resource_id=ids[key],
                    object_type=kind,
                    identity_key=f"account-dimension:{ids['001']}:{ids['department']}"
                    if key == "rule"
                    else "synthetic:" + str(ids[key]),
                    display_name="SYNTHETIC analytical acceptance " + key,
                    attributes=attributes,
                    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                    evidence_class="REFERENCE_TEMPLATE",
                )
            )
    proposal = ResourceProposal(
        title="SYNTHETIC canonical binding acceptance",
        rationale="Isolated non-authentic acceptance resources",
        access_entity=scope.legal_entity_id,
        mutations=mutations,
    )
    resources.propose(operator, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic acceptance review"),
    )
    versions = {
        key: str(uuid5(proposal.proposal_id, str(identifier))) for key, identifier in ids.items()
    }
    alias = None
    alias_version = None
    if alias_mode in ("account_revoked", "alias_revoked"):
        key = json.dumps(["synthetic-erp", "LocalAccount", "EXT001"], separators=(",", ":"))
        alias = ResourceMutation(
            object_type="Alias",
            identity_key="alias:" + sha256(key.encode()).hexdigest(),
            display_name="SYNTHETIC source account alias",
            attributes={
                "source_system": "synthetic-erp",
                "external_id": "EXT001",
                "target_id": str(ids["001"]),
            },
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )
        alias_proposal = ResourceProposal(
            title="SYNTHETIC reviewed source alias",
            rationale="Same canonical account across different source identifiers",
            access_entity=scope.legal_entity_id,
            mutations=[alias],
        )
        resources.propose(operator, alias_proposal)
        resources.review(
            reviewer,
            alias_proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Independent alias review"),
        )
        alias_version = str(uuid5(alias_proposal.proposal_id, str(alias.resource_id)))
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "operator": operator.model_dump(mode="json"),
                "reviewer": reviewer.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    outsider = operator.model_copy(
        update={
            "scope": scope.model_copy(update={"legal_entity_id": "another-synthetic-company"}),
            "permissions": ("read", "ingest", "ontology_read"),
        }
    )
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    grants["outsider"] = outsider.model_dump(mode="json")
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", json.dumps(grants))
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer operator"})
    payload: dict[str, Any] = {
        "scope": scope.model_dump(mode="json"),
        "filename": "SYNTHETIC-tb.csv",
        "csv_text": "account_code,debit,credit\n001,1.25,0\n002,0,1.25\n",
        "context_version_id": versions["context"],
        "account_version_ids": {code: versions[code] for code in ("001", "002")},
    }
    if alias_mode == "dimensions":
        payload.update(
            csv_text="account_code,debit,credit,dimension:DEPT\n001,0.50,0,01\n001,0.75,0,02\n002,0,1.25,\n",
            account_dimension_rule_version_ids={"001": [versions["rule"]]},
            dimension_member_version_ids={
                "DEPT": {"01": versions["dept01"], "02": versions["dept02"]}
            },
        )
        for csv_text, mappings, finding in (
            (
                "account_code,debit,credit\n001,1.25,0\n002,0,1.25\n",
                {},
                "missing required dimension:DEPT",
            ),
            (
                "account_code,debit,credit,dimension:DEPT\n001,1.25,0,UNKNOWN\n002,0,1.25,\n",
                {},
                "needs an accepted member mapping",
            ),
        ):
            bad = client.post(
                "/v1/hydration/ingest",
                json={**payload, "csv_text": csv_text, "dimension_member_version_ids": mappings},
            )
            assert bad.status_code == 200, bad.text
            assert finding in " ".join(bad.json()["rejects"])
            denied = client.post(
                f"/v1/workspace/constructions/{bad.json()['receipt_id']}/decision",
                headers={"Authorization": "Bearer reviewer"},
                json={
                    "decision": "APPROVED",
                    "reason": "Must reject incomplete dimensions",
                    "idempotency_key": str(uuid4()),
                    "expected_head": None,
                },
            )
            assert denied.status_code == 409, denied.text
        omitted = client.post(
            "/v1/hydration/ingest", json={**payload, "account_dimension_rule_version_ids": {}}
        )
        assert omitted.status_code == 409, omitted.text
    if alias is not None:
        payload.update(
            csv_text="account_code,debit,credit\nEXT001,1.25,0\n002,0,1.25\n",
            source_system="synthetic-erp",
            account_version_ids={"EXT001": versions["001"], "002": versions["002"]},
            account_alias_version_ids={"EXT001": alias_version},
        )
        for invalid in (
            {"source_system": "another-erp"},
            {"source_system": None},
            {"account_alias_version_ids": {}},
        ):
            failed = client.post("/v1/hydration/ingest", json={**payload, **invalid})
            assert failed.status_code == 422, failed.text
    choices = client.get("/v1/ontology/context")
    assert choices.status_code == 200, choices.text
    assert choices.json()["binding"]["version_id"] == versions["context"]
    choices = client.get(
        "/v1/ontology/context/accounts", params={"context_version_id": versions["context"]}
    )
    assert choices.status_code == 200, choices.text
    assert {row["account_code"] for row in choices.json()["items"]} == {"001", "002"}
    client.headers["Authorization"] = "Bearer outsider"
    assert client.get(
        "/v1/ontology/context/accounts", params={"context_version_id": versions["context"]}
    ).status_code in (403, 409)
    client.headers["Authorization"] = "Bearer operator"
    source_only = client.post(
        "/v1/ontology/context/source-accounts",
        json={
            **payload,
            "context_version_id": None,
            "account_version_ids": {},
            "account_alias_version_ids": {},
        },
    )
    assert source_only.status_code == 200, source_only.text
    preview = client.post("/v1/ontology/context/source-accounts", json=payload)
    assert set(preview.json()["account_codes"]) == {"001" if alias is None else "EXT001", "002"}
    response = client.post("/v1/hydration/ingest", json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["binding_state"] == "CANONICAL_BOUND"
    assert client.post("/v1/hydration/ingest", json=payload).json() == receipt
    rid = receipt["receipt_id"]
    detail = client.get(f"/v1/workspace/constructions/{rid}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["impact"]["added"] == len(receipt["candidates"])
    client.headers["Authorization"] = "Bearer reviewer"
    decision = {
        "decision": "APPROVED",
        "reason": "Independent synthetic accounting review",
        "idempotency_key": str(uuid4()),
        "expected_head": None,
    }
    response = client.post(f"/v1/workspace/constructions/{rid}/decision", json=decision)
    assert response.status_code == 200, response.text
    objects = client.get("/v1/workspace/objects").json()
    assert len(objects) == (6 if alias_mode == "dimensions" else 4)
    if alias_mode == "dimensions":
        analytical = [
            obj
            for obj in objects
            if obj["object_type"] == "PeriodBalance" and obj["values"]["account_code"] == "001"
        ]
        assert [
            obj["canonical_references"]["dimension:DEPT"]["version_id"]
            for obj in sorted(analytical, key=lambda obj: obj["source_row"])
        ] == [versions["dept01"], versions["dept02"]]
        assert all(
            obj["canonical_references"]["dimension_rule:DEPT"]["version_id"] == versions["rule"]
            for obj in analytical
        )
    assert all("account_id" in obj["canonical_references"] for obj in objects)
    if alias is not None:
        aliased = [obj for obj in objects if obj["values"]["account_code"] == "EXT001"]
        assert len(aliased) == 2
        assert all(
            obj["canonical_references"]["account_alias_id"]["version_id"] == alias_version
            and obj["canonical_references"]["account_id"]["resource_id"] == str(ids["001"])
            for obj in aliased
        )
    exported = client.get(f"/v1/workspace/constructions/{rid}/export").json()
    assert exported["construction"]["receipt"] == receipt
    # A second retained source cannot promote after its pinned account is revoked.
    client.headers["Authorization"] = "Bearer operator"
    second = client.post(
        "/v1/hydration/ingest", json={**payload, "filename": "SYNTHETIC-second.csv"}
    ).json()
    original = next(item for item in mutations if item.resource_id == ids["001"])
    revoked_version = versions["001"]
    if alias_mode == "dimensions":
        original = next(item for item in mutations if item.resource_id == ids["dept01"])
        revoked_version = versions["dept01"]
    if alias_mode == "alias_revoked":
        assert alias is not None and alias_version is not None
        original, revoked_version = alias, alias_version
    revoke = ResourceProposal(
        title="SYNTHETIC revoke account",
        rationale="Verify stale dependency fails closed",
        access_entity=scope.legal_entity_id,
        mutations=[
            original.model_copy(
                update={"expected_version_id": UUID(revoked_version), "authority_state": "REVOKED"}
            )
        ],
    )
    resources.propose(operator, revoke)
    resources.review(
        reviewer,
        revoke.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic revocation test"),
    )
    client.headers["Authorization"] = "Bearer reviewer"
    denied = client.post(
        f"/v1/workspace/constructions/{second['receipt_id']}/decision",
        json={**decision, "idempotency_key": str(uuid4()), "expected_head": rid},
    )
    assert denied.status_code == 409, denied.text
    assert (
        client.get(f"/v1/workspace/constructions/{rid}/export").json()["construction"]["receipt"]
        == receipt
    )
