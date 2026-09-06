BEGIN;
-- Every lineage edge identifies one version by its tenant-scoped primary key.
-- Keep those lookups bounded: recursive cardinality estimates otherwise cause
-- a tenant-wide version scan for every visibility decision as real data grows.
-- LIMIT 1 is cardinality-preserving because both lookups use the unique key.
CREATE OR REPLACE FUNCTION g8_can_read_version(tenant uuid, version uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE resource record; permissions jsonb; found_version boolean := false;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 permissions := coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb;
 FOR resource IN
  WITH RECURSIVE lineage(version_id) AS (
   SELECT version UNION
   SELECT d.target_version_id FROM public.resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
   WHERE d.tenant_id=tenant
  ) SELECT v.attributes,s.attributes AS schema_attributes FROM lineage l
    JOIN LATERAL (SELECT attributes,schema_version_id FROM public.resource_versions
     WHERE tenant_id=tenant AND version_id=l.version_id LIMIT 1) v ON true
    LEFT JOIN LATERAL (SELECT attributes FROM public.resource_versions
     WHERE tenant_id=tenant AND version_id=v.schema_version_id LIMIT 1) s ON true
 LOOP
  found_version := true;
  IF NOT public.g8_fields_readable(resource.schema_attributes,resource.attributes,permissions) THEN RETURN false; END IF;
 END LOOP;
 RETURN found_version;
END $$;

CREATE OR REPLACE FUNCTION g8_can_read_proposal(tenant uuid, proposal uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE retained jsonb; item jsonb; schema_attributes jsonb; permissions jsonb;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 SELECT payload INTO retained FROM public.resource_proposals WHERE tenant_id=tenant AND proposal_id=proposal;
 IF retained IS NULL THEN RETURN false; END IF;
 permissions := coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb;
 FOR item IN SELECT value FROM jsonb_array_elements(retained->'request'->'mutations') LOOP
  IF item->>'object_type' NOT IN ('SchemaDefinition','SemanticContract','LinkType') THEN
   SELECT value->'attributes' INTO schema_attributes FROM jsonb_array_elements(retained->'request'->'mutations')
    WHERE value->>'object_type'='SchemaDefinition' AND value->>'identity_key'=item->>'object_type';
   IF schema_attributes IS NULL THEN
    SELECT attributes INTO schema_attributes FROM public.resource_versions WHERE tenant_id=tenant
     AND version_id=(retained->'validation'->'schema_versions'->>(item->>'resource_id'))::uuid;
   END IF;
   IF schema_attributes IS NULL OR NOT public.g8_fields_readable(schema_attributes,item->'attributes',permissions) THEN RETURN false; END IF;
  END IF;
 END LOOP;
 RETURN NOT EXISTS (
  WITH RECURSIVE mutations AS MATERIALIZED (
   SELECT value FROM jsonb_array_elements(retained->'request'->'mutations')
  ), required_versions AS (
   SELECT (value->>'expected_version_id')::uuid AS version_id FROM mutations
    WHERE value->>'expected_version_id' IS NOT NULL
   UNION
   SELECT (dependency->>'version_id')::uuid FROM mutations m,
    LATERAL jsonb_array_elements(coalesce(retained->'validation'->'dependencies'->(m.value->>'resource_id'),'[]'::jsonb)) dependency
    WHERE NOT EXISTS (SELECT 1 FROM mutations target WHERE target.value->>'resource_id'=dependency->>'resource_id')
   UNION
   SELECT (value#>>'{}')::uuid FROM jsonb_each(coalesce(retained->'request'->'restores_versions','{}'::jsonb))
   UNION
   SELECT (value->>'version_id')::uuid FROM jsonb_array_elements(coalesce(retained->'validation'->'downstream_impact'->'affected','[]'::jsonb))
    WHERE value->>'state'='CURRENT'
   UNION
   SELECT (value->>'version_id')::uuid FROM public.proposal_impact_snapshots p,
    LATERAL jsonb_array_elements(p.snapshot->'affected')
    WHERE p.tenant_id=tenant AND p.proposal_id=proposal AND value->>'state'='CURRENT'
  )
  , lineage(version_id) AS (
   SELECT version_id FROM required_versions
   UNION
   SELECT d.target_version_id FROM public.resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
    WHERE d.tenant_id=tenant
  )
  SELECT 1 FROM lineage l
   LEFT JOIN LATERAL (SELECT version_id,attributes,schema_version_id FROM public.resource_versions
    WHERE tenant_id=tenant AND version_id=l.version_id LIMIT 1) v ON true
   LEFT JOIN LATERAL (SELECT attributes FROM public.resource_versions
    WHERE tenant_id=tenant AND version_id=v.schema_version_id LIMIT 1) schema ON true
   WHERE v.version_id IS NULL OR NOT public.g8_fields_readable(schema.attributes,v.attributes,permissions)
 );
END $$;
INSERT INTO schema_migrations VALUES(31);
COMMIT;
