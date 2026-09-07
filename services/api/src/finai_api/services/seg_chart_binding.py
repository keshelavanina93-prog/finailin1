"""Explicit SEG account candidate selection through the shared resource review lifecycle."""

from datetime import UTC, datetime
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import resources, seg_account_observations, source_company_alias
from finai_api.services.workspace import WorkspaceError


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)
    definition_id: UUID
    definition_version_id: UUID


class ChartSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accounts: list[AccountSelection] = Field(min_length=1, max_length=20)
    rationale: str = Field(min_length=10, max_length=1700)

    @model_validator(mode="after")
    def unique_codes(self):
        if len({a.code for a in self.accounts}) != len(self.accounts):
            raise ValueError("Select each exact account code once")
        if len(self.rationale.strip()) < 10:
            raise ValueError("Explain why these definitions apply to this company source")
        return self


def propose(principal, document_id, sheet, profile, company_id, selection: ChartSelection):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    observed = seg_account_observations.inspect(principal, document_id, sheet, profile, company_id)
    if observed["source_sha256"] != selection.source_sha256:
        raise WorkspaceError(409, "Source changed; inspect the retained account candidates again")
    company_binding = source_company_alias.inspect(
        principal, document_id, sheet, profile, company_id
    )
    if (
        not company_binding["accepted"]
        or company_binding["source_sha256"] != selection.source_sha256
    ):
        raise WorkspaceError(409, "The source company binding is no longer available")
    company = company_binding["company"]
    selected = []
    rows = {row["code"]: row for row in observed["rows"]}
    for choice in selection.accounts:
        row = rows.get(choice.code)
        if row is None:
            raise WorkspaceError(409, "Selected account code is absent from the source")
        definition = (
            next(
                (
                    d
                    for d in row["definitions"]
                    if d["resource_id"] == str(choice.definition_id)
                    and d["version_id"] == str(choice.definition_version_id)
                ),
                None,
            )
            if row
            else None
        )
        if not definition:
            raise WorkspaceError(409, "Selected definition is not a current exact-code candidate")
        selected.append((row, definition))
    evidence_id = canonical_id(principal.scope.tenant_id, "SourceEvidence", selection.source_sha256)
    chart_id = uuid5(company_id, "1c-observed-chart")
    now = datetime.now(UTC)
    mutations, pins = [], {}
    company_pins = {company_id: UUID(company["version_id"])}
    if company_binding.get("alias"):
        alias = company_binding["alias"]
        company_pins[UUID(alias["resource_id"])] = UUID(alias["version_id"])

    def add(identity, kind, name, attributes, dependencies=None, evidence_class="SOURCE_BOUND"):
        try:
            prior = resources.get_resource(principal, identity)["resource"]
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
        else:
            if prior["object_type"] != kind or prior["attributes"] != attributes:
                raise WorkspaceError(
                    409, "Existing canonical chart or account conflicts with this selection"
                )
            if dependencies:
                with resources.resource_connection(principal) as conn:
                    retained = {
                        str(row[0]): str(row[1])
                        for row in conn.execute(
                            "SELECT target_resource_id,target_version_id "
                            "FROM resource_dependencies WHERE tenant_id=%s AND version_id=%s "
                            "AND relation LIKE 'BOUND_SOURCE:%%'",
                            (principal.scope.tenant_id, prior["version_id"]),
                        ).fetchall()
                    }
                if any(retained.get(str(key)) != str(value) for key, value in dependencies.items()):
                    raise WorkspaceError(
                        409, "Existing account has different reviewed definition pins"
                    )
            return
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key="source-chart:" + str(identity),
                display_name=name[:200],
                attributes=attributes,
                valid_from=now,
                evidence_class=evidence_class,
            )
        )
        if dependencies:
            pins[identity] = dependencies

    add(
        chart_id,
        "LocalChartOfAccounts",
        "Observed 1C chart · " + company["display_name"],
        {
            "legal_entity_id": str(company_id),
            "code": "observed-1c-" + str(company_id),
            "evidence_id": str(evidence_id),
        },
        company_pins,
    )
    for row, definition in selected:
        coordinate = row["coordinates"][0]["coordinate"]
        record_id = uuid5(evidence_id, coordinate)
        account_id = uuid5(chart_id, row["code"])
        add(
            record_id,
            "SourceRecord",
            coordinate,
            {
                "evidence_id": str(evidence_id),
                "coordinate": coordinate,
            },
        )
        add(
            account_id,
            "LocalAccount",
            row["code"] + " · " + definition["display_name"],
            {
                "chart_id": str(chart_id),
                "account_code": row["code"],
                "evidence_id": str(evidence_id),
            },
            {UUID(definition["resource_id"]): UUID(definition["version_id"])},
        )
        add(
            uuid5(account_id, "observed-in:" + str(record_id)),
            "Relationship",
            "Account usage at " + coordinate,
            {
                "relation_id": str(
                    canonical_id(principal.scope.tenant_id, "LinkType", "DERIVED_FROM")
                ),
                "source_id": str(account_id),
                "target_id": str(record_id),
                "evidence_id": str(evidence_id),
            },
        )
    if not mutations:
        raise WorkspaceError(
            409, "Selected accounts are already retained with these definition pins"
        )
    return resources.propose(
        principal,
        ResourceProposal(
            title="Review SEG source account definitions in the canonical company chart",
            rationale=selection.rationale
            + "\nThis selection does not establish chart completeness, "
            "currency, amount semantics, financial classification, "
            "journal completeness or accounting use.",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
            source_versions=pins,
        ),
    )
