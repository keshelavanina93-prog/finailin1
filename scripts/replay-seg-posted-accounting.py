"""Replay the explicit reviewed SEG January accounting meaning through canonical APIs.

Requires the original retained source and reviewed company alias in the target DB.
Uses stable native identities, separate configured proposer/reviewer, and refuses
conflicting existing maps. Does not import isolated versions or source bytes.
Run with the target checkout's load-local environment and --apply. Without --apply
this prints the intended scope and performs no writes. Function manifests must be
reviewed separately after the target code and migrations are frozen.
"""

import argparse
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid5

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import ResourceMutation, ResourceProposal

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
if not parser.parse_args().apply:
    print(
        "SEG / Base / January2025: statutory1C, GEL, source_amount asposted, Amount non-authoritative. Use --apply to run canonical separate review."
    )
    raise SystemExit(0)
import json
import os
from uuid import UUID

from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources, seg_account_observations, seg_chart_binding

principals = [
    Principal.model_validate(value)
    for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
]
author = next(
    p
    for p in principals
    if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
)
reviewer = next(
    p
    for p in principals
    if p.actor_id != author.actor_id
    and p.scope.tenant_id == author.scope.tenant_id
    and {"ontology_admin", "ontology_review"} <= set(p.permissions)
)
company = UUID("365aa5d9-c2ec-52e1-867a-50fe3415f486")
receipt = "ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6"
from finai_api.services.accounting_source_document import read_source

metadata, _ = read_source(author, receipt)
assert (
    metadata["source_sha256"]
    == "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
), "Retained source differs"
new_fields = {
    "SourceAccountingBinding": [
        "vat_treatment",
        "supplementary_amount_field",
        "supplementary_amount_role",
    ],
    "MappingVersion": ["definition"],
    "FunctionDefinition": [
        "accounting_binding_id",
        "source_scope_id",
        "minimum_authority_state",
    ],
    "TransformationDefinition": ["minimum_authority_state"],
}
for spec in platform_definitions(author.scope.tenant_id):
    names = new_fields.get(spec["identity_key"])
    if spec["object_type"] != "SchemaDefinition" or names is None:
        continue
    identity = canonical_id(
        author.scope.tenant_id, "SchemaDefinition", spec["identity_key"]
    )
    prior = resources.get_resource(author, identity)["resource"]
    attrs = deepcopy(prior["attributes"])
    for name in names:
        native = spec["attributes"]["fields"][name]
        if name in attrs["fields"] and attrs["fields"][name] != native:
            raise ValueError(
                "Conflicting schema field: " + spec["identity_key"] + "." + name
            )
        attrs["fields"][name] = native
    if attrs != prior["attributes"]:
        proposal = ResourceProposal(
            title="Add reviewed posted-amount policy fields",
            rationale="Add native optional fields for the explicit user-reviewed SEG posted-amount contract; retain all existing schema fields.",
            access_entity="__PLATFORM__",
            mutations=[
                ResourceMutation(
                    resource_id=identity,
                    expected_version_id=prior["version_id"],
                    object_type="SchemaDefinition",
                    identity_key=spec["identity_key"],
                    display_name=prior["display_name"],
                    attributes=attrs,
                    valid_from=datetime.now(UTC),
                    evidence_class="REFERENCE_TEMPLATE",
                )
            ],
        )
        resources.propose(author, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale=proposal.rationale),
        )

observed = seg_account_observations.inspect(
    author, receipt, "Base", "seg_expense_base", company
)
print(
    json.dumps(
        [
            {"code": r["code"], "definitions": len(r["definitions"])}
            for r in observed["rows"]
        ]
    )
)
assert all(len(row["definitions"]) == 1 for row in observed["rows"])


def accept(detail):
    resources.review(
        reviewer,
        detail.proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Apply user-reviewed SEG statutory 1C interpretation from task answer 01a07c83-6369-7871-853c-272dc600a450; exact source/account pins checked. No completeness certification.",
        ),
    )
    print("reviewed_proposal", str(detail.proposal.proposal_id))


