"""Reviewed source-company labels resolve to existing legal entities through canonical Alias."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid5

from psycopg.rows import dict_row

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import CanonicalResource, ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.accounting_source_document import read_source
from finai_api.services.company_source import observe_companies, observe_tb_company
from finai_api.services.seg_expense_source import read_base
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError

SOURCE_SYSTEM = "RETAINED_ACCOUNTING_COMPANY"


def _effective_resources(principal, identities):
    if len(identities) > 100:
        raise WorkspaceError(422, "Resolve no more than 100 canonical identities per page")
    at = datetime.now(UTC)
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.resource_id=ANY(%s::uuid[]) "
            "AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,%s)",
            (principal.scope.tenant_id, identities, at),
        ).fetchall()
    return {
        str(row["resource_id"]): CanonicalResource.model_validate(row).model_dump(mode="json")
        for row in rows
    }


def observe(principal, document_id, sheet, profile):
    metadata, content = read_source(principal, document_id)
    if profile == "seg_expense_base":
        parsed = read_base(content, sheet)
        label = parsed["company_label"]
        headers = [
            coordinate
            for coordinate, cell in parsed["headers"].items()
            if cell["value"] == "Организация"
        ]
        if len(headers) != 1:
            raise WorkspaceError(422, "Source company header is ambiguous")
        column = headers[0].removeprefix(sheet + "!").removesuffix("1")
        coordinate = f"{sheet}!{column}{parsed['rows'][0]['row']}"
    elif profile in {"1c_tb", "1c_journal"}:
        observation = (
            observe_tb_company(content, sheet)
            if profile == "1c_tb"
            else observe_companies(content, sheet, 2, 10)
        )
        if len(observation["companies"]) != 1 or observation["unassigned_row_count"]:
            raise WorkspaceError(422, "Select a source with one explicit company label")
        label = observation["companies"][0]["source_label"]
        coordinate = observation["companies"][0]["first_coordinate"]
    else:
        raise WorkspaceError(422, "Unsupported source company alias profile")
    if not label or len(label) > 200:
        raise WorkspaceError(422, "Source company label exceeds the supported label bound")
    external_id = sha256(
        json.dumps(
            [metadata["source_sha256"], sheet, profile, label],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    key = (
        "alias:"
        + sha256(
            json.dumps(
                [SOURCE_SYSTEM, "LegalEntity", external_id],
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    evidence_id = canonical_id(
        principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"]
    )
    return {
        "document_id": document_id,
        "worksheet": sheet,
        "source_profile": profile,
        "source_label": label,
        "coordinate": coordinate,
        "source_sha256": metadata["source_sha256"],
        "external_id": external_id,
        "identity_key": key,
        "alias_id": str(canonical_id(principal.scope.tenant_id, "Alias", key)),
        "evidence_id": str(evidence_id),
        "source_record_id": str(uuid5(evidence_id, coordinate)),
    }


def inspect(principal, document_id, sheet, profile, company_id):
    observed = observe(principal, document_id, sheet, profile)
    effective = _effective_resources(principal, [company_id, UUID(observed["alias_id"])])
    company = effective.get(str(company_id))
    if (
        not company
        or company["object_type"] != "LegalEntity"
        or company["authority_state"] != "APPROVED"
        or company["evidence_class"] == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(409, "Select an existing accepted canonical legal entity")
    alias = effective.get(observed["alias_id"])
    accepted, reason = False, "Review the observed label against the existing company identity"
    can_propose = True
    if alias and alias["attributes"].get("target_id") == str(company_id):
        from finai_api.services.resource_lifecycle import _latest, _version

        try:
            expected = {
                "source_system": SOURCE_SYSTEM,
                "external_id": observed["external_id"],
                "target_id": str(company_id),
                "evidence_id": observed["evidence_id"],
                **{
                    field: observed[field]
                    for field in ("document_id", "worksheet", "source_profile", "source_record_id")
                },
            }
            if (
                alias["object_type"] != "Alias"
                or alias["evidence_class"] != "USER_ASSERTED"
                or alias["attributes"] != expected
                or alias["display_name"] != observed["source_label"]
            ):
                raise WorkspaceError(409, "Existing alias differs from this retained observation")
            # An identical approved alias with withdrawn upstream authority needs that
            # authority repaired; resubmitting identical alias content cannot repair it.
            can_propose = alias["authority_state"] != "APPROVED"
            with (
                resources.resource_connection(principal, repeatable_read=True) as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                reference = VersionReference(
                    resource_id=UUID(alias["resource_id"]), version_id=UUID(alias["version_id"])
                )
                _version(cursor, principal, reference)
                event = _latest(cursor, principal, reference.version_id)
                if event and (
                    event["payload"]["target_state"] in {"REVOKED", "SUPERSEDED"}
                    or event["payload"]["availability_state"] != "AVAILABLE"
                ):
                    raise WorkspaceError(
                        409, "Company alias authority or availability was withdrawn"
                    )
                upstream_authority(cursor, principal.scope.tenant_id, reference.version_id)
            accepted, reason = True, "Existing reviewed source alias resolves this company"
        except WorkspaceError as exc:
            reason = exc.detail
    return {
        **observed,
        "company": company,
        "alias": alias,
        "accepted": accepted,
        "can_propose": not accepted and can_propose,
        "reason": reason,
        "purpose": "SOURCE_COMPANY_IDENTITY_REVIEW",
        "accounting_use_authorized": False,
    }


def propose(principal, document_id, sheet, profile, company_id, rationale):
    observed = inspect(principal, document_id, sheet, profile, company_id)
    now = datetime.now(UTC)
    existing = resources.current_resources(
        principal, [UUID(observed[field]) for field in ("evidence_id", "source_record_id")]
    )
    mutations = []
    for field, kind, name, attrs in [
        (
            "evidence_id",
            "SourceEvidence",
            "Retained company label source",
            {"sha256": observed["source_sha256"], "source_system": "RETAINED_DOCUMENT"},
        ),
        (
            "source_record_id",
            "SourceRecord",
            observed["coordinate"],
            {"evidence_id": observed["evidence_id"], "coordinate": observed["coordinate"]},
        ),
    ]:
        if observed[field] not in existing:
            mutations.append(
                ResourceMutation(
                    resource_id=UUID(observed[field]),
                    object_type=kind,
                    identity_key=observed["source_sha256"]
                    if kind == "SourceEvidence"
                    else "source-record:" + observed["source_record_id"],
                    display_name=name,
                    attributes=attrs,
                    valid_from=now,
                    evidence_class="SOURCE_BOUND",
                )
            )
    # Inspect current effective attribution, but edits compare against the latest
    # publication head, which may already contain a scheduled alias revision.
    previous = resources.current_resources(principal, [UUID(observed["alias_id"])]).get(
        observed["alias_id"]
    )
    attrs = {
        "source_system": SOURCE_SYSTEM,
        "external_id": observed["external_id"],
        "target_id": str(company_id),
        "evidence_id": observed["evidence_id"],
        **{
            field: observed[field]
            for field in ("document_id", "worksheet", "source_profile", "source_record_id")
        },
    }
    effective_alias = observed["alias"]
    if any(
        row and row["authority_state"] == "APPROVED" and row["attributes"] == attrs
        for row in (previous, effective_alias)
    ):
        raise WorkspaceError(409, "This reviewed company alias is already current or scheduled")
    alias = ResourceMutation(
        resource_id=UUID(observed["alias_id"]),
        object_type="Alias",
        identity_key=observed["identity_key"],
        display_name=observed["source_label"],
        attributes=attrs,
        expected_version_id=UUID(previous["version_id"]) if previous else None,
        valid_from=now,
        evidence_class="USER_ASSERTED",
    )
    mutations.append(alias)
    company = observed["company"]
    pinned = {
        UUID(company["resource_id"]): UUID(company["version_id"]),
        **{UUID(key): UUID(row["version_id"]) for key, row in existing.items()},
    }
    return resources.propose(
        principal,
        ResourceProposal(
            title="Review source company identity",
            rationale=rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
            source_versions={alias.resource_id: pinned},
        ),
    )


def validate_alias(principal, item, target):
    if item.attributes.get("source_system") != SOURCE_SYSTEM:
        return
    attrs, key = item.attributes, str(item.resource_id)
    if any(
        not attrs.get(field)
        for field in ("document_id", "worksheet", "source_profile", "source_record_id")
    ):
        raise WorkspaceError(422, "Source company aliases require retained provenance")
    observed = observe(principal, attrs["document_id"], attrs["worksheet"], attrs["source_profile"])
    expected = {
        "source_system": SOURCE_SYSTEM,
        "external_id": observed["external_id"],
        "target_id": attrs["target_id"],
        "evidence_id": observed["evidence_id"],
        **{
            field: observed[field]
            for field in ("document_id", "worksheet", "source_profile", "source_record_id")
        },
    }
    if (
        attrs != expected
        or str(item.resource_id) != observed["alias_id"]
        or item.identity_key != observed["identity_key"]
        or item.display_name != observed["source_label"]
        or item.evidence_class != "USER_ASSERTED"
    ):
        raise WorkspaceError(
            422, "Source company alias differs from the retained company observation"
        )
    company = target(attrs["target_id"], key, "SOURCE_COMPANY_TARGET")
    record = target(attrs["source_record_id"], key, "SOURCE_COMPANY_RECORD")
    if (
        company["object_type"] != "LegalEntity"
        or not company.get("system_from")
        or company["authority_state"] != "APPROVED"
        or company["evidence_class"] == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(
            409, "Source company alias must target an existing accepted legal entity"
        )
    if (
        record["object_type"] != "SourceRecord"
        or record["evidence_class"] != "SOURCE_BOUND"
        or record["attributes"]
        != {"evidence_id": observed["evidence_id"], "coordinate": observed["coordinate"]}
    ):
        raise WorkspaceError(
            422, "Source company alias record does not match its original coordinate"
        )
