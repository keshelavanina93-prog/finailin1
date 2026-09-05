"""Optional spatial field upgrade, preserving customized and historical definitions.
Run install-ontology.py first. No enterprise facts or geometry are installed here.
"""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions

grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
tenants = {UUID(grant.get("scope", grant)["tenant_id"]) for grant in grants.values()}
with psycopg.connect(
    os.environ["FINAI_MIGRATION_DATABASE_URL"], row_factory=dict_row
) as conn:
    for tenant in tenants:
        for definition in platform_definitions(tenant):
            if definition["object_type"] != "SchemaDefinition" or definition[
                "identity_key"
            ] not in (
                "Location",
                "Facility",
                "PipelineSegment",
                "LicensedServiceArea",
                "OperationalNetwork",
                "GasDistributionSystem",
            ):
                continue
            resource_id = canonical_id(
                tenant, "SchemaDefinition", definition["identity_key"]
            )
            current = conn.execute(
                "SELECT v.* FROM resource_heads h JOIN resource_versions v "
                "USING(tenant_id,resource_id,version_id) WHERE h.tenant_id=%s AND h.resource_id=%s "
                "FOR UPDATE",
                (tenant, resource_id),
            ).fetchone()
            if current is None or current["evidence_class"] != "PLATFORM_DEFINITION":
                continue
            attributes = dict(current["attributes"])
            fields = dict(attributes["fields"])
            additions = {
                key: value
                for key, value in definition["attributes"]["fields"].items()
                if key in {"geometry", "legal_entity_id", "spatial_import_id"}
                and key not in fields
            }
            if not additions:
                continue
            fields.update(additions)
            attributes.update(fields=fields, version=attributes.get("version", 1) + 1)
            version = uuid4()
            conn.execute(
                "INSERT INTO resource_versions (tenant_id,resource_id,version_id,"
                "access_entity,object_type,display_name,attributes,content_hash,valid_from,"
                "authority_state,evidence_class) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    tenant,
                    resource_id,
                    version,
                    current["access_entity"],
                    current["object_type"],
                    current["display_name"],
                    Jsonb(attributes),
                    sha256(json.dumps(attributes, sort_keys=True).encode()).hexdigest(),
                    datetime.now(UTC),
                    "APPROVED",
                    "PLATFORM_DEFINITION",
                ),
            )
            conn.execute(
                "UPDATE resource_heads SET version_id=%s WHERE tenant_id=%s AND resource_id=%s",
                (version, tenant, resource_id),
            )
            print("Added optional spatial fields to", definition["identity_key"])