for offset in range(0, len(observed["rows"]), 20):
    choices = [
        {
            "code": row["code"],
            "definition_id": row["definitions"][0]["resource_id"],
            "definition_version_id": row["definitions"][0]["version_id"],
        }
        for row in observed["rows"][offset : offset + 20]
    ]
    try:
        detail = seg_chart_binding.propose(
            author,
            receipt,
            "Base",
            "seg_expense_base",
            company,
            seg_chart_binding.ChartSelection(
                source_sha256=observed["source_sha256"],
                accounts=choices,
                rationale="User reviewed uploaded 1C chart as governing SEG statutory accounting; each literal source code has one retained exact-code definition.",
            ),
        )
        accept(detail)
    except Exception as exc:
        if "already retained" not in str(exc):
            raise
from uuid import uuid4

from finai_api.services import source_accounting_context, source_accounting_setup

context = source_accounting_context.inspect(
    author, receipt, "Base", "seg_expense_base", company
)
if not context["scope"]:
    accept(
        source_accounting_context.propose_scope(
            author, receipt, "Base", "seg_expense_base", company
        )
    )
setup = source_accounting_setup.SetupSelection(
    request_id=uuid4(),
    ledger_code="STATUTORY_1C",
    ledger_name="SEG statutory 1C general ledger",
    book_code="REGLAMENTED",
    book_name="1C reglamented accounting",
    currency_code="GEL",
    calendar={"code": "CALENDAR_YEAR", "name": "SEG calendar year"},
    period={"name": "January 2025", "starts_on": "2025-01-01", "ends_on": "2025-01-31"},
    rationale="User reviewed statutory/reglamented 1C GL, GEL functional currency and January 2025 Base. Calendar interval names the supplied source slice, without period-completeness certification.",
)
try:
    created = source_accounting_setup.propose(
        author, receipt, "Base", "seg_expense_base", company, setup
    )
except Exception as exc:
    if getattr(exc, "detail", None) != (
        "This accounting structure is already reviewed; select its existing resources"
    ):
        raise
    planned, _ = source_accounting_setup.planned_identities(
        author.scope.tenant_id, company, UUID(context["observed"]["chart_id"]), setup
    )
    created = {"planned": planned, "review_required": False}
if created.get("review_required"):
    resources.review(
        reviewer,
        UUID(created["proposal_id"]),
        ResourceReview(decision="APPROVED", rationale=setup.rationale),
    )
print("setup", json.dumps(created["planned"]))
planned = created["planned"]

account_mapping = uuid5(company, "seg-source-account-identity-map/v1")
dimension_mapping = uuid5(company, "seg-source-dimension-preservation/v1")
accounts = [
    r
    for r in resources.list_resources(author, "LocalAccount", "", 0, limit=1000)
    if r.attributes["chart_id"] == planned["chart_id"]
]
assert len(accounts) == 38
policies = [
    (
        account_mapping,
        "SEG exact source account identities",
        "LocalAccount",
        {
            "kind": "EXACT_SOURCE_ACCOUNT_IDENTITIES",
            "version": 1,
            "company_id": str(company),
            "chart_id": planned["chart_id"],
            "accounts": {
                a.attributes["account_code"]: {
                    "resource_id": str(a.resource_id),
                    "version_id": str(a.version_id),
                }
                for a in accounts
            },
            "financial_statement_classification": "NOT_ESTABLISHED",
        },
    ),
    (
        dimension_mapping,
        "SEG source analytical coordinates",
        "SourceRecord",
        {
            "kind": "PRESERVE_SOURCE_DIMENSION_COORDINATES",
            "version": 1,
            "company_id": str(company),
            "canonical_dimension_classification": "NOT_ESTABLISHED",
            "aggregation_dimensions": [],
            "policy": "Retain all debit and credit source cells losslessly. No canonical dimension identity is inferred.",
        },
    ),
]
mutations = []
pins = {}
for identity, name, schema, definition in policies:
    try:
        existing = resources.get_resource(author, identity)["resource"]
    except Exception as exc:
        if getattr(exc, "status", None) != 404:
            raise
    else:
        assert existing["attributes"]["definition"] == definition
        continue
    schema_id = str(canonical_id(author.scope.tenant_id, "SchemaDefinition", schema))
    mutations.append(
        ResourceMutation(
            resource_id=identity,
            object_type="MappingVersion",
            identity_key="source-map:" + str(identity),
            display_name=name,
            evidence_class="USER_ASSERTED",
            valid_from=datetime.now(UTC),
            attributes={
                "source_schema_id": schema_id,
                "target_schema_id": schema_id,
                "definition": definition,
            },
        )
    )
    if identity == account_mapping:
        pins[identity] = {a.resource_id: a.version_id for a in accounts}
