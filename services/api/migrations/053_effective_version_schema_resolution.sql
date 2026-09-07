BEGIN;
-- Restricted-search-path guards call this shared helper. Resolve its table
-- explicitly without changing its effective-version ordering or RLS behavior.
CREATE OR REPLACE FUNCTION public.g8_effective_version_id(tenant uuid, resource uuid, at_time timestamptz)
RETURNS uuid LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $$
 SELECT version_id FROM public.resource_versions
 WHERE tenant_id=tenant AND resource_id=resource AND system_from<=at_time
 AND valid_from<=at_time AND (valid_to IS NULL OR valid_to>at_time)
 ORDER BY system_from DESC,version_id LIMIT 1
$$;
INSERT INTO schema_migrations VALUES(53);
COMMIT;
