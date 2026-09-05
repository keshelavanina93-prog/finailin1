import json
from calendar import monthrange
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resources import (
    CanonicalResource,
    ProposalDetail,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection

HEAD_SELECT = (
    "SELECT v.*,i.identity_key FROM resource_heads h JOIN "
    "resource_versions v USING(tenant_id,resource_id,version_id) "
    "JOIN canonical_identities i USING(tenant_id,resource_id) "
)


@contextmanager
def resource_connection(principal: Principal) -> Iterator[psycopg.Connection[Any]]:
    with connection(principal.scope) as conn:
        conn.execute(
            (
                "SELECT "
                "set_config('finai.entity_id',%s,true),set_config('finai.tena"
                "nt_access',%s,true)"
            ),
            (
                principal.scope.legal_entity_id,
                "true" if "ontology_admin" in principal.permissions else "false",
            ),
        )
        yield conn


def _get(conn: psycopg.Connection[Any], tenant: UUID, resource_id: UUID) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND h.resource_id=%s", (tenant, resource_id)
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Canonical resource not found in authorized context")
    return row


def catalog(principal: Principal) -> list[CanonicalResource]:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            HEAD_SELECT
            + (
                "WHERE h.tenant_id=%s AND v.object_type IN "
                "('SchemaDefinition','SemanticContract','LinkType') ORDER BY "
                "v.object_type,v.display_name"
            ),
            (principal.scope.tenant_id,),
        ).fetchall()
        return [CanonicalResource.model_validate(row) for row in rows]


def list_resources(
    principal: Principal,
    object_type: str | None,
    search: str,
    offset: int,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> list[CanonicalResource]:
    valid_at, known_at = valid_at or datetime.now(UTC), known_at or datetime.now(UTC)
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) "
            "v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) WHERE v.tenant_id=%s "
            "AND v.system_from<=%s AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) current "
            "WHERE authority_state<>'REVOKED' AND (%s::text IS NULL OR object_type=%s) "
            "AND position(lower(%s) in lower(display_name || ' ' || identity_key))>0 "
            "ORDER BY display_name,resource_id LIMIT 100 OFFSET %s",
            (
                principal.scope.tenant_id,
                known_at,
                valid_at,
                valid_at,
                object_type,
                object_type,
                search,
                offset,
            ),
        ).fetchall()
        return [CanonicalResource.model_validate(row) for row in rows]


def get_resource(principal: Principal, resource_id: UUID) -> dict[str, Any]:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        current = CanonicalResource.model_validate(
            _get(conn, principal.scope.tenant_id, resource_id)
        )
        versions = cursor.execute(
            (
                "SELECT v.*,i.identity_key FROM resource_versions v JOIN "
                "canonical_identities i USING(tenant_id,resource_id) WHERE "
                "v.tenant_id=%s AND v.resource_id=%s ORDER BY system_from "
                "DESC"
            ),
            (principal.scope.tenant_id, resource_id),
        ).fetchall()
        dependents = cursor.execute(
            (
                "SELECT "
                "d.relation,v.resource_id,v.version_id,v.display_name,v.objec"
                "t_type FROM resource_dependencies d JOIN resource_versions v "
                "ON d.tenant_id=v.tenant_id AND d.version_id=v.version_id "
                "WHERE d.tenant_id=%s AND d.target_resource_id=%s ORDER BY "
                "v.system_from DESC LIMIT 100"
            ),
            (principal.scope.tenant_id, resource_id),
        ).fetchall()
        return {
            "resource": current.model_dump(mode="json"),
            "versions": [
                CanonicalResource.model_validate(row).model_dump(mode="json") for row in versions
            ],
            "dependents": dependents,
        }


def _check_scalar(kind: str, value: Any) -> bool:
    if kind in ("text", "identifier"):
        return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000
    if kind == "integer":
        return type(value) is int
    if kind == "boolean":
        return type(value) is bool
    if kind == "reference":
        try:
            UUID(str(value))
            return isinstance(value, str)
        except ValueError:
            return False
    if kind in ("date", "datetime"):
        try:
            parsed = (
                datetime.fromisoformat(value) if kind == "datetime" else date.fromisoformat(value)
            )
            return kind == "date" or (isinstance(parsed, datetime) and parsed.tzinfo is not None)
        except (ValueError, TypeError):
            return False
    if kind == "decimal":
        try:
            return isinstance(value, str) and Decimal(value).is_finite() and len(value) <= 50
        except InvalidOperation:
            return False
    if kind in ("money", "quantity"):
        dimension = "currency_id" if kind == "money" else "unit"
        return (
            isinstance(value, dict)
            and set(value) == {"amount", dimension}
            and _check_scalar("decimal", value["amount"])
            and _check_scalar("reference" if kind == "money" else "identifier", value[dimension])
        )
    return False


