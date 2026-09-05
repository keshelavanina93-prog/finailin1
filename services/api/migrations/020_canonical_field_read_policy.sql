BEGIN;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='finai_policy_reader') THEN
  CREATE ROLE finai_policy_reader NOLOGIN BYPASSRLS;
 END IF;
END $$;
GRANT USAGE,CREATE ON SCHEMA public TO finai_policy_reader;
GRANT SELECT ON resource_versions,resource_dependencies,resource_heads,resource_proposals TO finai_policy_reader;

CREATE FUNCTION g8_fields_readable(schema_attributes jsonb, properties jsonb, permissions jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE field record; needed jsonb;
BEGIN
 FOR field IN SELECT key,value FROM jsonb_each(coalesce(schema_attributes->'fields','{}'::jsonb)) LOOP
  IF properties ? field.key AND field.value ? 'read_permissions' THEN
   IF jsonb_typeof(field.value->'read_permissions') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   FOR needed IN SELECT value FROM jsonb_array_elements(field.value->'read_permissions') LOOP
    IF jsonb_typeof(needed)<>'string' OR NOT (permissions @> jsonb_build_array(needed)) THEN RETURN false; END IF;
   END LOOP;
  END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION g8_can_read_version(tenant uuid, version uuid) RETURNS boolean
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
    JOIN public.resource_versions v ON v.tenant_id=tenant AND v.version_id=l.version_id
    LEFT JOIN public.resource_versions s ON s.tenant_id=tenant AND s.version_id=v.schema_version_id
 LOOP
  found_version := true;
  IF NOT public.g8_fields_readable(resource.schema_attributes,resource.attributes,permissions) THEN RETURN false; END IF;
 END LOOP;
 RETURN found_version;
END $$;

CREATE FUNCTION g8_can_read_proposal(tenant uuid, proposal uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE retained jsonb; item jsonb; schema_attributes jsonb; dependency jsonb; permissions jsonb;
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
  FOR dependency IN SELECT value FROM jsonb_array_elements(coalesce(retained->'validation'->'dependencies'->(item->>'resource_id'),'[]'::jsonb)) LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(retained->'request'->'mutations') mutation
      WHERE mutation->>'resource_id'=dependency->>'resource_id')
    AND NOT public.g8_can_read_version(tenant,(dependency->>'version_id')::uuid) THEN RETURN false;
   END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;

ALTER FUNCTION g8_can_read_version(uuid,uuid) OWNER TO finai_policy_reader;
ALTER FUNCTION g8_can_read_proposal(uuid,uuid) OWNER TO finai_policy_reader;
REVOKE CREATE ON SCHEMA public FROM finai_policy_reader;
REVOKE ALL ON FUNCTION g8_can_read_version(uuid,uuid),g8_can_read_proposal(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION g8_can_read_version(uuid,uuid),g8_can_read_proposal(uuid,uuid) TO finai_runtime,finai_policy_reader;

DO $$ DECLARE target record; previous text; BEGIN
 FOR target IN SELECT * FROM (VALUES
  ('resource_versions','resource_access','public.g8_can_read_version(tenant_id,version_id)'),
  ('resource_heads','resource_access','public.g8_can_read_version(tenant_id,version_id)'),
  ('resource_dependencies','resource_access','public.g8_can_read_version(tenant_id,version_id)'),
  ('resource_proposals','resource_access','public.g8_can_read_proposal(tenant_id,proposal_id)'),
  ('resource_decisions','resource_access','public.g8_can_read_proposal(tenant_id,proposal_id)'),
  ('proposal_impact_snapshots','impact_snapshot_access','public.g8_can_read_proposal(tenant_id,proposal_id)'),
  ('resource_lifecycle_requests','lifecycle_access','public.g8_can_read_version(tenant_id,version_id)'),
  ('resource_lifecycle_events','lifecycle_access','public.g8_can_read_version(tenant_id,version_id)'),
  ('guarded_consumption_receipts','consumption_access','public.g8_can_read_version(tenant_id,consumer_version_id)'),
  ('retained_source_events','event_access','public.g8_can_read_version(tenant_id,stream_version_id)')
 ) AS policy(table_name,policy_name,predicate) LOOP
  SELECT qual INTO previous FROM pg_policies WHERE schemaname='public' AND tablename=target.table_name AND policyname=target.policy_name;
  IF previous IS NULL THEN RAISE EXCEPTION 'Missing governed policy: %.%',target.table_name,target.policy_name; END IF;
  EXECUTE format('ALTER POLICY %I ON public.%I USING ((%s) AND (%s))',target.policy_name,target.table_name,previous,target.predicate);
 END LOOP;
END $$;
INSERT INTO schema_migrations VALUES(20);
COMMIT;
