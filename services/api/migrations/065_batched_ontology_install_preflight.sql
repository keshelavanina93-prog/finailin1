BEGIN;

CREATE OR REPLACE FUNCTION public.g8_hidden_current_dependents_for_roots(root_resource_ids uuid[])
RETURNS TABLE(
    root_resource_id uuid,
    resource_id uuid,
    version_id uuid,
    object_type text,
    identity_key text,
    display_name text,
    access_entity text
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = off AS $$
DECLARE tenant uuid := NULLIF(current_setting('finai.tenant_id', true), '')::uuid;
DECLARE caller_entity text := current_setting('finai.entity_id', true);
DECLARE tenant_access boolean := coalesce(current_setting('finai.tenant_access', true), '') = 'true';
BEGIN
    IF tenant IS NULL OR EXISTS (
        SELECT 1
        FROM unnest(root_resource_ids) AS requested(resource_id)
        WHERE NOT EXISTS (
            SELECT 1 FROM public.canonical_identities i
            WHERE i.tenant_id = tenant AND i.resource_id = requested.resource_id
            AND (i.access_entity = '__PLATFORM__' OR tenant_access OR
                 (i.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__')
                  AND i.access_entity = caller_entity))
        )
    ) THEN
        RAISE EXCEPTION 'Impact root unavailable in authorized context' USING ERRCODE = '42501';
    END IF;

    RETURN QUERY
    SELECT d.target_resource_id, h.resource_id, h.version_id, v.object_type,
           i.identity_key, v.display_name, h.access_entity
    FROM public.resource_dependencies d
    JOIN public.resource_heads h
      ON h.tenant_id = d.tenant_id AND h.version_id = d.version_id
    JOIN public.resource_versions v
      ON v.tenant_id = h.tenant_id AND v.version_id = h.version_id
    JOIN public.canonical_identities i
      ON i.tenant_id = h.tenant_id AND i.resource_id = h.resource_id
    WHERE d.tenant_id = tenant
      AND d.target_resource_id = ANY(root_resource_ids)
      AND v.authority_state = 'APPROVED'
      AND (
          NOT public.g8_can_read_version(tenant, h.version_id)
          OR NOT (h.access_entity = '__PLATFORM__' OR tenant_access OR
                  (h.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__')
                   AND h.access_entity = caller_entity))
      )
    ORDER BY d.target_resource_id, i.identity_key, h.version_id;
END $$;

REVOKE ALL ON FUNCTION public.g8_hidden_current_dependents_for_roots(uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_hidden_current_dependents_for_roots(uuid[]) TO finai_runtime;

INSERT INTO schema_migrations VALUES(65);
COMMIT;