if mutations:
    proposal = ResourceProposal(
        title="Retain reviewed SEG source mapping boundaries",
        rationale="Exact account identities from the reviewed source chart; analytical cells preserved without invented dimension classifications.",
        access_entity=author.scope.legal_entity_id,
        mutations=mutations,
        source_versions=pins,
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale=proposal.rationale),
    )
selection = source_accounting_context.ContextSelection(
    source_use="ACCOUNTING_INPUT",
    contract_version="2",
    ledger_id=planned["ledger_id"],
    book_id=planned["book_id"],
    period_id=planned["period_id"],
    currency_id=planned["currency_id"],
    functional_currency_id=planned["currency_id"],
    currency_role="FUNCTIONAL",
    currency_policy="SOURCE_AMOUNT_ONLY",
    account_mapping_id=account_mapping,
    dimension_mapping_id=dimension_mapping,
    granularity="SOURCE_ROW",
    deepest_valid_drill="SOURCE_CELL",
    amount_field="source_amount",
    amount_semantics="DEBIT_CREDIT",
    vat_treatment="AS_POSTED",
    supplementary_amount_field="annotated_amount",
    supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
    rationale="User-reviewed interpretation01a07c83-6369-7871-853c-272dc600a450: SEG statutory/reglamented1C, GEL, Сумма as posted. Amount non-authoritative, no global VAT adjustment, preserve FX separately. S288 is unavailable; no completeness certification or zero substitution.",
)
current = source_accounting_context.inspect(
    author, receipt, "Base", "seg_expense_base", company
)["binding"]
expected = selection.model_dump(mode="json", exclude_none=True)
if (
    current is None
    or {k: v for k, v in current["attributes"].items() if k != "scope_id"} != expected
):
    detail = source_accounting_context.propose_binding(
        author, receipt, "Base", "seg_expense_base", company, selection
    )
    resources.review(
        reviewer,
        detail.proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale=selection.rationale),
    )
result = source_accounting_context.inspect(
    author, receipt, "Base", "seg_expense_base", company
)


from finai_api.domain.resource_lifecycle import (
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.services import resource_lifecycle
from psycopg.rows import dict_row

binding = result["binding"]
ref = VersionReference(
    resource_id=UUID(binding["resource_id"]), version_id=UUID(binding["version_id"])
)
with (
    resources.resource_connection(author) as conn,
    conn.cursor(row_factory=dict_row) as cur,
):
    event = resource_lifecycle._latest(cur, author, ref.version_id)
if event is None:
    request = LifecycleRequest(
        subject=ref,
        target_state="OBSERVED",
        epistemic_state="INFERRED",
        business_state="PROVISIONAL",
        availability_state="AVAILABLE",
        reason=selection.rationale,
    )
    resource_lifecycle.request_transition(author, request)
    resource_lifecycle.review_transition(
        reviewer,
        request.request_id,
        LifecycleReview(decision="APPROVED", reason=selection.rationale),
    )
result = source_accounting_context.inspect(
    author, receipt, "Base", "seg_expense_base", company
)
print(
    json.dumps(
        {
            "binding": binding["resource_id"],
            "version": binding["version_id"],
            "eligibility": result["accounting_eligibility"]["state"],
        }
    )
)
