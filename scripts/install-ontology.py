"""Install immutable platform definitions; does not create company or financial facts."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from finai_api.domain.ontology_catalog import (
    CATALOG_NAMESPACE,
    canonical_id,
    platform_definitions,
)

grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
tenants = {UUID(grant.get("scope", grant)["tenant_id"]) for grant in grants.values()}
with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
    for tenant in tenants:
        for definition in platform_definitions(tenant):
            resource_id = canonical_id(
                tenant, definition["object_type"], definition["identity_key"]
            )
            version_id = uuid5(CATALOG_NAMESPACE, f"{resource_id}:platform-v1")
            digest = sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
            conn.execute(
                "INSERT INTO canonical_identities (tenant_id,resource_id,object_type,identity_key,access_entity) VALUES (%s,%s,%s,%s,'__PLATFORM__') ON CONFLICT DO NOTHING",
                (
                    tenant,
                    resource_id,
                    definition["object_type"],
                    definition["identity_key"],
                ),
            )
            conn.execute(
                "INSERT INTO resource_versions (tenant_id,resource_id,version_id,access_entity,object_type,display_name,attributes,content_hash,valid_from,authority_state,evidence_class) VALUES (%s,%s,%s,'__PLATFORM__',%s,%s,%s,%s,%s,'APPROVED','PLATFORM_DEFINITION') ON CONFLICT DO NOTHING",
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
            conn.execute(
                "INSERT INTO resource_heads (tenant_id,resource_id,version_id,access_entity) VALUES (%s,%s,%s,'__PLATFORM__') ON CONFLICT DO NOTHING",
                (tenant, resource_id, version_id),
            )
        print(
            f"Installed {len(platform_definitions(tenant))} versioned platform definitions for configured tenant."
        )
