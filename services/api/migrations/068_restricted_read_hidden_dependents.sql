BEGIN;

CREATE OR REPLACE FUNCTION public.g8_has_hidden_current_dependents(root_resource_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = off AS $$
DECLARE tenant uuid := NULLIF(current_setting('finai.tenant_id', true), '')::uuid;
DECLARE caller_entity text := current_setting('finai.entity_id', true);
DECLARE tenant_access boolean := coalesce(current_setting('finai.tenant_access', true), '') = 'true';
DECLARE permissions jsonb := coalesce(nullif(current_setting('finai.read_permissions', true), ''), '[]')::jsonb;
BEGIN
    IF tenant IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.canonical_identities i
        WHERE i.tenant_id = tenant AND i.resource_id = root_resource_id
        AND (i.access_entity = '__PLATFORM__' OR tenant_access OR
             (i.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__')
              AND i.access_entity = caller_entity))
    ) THEN
        RAISE EXCEPTION 'Impact root unavailable in authorized context' USING ERRCODE = '42501';
    END IF;
    -- The reviewed steward capability authorizes the complete hidden graph.
    IF permissions @> '["restricted_read"]'::jsonb THEN
        RETURN false;
    END IF;
    RETURN EXISTS (
        SELECT 1
        FROM public.resource_dependencies d
        JOIN public.resource_heads h ON h.tenant_id = d.tenant_id AND h.version_id = d.version_id
        JOIN public.resource_versions v ON v.tenant_id = h.tenant_id AND v.version_id = h.version_id
        WHERE d.tenant_id = tenant AND d.target_resource_id = root_resource_id
          AND v.authority_state = 'APPROVED'
          AND (NOT public.g8_can_read_version(tenant, v.version_id)
               OR NOT (h.access_entity = '__PLATFORM__' OR tenant_access OR
                       (h.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__')
                        AND h.access_entity = caller_entity)))
    );
END $$;

REVOKE ALL ON FUNCTION public.g8_has_hidden_current_dependents(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_has_hidden_current_dependents(uuid) TO finai_runtime;

INSERT INTO schema_migrations VALUES(68);
COMMIT;
