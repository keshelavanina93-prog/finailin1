"""Bootstrap new platform identities with exact semantics; never rewrite existing history."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid5

import psycopg
from finai_api.domain.ontology_catalog import (
    CATALOG_NAMESPACE,
    canonical_id,
    platform_definitions,
)
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def seed_version(resource_id):
    return uuid5(CATALOG_NAMESPACE, f"{resource_id}:platform-v1")


def install(conn, tenant, definitions):
    """The caller owns the transaction: identities, versions and edges commit together."""
    # Serialize with the existing resource/lifecycle publication boundary. A seed
    # cannot be withdrawn between validating its current use and committing its consumer.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"canonical:{tenant}",),
    )
    created, existing, schemas = [], [], []
    with conn.cursor(row_factory=dict_row) as cursor:
        for definition in definitions:
            resource_id = canonical_id(
                tenant, definition["object_type"], definition["identity_key"]
            )
            version_id = seed_version(resource_id)
            identity = cursor.execute(
                "INSERT INTO canonical_identities "
                "(tenant_id,resource_id,object_type,identity_key,access_entity) "
                "VALUES (%s,%s,%s,%s,'__PLATFORM__') ON CONFLICT DO NOTHING "
                "RETURNING resource_id",
                (
                    tenant,
                    resource_id,
                    definition["object_type"],
                    definition["identity_key"],
                ),
            ).fetchone()
            if identity is None:
                # Existing resources may have reviewed successors or no current
                # head. Bootstrap never restores or changes their history.
                existing.append(str(resource_id))
                continue
            digest = sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
            cursor.execute(
                "INSERT INTO resource_versions "
                "(tenant_id,resource_id,version_id,access_entity,object_type,display_name,"
                "attributes,content_hash,valid_from,authority_state,evidence_class) "
                "VALUES (%s,%s,%s,'__PLATFORM__',%s,%s,%s,%s,%s,'APPROVED',"
                "'PLATFORM_DEFINITION')",
                (
                    tenant,
                    resource_id,
                    version_id,
                    definition["object_type"],
                    definition["display_name"],
                    Jsonb(definition["attributes"]),
                    digest,
                    datetime(1970, 1, 1, tzinfo=UTC),
                ),
            )
            cursor.execute(
                "INSERT INTO resource_heads (tenant_id,resource_id,version_id,access_entity) "
                "VALUES (%s,%s,%s,'__PLATFORM__')",
                (tenant, resource_id, version_id),
            )
            created.append(str(resource_id))
            if definition["object_type"] == "SchemaDefinition":
                schemas.append((version_id, definition))
        edges = 0
        for schema_version, schema in schemas:
            for name, spec in schema["attributes"]["fields"].items():
                semantic_id = UUID(str(spec["semantic_id"]))
                semantic_version = seed_version(semantic_id)
                semantic = cursor.execute(
                    "SELECT object_type,attributes,authority_state,access_entity "
                    "FROM resource_versions WHERE tenant_id=%s AND resource_id=%s "
                    "AND version_id=%s",
                    (tenant, semantic_id, semantic_version),
                ).fetchone()
                if (
                    semantic is None
                    or semantic["object_type"] != "SemanticContract"
                    or semantic["attributes"].get("kind") != spec["kind"]
                    or semantic["authority_state"] != "APPROVED"
                    or semantic["access_entity"] != "__PLATFORM__"
                ):
                    raise ValueError(
                        f"{schema['identity_key']}.{name}: exact bootstrap semantics are "
                        "unavailable or incompatible; use reviewed platform publication"
                    )
                cursor.execute(
                    "INSERT INTO resource_dependencies "
                    "(tenant_id,version_id,target_resource_id,target_version_id,relation,"
                    "access_entity) VALUES (%s,%s,%s,%s,%s,'__PLATFORM__')",
                    (
                        tenant,
                        schema_version,
                        semantic_id,
                        semantic_version,
                        "SEMANTIC:" + name,
                    ),
                )
                edges += 1
            try:
                # Exact pins remain exact. This shared guard also checks temporal
                # successors, lifecycle withdrawal and availability; never substitute a head.
                upstream_authority(cursor, tenant, schema_version)
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                raise ValueError(
                    f"{schema['identity_key']}: exact bootstrap semantics are unavailable "
                    f"for current use; use reviewed platform publication ({exc.detail})"
                ) from exc
    return {
        "created_identities": created,
        "existing_identities_unchanged": existing,
        "exact_semantic_edges_created": edges,
        "historical_schema_repair_performed": False,
    }


def main():
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    tenants = {
        UUID(grant.get("scope", grant)["tenant_id"]) for grant in grants.values()
    }
    results = []
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
        for tenant in sorted(tenants, key=str):
            result = install(conn, tenant, platform_definitions(tenant))
            results.append({"tenant_id": str(tenant), **result})
    for result in results:
        print(json.dumps({"state": "COMMITTED", **result}))


if __name__ == "__main__":
    main()
