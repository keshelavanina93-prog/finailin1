BEGIN;
CREATE FUNCTION g8_can_read_identity(tenant uuid, resource uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE version uuid;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 SELECT version_id INTO version FROM public.resource_heads WHERE tenant_id=tenant AND resource_id=resource;
 RETURN version IS NULL OR public.g8_can_read_version(tenant,version);
END $$;
GRANT CREATE ON SCHEMA public TO finai_policy_reader;
ALTER FUNCTION g8_can_read_identity(uuid,uuid) OWNER TO finai_policy_reader;
REVOKE CREATE ON SCHEMA public FROM finai_policy_reader;
REVOKE ALL ON FUNCTION g8_can_read_identity(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION g8_can_read_identity(uuid,uuid) TO finai_runtime,finai_policy_reader;
DO $$ DECLARE previous text; BEGIN
 SELECT qual INTO previous FROM pg_policies WHERE schemaname='public' AND tablename='canonical_identities' AND policyname='resource_access';
 EXECUTE format('ALTER POLICY resource_access ON canonical_identities USING ((%s) AND public.g8_can_read_identity(tenant_id,resource_id))',previous);
 SELECT qual INTO previous FROM pg_policies WHERE schemaname='public' AND tablename='resource_lifecycle_decisions' AND policyname='lifecycle_access';
 EXECUTE format('ALTER POLICY lifecycle_access ON resource_lifecycle_decisions USING ((%s) AND EXISTS(SELECT 1 FROM resource_lifecycle_requests r WHERE r.tenant_id=resource_lifecycle_decisions.tenant_id AND r.request_id=resource_lifecycle_decisions.request_id))',previous);
END $$;
INSERT INTO schema_migrations VALUES(21);
COMMIT;