def _validate(
    conn: psycopg.Connection[Any], principal: Principal, proposal: ResourceProposal
) -> dict[str, Any]:
    tenant = principal.scope.tenant_id
    if (
        proposal.access_entity != principal.scope.legal_entity_id
        and "ontology_admin" not in principal.permissions
    ):
        raise WorkspaceError(403, "Tenant-wide ontology administration permission required")
    mutations = {str(item.resource_id): item for item in proposal.mutations}
    resolved: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[dict[str, str]]] = {key: [] for key in mutations}
    external_heads: dict[str, str] = {}
    schema_versions: dict[str, str | None] = {}
    impact: list[dict[str, Any]] = []

    def target(identifier: str, source: str, relation: str) -> dict[str, Any]:
        if identifier in mutations:
            item = mutations[identifier]
            result = {
                **item.model_dump(mode="json"),
                "version_id": str(uuid5(proposal.proposal_id, identifier)),
                "access_entity": proposal.access_entity,
            }
        else:
            if identifier not in resolved:
                resolved[identifier] = _get(conn, tenant, UUID(identifier))
            result = resolved[identifier]
            external_heads[identifier] = str(result["version_id"])
        if result["authority_state"] != "APPROVED":
            raise WorkspaceError(409, "Dependency is revoked")
        if (
            result["access_entity"] not in (proposal.access_entity, "__PLATFORM__")
            and proposal.access_entity != "__TENANT__"
        ):
            raise WorkspaceError(
                403, "A resource cannot discard a dependency's entity access boundary"
            )
        dependencies[source].append(
            {
                "resource_id": identifier,
                "version_id": str(result["version_id"]),
                "relation": relation,
            }
        )
        return result

    with conn.cursor(row_factory=dict_row) as cursor:
        schemas = cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='SchemaDefinition'", (tenant,)
        ).fetchall()
    schema_by_name = {row["identity_key"]: str(row["resource_id"]) for row in schemas}
    schema_by_name.update(
        {
            item.identity_key: str(item.resource_id)
            for item in proposal.mutations
            if item.object_type == "SchemaDefinition"
        }
    )
    meta_types = {"SchemaDefinition", "SemanticContract", "LinkType"}
    for identifier, item in mutations.items():
        if item.object_type in meta_types and proposal.access_entity != "__PLATFORM__":
            raise WorkspaceError(
                403, "Schema, semantic and link definitions belong to the shared platform registry"
            )
        if proposal.access_entity == "__PLATFORM__" and item.object_type not in meta_types:
            raise WorkspaceError(403, "Enterprise facts cannot use platform-public policy")
        with conn.cursor(row_factory=dict_row) as cursor:
            previous = cursor.execute(
                HEAD_SELECT + "WHERE h.tenant_id=%s AND h.resource_id=%s",
                (tenant, item.resource_id),
            ).fetchone()
        actual = str(previous["version_id"]) if previous else None
        if actual != (str(item.expected_version_id) if item.expected_version_id else None):
            raise WorkspaceError(
                409, f"{item.display_name}: accepted version changed; refresh proposal"
            )
        if previous and (
            previous["object_type"] != item.object_type
            or previous["identity_key"] != item.identity_key
            or previous["access_entity"] != proposal.access_entity
        ):
            raise WorkspaceError(
                409, "Canonical type, identity key and access boundary cannot be overwritten"
            )
        schema_versions[identifier] = None
        if item.object_type == "SchemaDefinition":
            fields = item.attributes.get("fields")
            if not isinstance(fields, dict) or not fields:
                raise WorkspaceError(422, "Schema needs explicit stable fields")
            field_ids = []
            for name, spec in fields.items():
                if not isinstance(spec, dict) or not all(
                    key in spec for key in ("field_id", "semantic_id", "kind", "required")
                ):
                    raise WorkspaceError(422, f"Incomplete field definition: {name}")
                if (
                    type(spec["required"]) is not bool
                    or type(spec.get("deprecated", False)) is not bool
                ):
                    raise WorkspaceError(422, "Field requirement and deprecation must be booleans")
                UUID(spec["field_id"])
                field_ids.append(spec["field_id"])
                semantic = target(spec["semantic_id"], identifier, f"SEMANTIC:{name}")
                if (
                    semantic["object_type"] != "SemanticContract"
                    or semantic["attributes"]["kind"] != spec["kind"]
                ):
                    raise WorkspaceError(422, f"Field {name} does not match its semantic contract")
            if len(field_ids) != len(set(field_ids)):
                raise WorkspaceError(422, "Field identities must be unique within a schema")
            if previous:
                old = previous["attributes"]["fields"]
                breaking = [
                    name
                    for name, spec in old.items()
                    if name not in fields
                    or any(
                        fields[name].get(k) != spec.get(k)
                        for k in ("field_id", "semantic_id", "kind", "target_type")
                    )
                    or (not spec["required"] and fields[name]["required"])
                ]
                breaking += [
                    name for name, spec in fields.items() if name not in old and spec["required"]
                ]
                if breaking:
                    raise WorkspaceError(
                        409,
                        "Incompatible schema evolution requires an explicit migration change set: "
                        + ", ".join(breaking),
                    )
        elif item.object_type == "SemanticContract":
            if item.attributes.get("kind") not in (
                "text",
                "identifier",
                "integer",
                "decimal",
                "money",
                "quantity",
                "reference",
                "date",
                "datetime",
                "boolean",
            ):
                raise WorkspaceError(422, "Unknown semantic value kind")
            if previous and previous["attributes"].get("kind") != item.attributes["kind"]:
                raise WorkspaceError(409, "A semantic identity cannot change its value kind")
        elif item.object_type == "LinkType":
            if not all(
                isinstance(item.attributes.get(key), list) and item.attributes[key]
                for key in ("sources", "targets")
            ):
                raise WorkspaceError(422, "Link types need explicit endpoint types")
        else:
            schema_id = schema_by_name.get(item.object_type)
            if not schema_id:
                raise WorkspaceError(422, f"No canonical schema registered for {item.object_type}")
            schema = target(schema_id, identifier, "USES_SCHEMA")
            schema_versions[identifier] = str(schema["version_id"])
            fields = schema["attributes"]["fields"]
            if not schema["attributes"].get("additional_fields", False) and set(
                item.attributes
            ) - set(fields):
                raise WorkspaceError(
                    422, f"{item.display_name}: undeclared fields require a schema proposal"
                )
            for name, spec in fields.items():
                if name not in item.attributes:
                    if spec["required"]:
                        raise WorkspaceError(422, f"{item.display_name}: missing {name}")
                    continue
                value = item.attributes[name]
                if not _check_scalar(spec["kind"], value):
                    raise WorkspaceError(
                        422, f"{item.display_name}: invalid {name} ({spec['kind']})"
                    )
                if spec["kind"] == "reference":
                    ref = target(value, identifier, f"FIELD:{name}")
                    if spec.get("target_type") not in (None, "*", ref["object_type"]):
                        raise WorkspaceError(422, f"{name} must reference {spec['target_type']}")
                if spec["kind"] == "money":
                    currency = target(value["currency_id"], identifier, f"MONEY:{name}")
                    if currency["object_type"] != "Currency":
                        raise WorkspaceError(422, "Money requires a canonical Currency")
            if (
                item.object_type == "FiscalPeriod"
                and item.attributes["ends_on"] < item.attributes["starts_on"]
            ):
                raise WorkspaceError(422, "Fiscal period end cannot precede its start")
            if item.object_type == "Currency" and (
                len(item.attributes["code"]) != 3
                or not item.attributes["code"].isalpha()
                or not item.attributes["code"].isupper()
            ):
                raise WorkspaceError(422, "Currency code must contain three uppercase letters")
            if item.object_type == "Ledger":
                chart = target(item.attributes["chart_id"], identifier, "LEDGER_CHART")
                if chart["attributes"]["legal_entity_id"] != item.attributes["legal_entity_id"]:
                    raise WorkspaceError(
                        422, "Ledger and chart must belong to the same canonical legal entity"
                    )
            if item.object_type == "Relationship":
                relation = target(item.attributes["relation_id"], identifier, "LINK_TYPE")
                source = target(item.attributes["source_id"], identifier, "SOURCE")
                destination = target(item.attributes["target_id"], identifier, "TARGET")
                for key, node in (("sources", source), ("targets", destination)):
                    allowed = relation["attributes"][key]
                    if "*" not in allowed and node["object_type"] not in allowed:
                        raise WorkspaceError(
                            422,
                            f"{relation['display_name']}: invalid {key} type {node['object_type']}",
                        )
            if item.object_type == "IdentityResolution":
                source = target(item.attributes["source_id"], identifier, "IDENTITY_SOURCE")
                destination = target(item.attributes["target_id"], identifier, "IDENTITY_TARGET")
                if (
                    source["object_type"] != destination["object_type"]
                    or item.attributes["source_id"] == item.attributes["target_id"]
                ):
                    raise WorkspaceError(
                        422,
                        (
                            "Identity merge requires two different resources of the same "
                            "canonical type"
                        ),
                    )
                if item.identity_key != f"identity:{item.attributes['source_id']}":
                    raise WorkspaceError(
                        422, "Identity decision key must be stable for its source identity"
                    )
            if item.object_type == "Alias":
                ref = target(item.attributes["target_id"], identifier, "ALIAS_TARGET")
                expected = json.dumps(
                    [
                        item.attributes["source_system"],
                        ref["object_type"],
                        item.attributes["external_id"],
                    ],
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                if item.identity_key != "alias:" + sha256(expected.encode()).hexdigest():
                    raise WorkspaceError(
                        422,
                        "Alias key must be the canonical source-system/type/identifier fingerprint",
                    )
            if item.object_type == "SemanticBinding":
                source_schema = target(
                    item.attributes["source_schema_id"], identifier, "SOURCE_SCHEMA"
                )
                field = source_schema["attributes"]["fields"].get(item.attributes["source_field"])
                if not field or field["semantic_id"] != item.attributes["semantic_id"]:
                    raise WorkspaceError(
                        422, "Source field must bind the same versioned semantic contract"
                    )
            if item.object_type == "ContextBinding":
                if item.attributes["source_scope_key"] != canonical_sha256(principal.scope):
                    raise WorkspaceError(
                        422,
                        "Context binding must match the reviewing identity's exact source scope",
                    )
                currency = target(item.attributes["currency_id"], identifier, "CONTEXT_CURRENCY")
                if currency["attributes"]["code"] != principal.scope.currency:
                    raise WorkspaceError(422, "Canonical currency differs from the source scope")
                ledger = target(item.attributes["ledger_id"], identifier, "CONTEXT_LEDGER")
                period = target(item.attributes["period_id"], identifier, "CONTEXT_PERIOD")
                year, month = map(int, principal.scope.period.split("-"))
                if date.fromisoformat(period["attributes"]["starts_on"]) > date(
                    year, month, 1
                ) or date.fromisoformat(period["attributes"]["ends_on"]) < date(
                    year, month, monthrange(year, month)[1]
                ):
                    raise WorkspaceError(
                        422, "Canonical fiscal period does not contain the complete source period"
                    )
                if (
                    ledger["attributes"]["legal_entity_id"] != item.attributes["legal_entity_id"]
                    or ledger["attributes"]["calendar_id"] != period["attributes"]["calendar_id"]
                    or ledger["attributes"]["currency_id"] != item.attributes["currency_id"]
                ):
                    raise WorkspaceError(
                        422,
                        (
                            "Context entity, calendar, period and currency must agree "
                            "with the canonical ledger"
                        ),
                    )
                if item.identity_key != "context:" + item.attributes["source_scope_key"]:
                    raise WorkspaceError(
                        422, "Context binding identity must be stable for its source scope"
                    )
            if item.evidence_class == "SOURCE_BOUND":
                if item.object_type == "SourceEvidence":
                    retained = conn.execute(
                        (
                            "SELECT 1 FROM hydration_runs WHERE tenant_id=%s AND "
                            "source_sha256=%s AND exact_scope->>'legal_entity_id'=%s "
                            "LIMIT 1"
                        ),
                        (tenant, item.attributes["sha256"], proposal.access_entity),
                    ).fetchone()
                    if not retained:
                        raise WorkspaceError(
                            409, "SourceEvidence hash is not retained in this entity scope"
                        )
                elif "evidence_id" not in item.attributes:
                    raise WorkspaceError(
                        409, "Source-bound objects require a canonical evidence reference"
                    )
                else:
                    evidence = target(item.attributes["evidence_id"], identifier, "SOURCE_EVIDENCE")
                    if evidence["evidence_class"] != "SOURCE_BOUND":
                        raise WorkspaceError(
                            409, "Source-bound status requires retained source evidence"
                        )
        impact.append(
            {
                "resource_id": identifier,
                "name": item.display_name,
                "operation": "UPDATE" if previous else "CREATE",
                "fields_changed": sorted(
                    key
                    for key in set(item.attributes)
                    | set(previous["attributes"] if previous else {})
                    if item.attributes.get(key)
                    != (previous["attributes"].get(key) if previous else None)
                ),
            }
        )
    # Evaluate the whole proposed redirect graph, including existing decisions, to prohibit cycles.
    with conn.cursor(row_factory=dict_row) as cursor:
        existing_resolutions = cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='IdentityResolution'", (tenant,)
        ).fetchall()
    resolutions = {
        str(row["resource_id"]): row["attributes"]
        for row in existing_resolutions
        if row["authority_state"] == "APPROVED"
    }
    resolutions.update(
        {
            key: {
                **row.attributes,
                "active": row.attributes["active"] and row.authority_state == "APPROVED",
            }
            for key, row in mutations.items()
            if row.object_type == "IdentityResolution"
        }
    )
    redirects = {
        row["source_id"]: row["target_id"] for row in resolutions.values() if row["active"]
    }
    for origin in redirects:
        visited: set[str] = set()
        current = origin
        while current in redirects:
            if current in visited:
                raise WorkspaceError(409, "Identity merge would introduce a cycle")
            visited.add(current)
            current = redirects[current]
    return {
        "impact": impact,
        "dependency_heads": external_heads,
        "dependencies": dependencies,
        "schema_versions": schema_versions,
        "compatibility": "PASS",
        "identity_cycles": "NONE",
    }


