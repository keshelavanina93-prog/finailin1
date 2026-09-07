"""Opt-in durable native SYNTHETIC acceptance; never an authentic paired-source claim.

Uses configured actor identities when explicitly supplied, otherwise three
synthetic service principals on the pre-seeded CI tenant. Both paths use an isolated
SYNTHETIC access_entity without changing persisted credentials, grants or schemas.
All retained documents and
canonical resources share that synthetic scope, separate from real SEG. Reuse the explicit
FINAI_SOURCE_ADOPTION_NATIVE_ID UUID to resume the same bounded fixture.
"""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile, ZipInfo

import pytest
from test_seg_expense_source import workbook

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import LifecycleRequest, LifecycleReview, VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.domain.source_adoption import SourceAdoptionSelection, SourceFamilySelection
from finai_api.services import (
    resource_lifecycle,
    resources,
    source_accounting_context,
    source_adoption,
    source_company_alias,
    source_documents,
)
from finai_api.services.workspace import WorkspaceError

REASON = "SYNTHETIC native source adoption acceptance only; no real SEG or financial certification."


def synthetic_book(label, month, *, missing=False):
    original = workbook(
        replacement={
            "A2": f"01.{month:02d}.2025 0:00:00",
            "C2": f"SYNTHETIC recorder {month}",
            "D2": label,
        }
    )
    result = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(result, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if missing and name.endswith("sheet1.xml"):
                content = content.replace(b'<c r="S2"><v>731.97</v></c>', b"")
            target.writestr(ZipInfo(name, (2025, 1, 1, 0, 0, 0)), content)
    return result.getvalue()


@pytest.fixture
def native_people(monkeypatch):
    namespace = UUID(os.environ.get("FINAI_SOURCE_ADOPTION_NATIVE_ID", str(uuid4())))
    configured = os.environ.get("FINAI_NATIVE_CONFIGURED_TOKENS")
    if configured:
        grants = json.loads(configured)
        # Preserve the explicit configured-native path; never discover mounted grants.
        monkeypatch.setenv("FINAI_ACCESS_TOKENS", json.dumps(grants))
        get_settings.cache_clear()
        people = [Principal.model_validate(value) for value in grants.values()]
        author = next(
            p for p in people if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
        )
        reviewer = next(
            p
            for p in people
            if p.actor_id != author.actor_id
            and p.scope == author.scope
            and {"ontology_admin", "ontology_review"} <= set(p.permissions)
        )
        ingestor = next(p for p in people if p.scope == author.scope and "ingest" in p.permissions)
        base_scope = author.scope
    else:
        base_scope = ExactScope(
            tenant_id=UUID(
                os.environ.get(
                    "FINAI_SOURCE_ADOPTION_NATIVE_TENANT", "805d8a32-d12b-4268-a236-b0b16e59da9f"
                )
            ),
            legal_entity_id="synthetic-native-fixture",
            period="2026-08",
            currency="GEL",
        )

        def person(role, permissions):
            return Principal(
                actor_id=f"synthetic-adoption-{namespace}-{role}",
                display_name=f"SYNTHETIC source adoption {role}",
                scope=base_scope,
                permissions=permissions,
            )

        author = person("author", ("read", "ontology_read", "ontology_admin", "ontology_propose"))
        reviewer = person(
            "reviewer", ("read", "ontology_read", "ontology_admin", "ontology_review")
        )
        ingestor = person("ingestor", ("read", "ontology_read", "ingest"))
        assert len({author.actor_id, reviewer.actor_id, ingestor.actor_id}) == 3
    synthetic_scope = base_scope.model_copy(
        update={"legal_entity_id": "SYNTHETIC-source-adoption-" + str(namespace)}
    )
    # Native-test principals only: no credential/grant registry changes. All
    # retained bytes and resources use this separate synthetic access boundary.
    author = author.model_copy(update={"scope": synthetic_scope})
    reviewer = reviewer.model_copy(update={"scope": synthetic_scope})
    ingestor = ingestor.model_copy(update={"scope": synthetic_scope})
    try:
        yield namespace, author, reviewer, ingestor
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(
    os.environ.get("FINAI_SOURCE_ADOPTION_NATIVE") != "1",
    reason="Explicit native synthetic opt-in required",
)
def test_native_reviewed_source_transition(native_people):
    namespace, author, reviewer, ingestor = native_people
    label = f"SYNTHETIC SEG-layout acceptance {namespace}"
    print("native_synthetic_namespace", str(namespace), flush=True)
    company = uuid5(namespace, "company")
    chart = uuid5(company, "1c-observed-chart")
    ids = {
        key: uuid5(namespace, key)
        for key in ("calendar", "currency", "ledger", "book", "accounts", "dimensions")
    }
    ids.update(company=company, chart=chart)
    proposals = []

    def get(identity):
        return resources.get_resource(author, identity)["resource"]

    def review(detail):
        proposal_id = detail.proposal.proposal_id
        resources.review(
            reviewer, proposal_id, ResourceReview(decision="APPROVED", rationale=REASON)
        )
        proposals.append(str(proposal_id))

    def item(identity, kind, attributes):
        return ResourceMutation(
            resource_id=identity,
            object_type=kind,
            identity_key=f"synthetic-adoption:{identity}",
            display_name=f"SYNTHETIC {kind} {str(namespace)[:8]}",
            attributes=attributes,
            valid_from=datetime.now(UTC),
            evidence_class="USER_ASSERTED",
        )

    def publish(mutations, pins=None):
        prior = resources.current_resources(author, [m.resource_id for m in mutations])
        pending = []
        for mutation in mutations:
            old = prior.get(str(mutation.resource_id))
            if old:
                assert old["attributes"] == mutation.attributes
            else:
                pending.append(mutation)
        if pending:
            proposal = ResourceProposal(
                title="SYNTHETIC native recurring source fixture",
                rationale=REASON,
                access_entity=author.scope.legal_entity_id,
                mutations=pending,
                source_versions={
                    key: value
                    for key, value in (pins or {}).items()
                    if key in {m.resource_id for m in pending}
                },
            )
            review(resources.propose(author, proposal))

    publish(
        [
            item(company, "LegalEntity", {"registration_code": "SYNTHETIC-" + str(namespace)}),
            item(
                chart,
                "LocalChartOfAccounts",
                {"legal_entity_id": str(company), "code": "SYNTHETIC"},
            ),
            item(ids["calendar"], "FiscalCalendar", {"code": "SYNTHETIC"}),
            item(ids["currency"], "Currency", {"code": "GEL"}),
            item(
                ids["ledger"],
                "Ledger",
                {
                    "legal_entity_id": str(company),
                    "chart_id": str(chart),
                    "calendar_id": str(ids["calendar"]),
                    "currency_id": str(ids["currency"]),
                },
            ),
            item(
                ids["book"],
                "AccountingBook",
                {"ledger_id": str(ids["ledger"]), "code": "SYNTHETIC"},
            ),
            *[
                item(
                    uuid5(chart, code),
                    "LocalAccount",
                    {"chart_id": str(chart), "account_code": code},
                )
                for code in ("0012.01", "3110")
            ],
        ]
    )
    company_before = source_adoption.pin(get(company))
    accounts = [get(uuid5(chart, code)) for code in ("0012.01", "3110")]
    mapping = {
        "kind": "EXACT_SOURCE_ACCOUNT_IDENTITIES",
        "version": 1,
        "company_id": str(company),
        "chart_id": str(chart),
        "accounts": {
            row["attributes"]["account_code"]: {
                "resource_id": str(row["resource_id"]),
                "version_id": str(row["version_id"]),
            }
            for row in accounts
        },
    }
    dimension = {
        "kind": "PRESERVE_SOURCE_DIMENSION_COORDINATES",
        "version": 1,
        "company_id": str(company),
        "aggregation_dimensions": [],
    }
    maps = []
    for key, definition, schema in [
        ("accounts", mapping, "LocalAccount"),
        ("dimensions", dimension, "SourceRecord"),
    ]:
        schema_id = str(canonical_id(author.scope.tenant_id, "SchemaDefinition", schema))
        maps.append(
            item(
                ids[key],
                "MappingVersion",
                {
                    "source_schema_id": schema_id,
                    "target_schema_id": schema_id,
                    "definition": definition,
                },
            )
        )
    publish(
        maps,
        {
            ids["accounts"]: {
                UUID(str(a["resource_id"])): UUID(str(a["version_id"])) for a in accounts
            }
        },
    )
    bindings = []
    documents = []
    for month, end in [(1, 31), (2, 28), (3, 31)]:
        content = synthetic_book(label, month, missing=month == 1)
        retained = source_documents.retain_document(
            ingestor, f"SYNTHETIC-{namespace}-{month}.xlsx", content
        )
        document = retained["document_id"]
        documents.append(document)
        matched = source_company_alias.inspect(
            author, document, "Base", "seg_expense_base", company
        )
        if not matched["accepted"]:
            review(
                source_company_alias.propose(
                    author, document, "Base", "seg_expense_base", company, REASON
                )
            )
        current = source_accounting_context.inspect(
            author, document, "Base", "seg_expense_base", company
        )
        if not current["scope"]:
            review(
                source_accounting_context.propose_scope(
                    author, document, "Base", "seg_expense_base", company
                )
            )
        period = uuid5(namespace, f"period-{month}")
        publish(
            [
                item(
                    period,
                    "FiscalPeriod",
                    {
                        "calendar_id": str(ids["calendar"]),
                        "starts_on": f"2025-{month:02d}-01",
                        "ends_on": f"2025-{month:02d}-{end}",
                    },
                )
            ]
        )
        selection = source_accounting_context.ContextSelection(
            source_use="ACCOUNTING_INPUT",
            contract_version="2",
            ledger_id=ids["ledger"],
            book_id=ids["book"],
            period_id=period,
            currency_id=ids["currency"],
            functional_currency_id=ids["currency"],
            currency_role="FUNCTIONAL",
            currency_policy="SOURCE_AMOUNT_ONLY",
            account_mapping_id=ids["accounts"],
            dimension_mapping_id=ids["dimensions"],
            granularity="SOURCE_ROW",
            deepest_valid_drill="SOURCE_CELL",
            amount_field="source_amount",
            amount_semantics="DEBIT_CREDIT",
            vat_treatment="AS_POSTED",
            supplementary_amount_field="annotated_amount",
            supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
            rationale=REASON,
        )
        if not current["binding"]:
            review(
                source_accounting_context.propose_binding(
                    author, document, "Base", "seg_expense_base", company, selection
                )
            )
        binding = get(UUID(current["binding_id"]))
        reference = VersionReference(
            resource_id=binding["resource_id"], version_id=binding["version_id"]
        )
        with resources.resource_connection(author) as conn:
            from psycopg.rows import dict_row

            with conn.cursor(row_factory=dict_row) as cursor:
                event = resource_lifecycle._latest(cursor, author, reference.version_id)
        if event is None:
            transition = LifecycleRequest(
                subject=reference,
                target_state="OBSERVED",
                epistemic_state="INFERRED",
                business_state="PROVISIONAL",
                availability_state="AVAILABLE",
                reason=REASON,
            )
            resource_lifecycle.request_transition(author, transition)
            resource_lifecycle.review_transition(
                reviewer, transition.request_id, LifecycleReview(decision="APPROVED", reason=REASON)
            )
        bindings.append(reference)
        print("native_synthetic_snapshot_ready", month, str(reference.resource_id), flush=True)
    family_selection = SourceFamilySelection(
        family_key="synthetic-base",
        source_system="SYNTHETIC-1C",
        display_name=label,
        baseline_binding=bindings[0],
        rationale=REASON,
    )
    prepared = source_adoption.prepare(author, family_selection)
    if not prepared["previous"]:
        review(source_adoption.propose(author, family_selection))
    family = get(UUID(prepared["resource_id"]))
    baseline = deepcopy(family["attributes"]["definition"]["baseline"])
    assert baseline["source_rows"] == baseline["missing_amount_count"] == 1
    assert baseline["missing_amount_coordinates"] == ["Base!S2"]
    selection = SourceAdoptionSelection(
        family=VersionReference(resource_id=family["resource_id"], version_id=family["version_id"]),
        predecessor_binding=bindings[0],
        successor_binding=bindings[1],
        policy="DISJOINT_PERIOD_ADDITION",
        rationale=REASON,
    )
    prepared = source_adoption.prepare(author, selection)
    if not prepared["previous"]:
        tampered = deepcopy(prepared["attributes"])
        tampered["definition"]["successor"]["schema_sha256"] = "f" * 64
        mutation = ResourceMutation(
            resource_id=prepared["resource_id"],
            object_type="SourceSnapshotAdoption",
            identity_key=prepared["identity_key"],
            display_name=prepared["display_name"],
            attributes=tampered,
            valid_from=datetime.now(UTC),
            evidence_class="USER_ASSERTED",
        )
        with pytest.raises(WorkspaceError, match="differs from retained bytes"):
            resources.propose(
                author,
                ResourceProposal(
                    title="SYNTHETIC tamper refusal",
                    rationale=REASON,
                    access_entity=author.scope.legal_entity_id,
                    mutations=[mutation],
                ),
            )
        detail = source_adoption.propose(author, selection)
        with pytest.raises(WorkspaceError, match="separate"):
            resources.review(
                author,
                detail.proposal.proposal_id,
                ResourceReview(decision="APPROVED", rationale=REASON),
            )
        review(detail)
    adoption = get(UUID(prepared["resource_id"]))
    result = source_adoption.read_successor(
        author,
        VersionReference(resource_id=adoption["resource_id"], version_id=adoption["version_id"]),
    )
    assert result["accounting_aggregation_authorized"] is False
    assert result["source"]["source_rows"] == 1 and result["source"]["missing_amount_count"] == 0
    assert result["source"]["period_starts_on"] == "2025-02-01"
    assert result["source"]["company"] == baseline["company"]
    assert result["source"]["company_alias"] != baseline["company_alias"]
    assert result["source"]["meaning"] == baseline["meaning"]
    assert source_adoption.pin(get(company)) == company_before
    assert get(UUID(family["resource_id"]))["attributes"]["definition"]["baseline"] == baseline
    with pytest.raises(WorkspaceError, match="reviewed successor"):
        source_adoption.prepare(
            author, selection.model_copy(update={"successor_binding": bindings[2]})
        )
    with pytest.raises(WorkspaceError, match="same reviewed period"):
        source_adoption.prepare(
            author, selection.model_copy(update={"policy": "REPLACES_PREDECESSOR_SNAPSHOT"})
        )
    print(
        json.dumps(
            {
                "native_synthetic_pass": True,
                "namespace": str(namespace),
                "company": str(company),
                "family": source_adoption.pin(family).model_dump(mode="json"),
                "adoption": source_adoption.pin(adoption).model_dump(mode="json"),
                "documents": documents,
                "proposals": proposals,
                "authentic_paired_source_acceptance": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
