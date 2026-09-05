BEGIN;
-- Evaluate each referenced version once per proposal read. Keep the same tenant,
-- field, restoration and historical impact checks as migration 022.
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
  WITH mutations AS MATERIALIZED (
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
  SELECT 1 FROM required_versions WHERE NOT public.g8_can_read_version(tenant,version_id)
 );
END $$;
INSERT INTO schema_migrations VALUES(24);
COMMIT;