def propose(principal: Principal, proposal: ResourceProposal) -> ProposalDetail:
    with resource_connection(principal) as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        request_hash = canonical_sha256(proposal)
        row = conn.execute(
            "SELECT request_hash FROM resource_proposals WHERE tenant_id=%s AND proposal_id=%s",
            (principal.scope.tenant_id, proposal.proposal_id),
        ).fetchone()
        if row and row[0] != request_hash:
            raise WorkspaceError(409, "Proposal ID was reused for different content")
        if row:
            return proposal_detail(principal, proposal.proposal_id)
        validation = _validate(conn, principal, proposal)
        conn.execute(
            (
                "INSERT INTO resource_proposals "
                "(tenant_id,proposal_id,access_entity,submitted_by,title,rati"
                "onale,request_hash,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING"
            ),
            (
                principal.scope.tenant_id,
                proposal.proposal_id,
                proposal.access_entity,
                principal.actor_id,
                proposal.title,
                proposal.rationale,
                request_hash,
                Jsonb({"request": proposal.model_dump(mode="json"), "validation": validation}),
            ),
        )
    return proposal_detail(principal, proposal.proposal_id)


def proposal_detail(principal: Principal, proposal_id: UUID) -> ProposalDetail:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            (
                "SELECT p.*,d.decision,d.reviewed_by,d.rationale AS "
                "review_rationale,d.recorded_at FROM resource_proposals p "
                "LEFT JOIN resource_decisions d USING(tenant_id,proposal_id) "
                "WHERE p.tenant_id=%s AND p.proposal_id=%s"
            ),
            (principal.scope.tenant_id, proposal_id),
        ).fetchone()
        if not row:
            raise WorkspaceError(404, "Resource proposal not found in authorized context")
        return ProposalDetail(
            proposal=ResourceProposal.model_validate(row["payload"]["request"]),
            submitted_by=row["submitted_by"],
            created_at=row["created_at"],
            decision=row["decision"],
            reviewed_by=row["reviewed_by"],
            review_rationale=row["review_rationale"],
            recorded_at=row["recorded_at"],
            validation=row["payload"]["validation"],
        )


