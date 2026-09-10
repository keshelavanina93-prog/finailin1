BEGIN;

-- restricted_read is the governed tenant-steward capability used for complete
-- dependency impact. Once present, field-level read checks no longer need to
-- recursively re-walk every retained dependency for each row in that graph.
CREATE OR REPLACE FUNCTION public.g8_can_read_version(tenant uuid, version uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE resource record; permissions jsonb; found_version boolean := false;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 permissions := coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb;
 IF permissions @> '["restricted_read"]'::jsonb THEN RETURN true; END IF;
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

ALTER FUNCTION public.g8_can_read_version(uuid,uuid) OWNER TO finai_policy_reader;
REVOKE ALL ON FUNCTION public.g8_can_read_version(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_can_read_version(uuid,uuid) TO finai_runtime,finai_policy_reader;

INSERT INTO schema_migrations VALUES(67);
COMMIT;
