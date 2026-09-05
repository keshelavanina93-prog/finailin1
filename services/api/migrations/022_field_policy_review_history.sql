BEGIN;
GRANT SELECT ON proposal_impact_snapshots TO finai_policy_reader;
CREATE OR REPLACE FUNCTION g8_can_read_proposal(tenant uuid, proposal uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE retained jsonb; item jsonb; schema_attributes jsonb; dependency jsonb; permissions jsonb;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 SELECT payload INTO retained FROM public.resource_proposals WHERE tenant_id=tenant AND proposal_id=proposal;
 IF retained IS NULL THEN RETURN false; END IF;
 permissions := coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb;
 FOR item IN SELECT value FROM jsonb_array_elements(retained->'request'->'mutations') LOOP
  IF item->>'expected_version_id' IS NOT NULL AND NOT public.g8_can_read_version(tenant,(item->>'expected_version_id')::uuid) THEN RETURN false; END IF;
  IF item->>'object_type' NOT IN ('SchemaDefinition','SemanticContract','LinkType') THEN
   SELECT value->'attributes' INTO schema_attributes FROM jsonb_array_elements(retained->'request'->'mutations')
    WHERE value->>'object_type'='SchemaDefinition' AND value->>'identity_key'=item->>'object_type';
   IF schema_attributes IS NULL THEN
    SELECT attributes INTO schema_attributes FROM public.resource_versions WHERE tenant_id=tenant
     AND version_id=(retained->'validation'->'schema_versions'->>(item->>'resource_id'))::uuid;
   END IF;
   IF schema_attributes IS NULL OR NOT public.g8_fields_readable(schema_attributes,item->'attributes',permissions) THEN RETURN false; END IF;
  END IF;
  FOR dependency IN SELECT value FROM jsonb_array_elements(coalesce(retained->'validation'->'dependencies'->(item->>'resource_id'),'[]'::jsonb)) LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(retained->'request'->'mutations') mutation
      WHERE mutation->>'resource_id'=dependency->>'resource_id')
    AND NOT public.g8_can_read_version(tenant,(dependency->>'version_id')::uuid) THEN RETURN false;
   END IF;
  END LOOP;
 END LOOP;
 FOR dependency IN SELECT value FROM jsonb_each(coalesce(retained->'request'->'restores_versions','{}'::jsonb)) LOOP
  IF NOT public.g8_can_read_version(tenant,(dependency#>>'{}')::uuid) THEN RETURN false; END IF;
 END LOOP;
 FOR dependency IN
  SELECT value FROM jsonb_array_elements(coalesce(retained->'validation'->'downstream_impact'->'affected','[]'::jsonb))
  UNION
  SELECT value FROM public.proposal_impact_snapshots p, LATERAL jsonb_array_elements(p.snapshot->'affected')
   WHERE p.tenant_id=tenant AND p.proposal_id=proposal
 LOOP
  IF dependency->>'state'='CURRENT' AND NOT public.g8_can_read_version(tenant,(dependency->>'version_id')::uuid) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.g8_has_hidden_current_dependents(root_resource_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = off AS $$
DECLARE tenant uuid := NULLIF(current_setting('finai.tenant_id', true), '')::uuid;
DECLARE caller_entity text := current_setting('finai.entity_id', true);
DECLARE tenant_access boolean := coalesce(current_setting('finai.tenant_access', true), '') = 'true';
BEGIN
    IF tenant IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.canonical_identities i
        WHERE i.tenant_id = tenant AND i.resource_id = root_resource_id
        AND (i.access_entity = '__PLATFORM__' OR tenant_access OR
             (i.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND i.access_entity = caller_entity))
    ) THEN
        RAISE EXCEPTION 'Impact root unavailable in authorized context' USING ERRCODE = '42501';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM public.resource_dependencies d
        JOIN public.resource_heads h ON h.tenant_id=d.tenant_id AND h.version_id=d.version_id
        JOIN public.resource_versions v ON v.tenant_id=h.tenant_id AND v.version_id=h.version_id
        WHERE d.tenant_id=tenant AND d.target_resource_id=root_resource_id
        AND v.authority_state='APPROVED'
        AND (NOT public.g8_can_read_version(tenant,v.version_id) OR NOT (h.access_entity='__PLATFORM__' OR tenant_access OR
            (h.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND h.access_entity=caller_entity)))
    );
END $$;
INSERT INTO schema_migrations VALUES(22);
COMMIT;