def proposals(principal: Principal) -> list[dict[str, Any]]:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            (
                "SELECT "
                "p.proposal_id,p.title,p.rationale,p.submitted_by,p.created_a"
                "t,p.access_entity,coalesce(d.decision,'PENDING') AS decision "
                "FROM resource_proposals p LEFT JOIN resource_decisions d "
                "USING(tenant_id,proposal_id) WHERE p.tenant_id=%s ORDER BY "
                "p.created_at DESC LIMIT 100"
            ),
            (principal.scope.tenant_id,),
        ).fetchall()


def review(principal: Principal, proposal_id: UUID, request: ResourceReview) -> ProposalDetail:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        tenant = principal.scope.tenant_id
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"canonical:{tenant}",)
        )
        row = cursor.execute(
            "SELECT * FROM resource_proposals WHERE tenant_id=%s AND proposal_id=%s",
            (tenant, proposal_id),
        ).fetchone()
        if not row:
            raise WorkspaceError(404, "Proposal not found")
        existing = cursor.execute(
            "SELECT * FROM resource_decisions WHERE tenant_id=%s AND proposal_id=%s",
            (tenant, proposal_id),
        ).fetchone()
        if existing:
            if (
                existing["reviewed_by"] != principal.actor_id
                or existing["decision"] != request.decision
                or existing["rationale"] != request.rationale
            ):
                raise WorkspaceError(409, "Proposal already has an immutable decision")
        else:
            if row["submitted_by"] == principal.actor_id:
                raise WorkspaceError(403, "A separate identity steward must review this proposal")
            proposal = ResourceProposal.model_validate(row["payload"]["request"])
            if request.decision == "APPROVED":
                validation = _validate(conn, principal, proposal)
                if (
                    validation["dependency_heads"]
                    != row["payload"]["validation"]["dependency_heads"]
                ):
                    raise WorkspaceError(
                        409, "A reviewed dependency changed; submit a refreshed proposal"
                    )
            conn.execute(
                (
                    "INSERT INTO resource_decisions "
                    "(tenant_id,proposal_id,access_entity,decision,reviewed_by,ra"
                    "tionale) VALUES (%s,%s,%s,%s,%s,%s)"
                ),
                (
                    tenant,
                    proposal_id,
                    proposal.access_entity,
                    request.decision,
                    principal.actor_id,
                    request.rationale,
                ),
            )
            if request.decision == "APPROVED":
                for item in proposal.mutations:
                    version_id = uuid5(proposal_id, str(item.resource_id))
                    conn.execute(
                        (
                            "INSERT INTO canonical_identities "
                            "(tenant_id,resource_id,object_type,identity_key,access_entit"
                            "y) VALUES (%s,%s,%s,%s,%s) ON CONFLICT "
                            "(tenant_id,resource_id) DO NOTHING"
                        ),
                        (
                            tenant,
                            item.resource_id,
                            item.object_type,
                            item.identity_key,
                            proposal.access_entity,
                        ),
                    )
                    conn.execute(
                        (
                            "INSERT INTO resource_versions "
                            "(tenant_id,resource_id,version_id,access_entity,object_type,"
                            "display_name,schema_version_id,attributes,content_hash,valid"
                            "_from,valid_to,authority_state,evidence_class,proposal_id) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        ),
                        (
                            tenant,
                            item.resource_id,
                            version_id,
                            proposal.access_entity,
                            item.object_type,
                            item.display_name,
                            validation["schema_versions"][str(item.resource_id)],
                            Jsonb(item.attributes),
                            canonical_sha256(item),
                            item.valid_from,
                            item.valid_to,
                            item.authority_state,
                            item.evidence_class,
                            proposal_id,
                        ),
                    )
                    conn.execute(
                        (
                            "INSERT INTO resource_heads "
                            "(tenant_id,resource_id,version_id,access_entity) VALUES "
                            "(%s,%s,%s,%s) ON CONFLICT (tenant_id,resource_id) DO UPDATE "
                            "SET version_id=EXCLUDED.version_id"
                        ),
                        (tenant, item.resource_id, version_id, proposal.access_entity),
                    )
                    for dep in validation["dependencies"][str(item.resource_id)]:
                        conn.execute(
                            (
                                "INSERT INTO resource_dependencies "
                                "(tenant_id,version_id,target_resource_id,target_version_id,r"
                                "elation,access_entity) VALUES (%s,%s,%s,%s,%s,%s) ON "
                                "CONFLICT DO NOTHING"
                            ),
                            (
                                tenant,
                                version_id,
                                dep["resource_id"],
                                dep["version_id"],
                                dep["relation"],
                                proposal.access_entity,
                            ),
                        )
    return proposal_detail(principal, proposal_id)


def resolve_identity(
    principal: Principal, resource_id: UUID, known_at: datetime | None = None,
    valid_at: datetime | None = None,
) -> dict[str, Any]:
    chain: list[str] = []
    current = str(resource_id)
    known_at = known_at or datetime.now(UTC)
    valid_at = valid_at or known_at
    if known_at.tzinfo is None or valid_at.tzinfo is None:
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        for _ in range(64):
            node = cursor.execute(
                (
                    "SELECT v.*,i.identity_key FROM resource_versions v JOIN "
                    "canonical_identities i USING(tenant_id,resource_id) WHERE "
                    "v.tenant_id=%s AND v.resource_id=%s AND system_from<=%s AND "
                    "valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) ORDER "
                    "BY system_from DESC LIMIT 1"
                ),
                (principal.scope.tenant_id, UUID(current), known_at, valid_at, valid_at),
            ).fetchone()
            if not node or node["authority_state"] != "APPROVED":
                raise WorkspaceError(404, "No accepted identity exists at the requested time")
            chain.append(current)
            resolutions = cursor.execute(
                (
                    "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.* FROM "
                    "resource_versions v WHERE v.tenant_id=%s AND "
                    "v.object_type='IdentityResolution' AND v.system_from<=%s AND "
                    "v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
                    "ORDER BY v.resource_id,v.system_from DESC) latest WHERE "
                    "attributes->>'source_id'=%s AND attributes->>'active'='true' "
                    "AND authority_state='APPROVED'"
                ),
                (principal.scope.tenant_id, known_at, valid_at, valid_at, current),
            ).fetchall()
            if len(resolutions) > 1:
                raise WorkspaceError(409, "Conflicting identity resolutions at the requested time")
            row = resolutions[0] if resolutions else None
            if not row:
                return {
                    "canonical_id": current,
                    "display_name": node["display_name"],
                    "resolution_chain": chain,
                    "known_at": known_at,
                    "valid_at": valid_at,
                    "version_id": str(node["version_id"]),
                    "authority_state": node["authority_state"],
                }
            current = row["attributes"]["target_id"]
            if current in chain:
                raise WorkspaceError(409, "Identity resolution cycle detected")
    raise WorkspaceError(409, "Identity resolution exceeds bounded traversal depth")


def aliases(principal: Principal, source_system: str, external_id: str) -> list[dict[str, Any]]:
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            HEAD_SELECT
            + (
                "WHERE h.tenant_id=%s AND v.object_type='Alias' AND "
                "v.authority_state='APPROVED' AND "
                "v.attributes->>'source_system'=%s AND "
                "v.attributes->>'external_id'=%s"
            ),
            (principal.scope.tenant_id, source_system, external_id),
        ).fetchall()
        return [
            {
                "alias": CanonicalResource.model_validate(row).model_dump(mode="json"),
                "resolution": resolve_identity(principal, UUID(row["attributes"]["target_id"])),
            }
            for row in rows
        ]


def context_binding(principal: Principal) -> dict[str, Any]:
    scope_key = canonical_sha256(principal.scope)
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            HEAD_SELECT
            + (
                "WHERE h.tenant_id=%s AND v.object_type='ContextBinding' AND "
                "i.identity_key=%s AND v.authority_state='APPROVED' AND "
                "v.valid_from<=now() AND (v.valid_to IS NULL OR "
                "v.valid_to>now())"
            ),
            (principal.scope.tenant_id, "context:" + scope_key),
        ).fetchone()
        if not row:
            return {"source_scope_key": scope_key, "binding": None, "canonical_references": {}}
        references = cursor.execute(
            (
                "SELECT target_resource_id,target_version_id,relation FROM "
                "resource_dependencies WHERE tenant_id=%s AND version_id=%s "
                "AND relation LIKE 'FIELD:%'"
            ),
            (principal.scope.tenant_id, row["version_id"]),
        ).fetchall()
        return {
            "source_scope_key": scope_key,
            "binding": CanonicalResource.model_validate(row).model_dump(mode="json"),
            "canonical_references": {
                ref["relation"].removeprefix("FIELD:"): {
                    "resource_id": str(ref["target_resource_id"]),
                    "version_id": str(ref["target_version_id"]),
                }
                for ref in references
            },
        }
