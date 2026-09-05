BEGIN;
-- The only privileged output is a boolean for a caller-visible root in its current tenant.
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
        AND (i.access_entity = caller_entity OR i.access_entity = '__PLATFORM__' OR tenant_access)
    ) THEN
        RAISE EXCEPTION 'Impact root unavailable in authorized context' USING ERRCODE = '42501';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM public.resource_dependencies d
        JOIN public.resource_heads h ON h.tenant_id=d.tenant_id AND h.version_id=d.version_id
        JOIN public.resource_versions v ON v.tenant_id=h.tenant_id AND v.version_id=h.version_id
        WHERE d.tenant_id=tenant AND d.target_resource_id=root_resource_id
        AND v.authority_state='APPROVED'
        AND NOT (h.access_entity=caller_entity OR h.access_entity='__PLATFORM__' OR tenant_access)
    );
END $$;
REVOKE ALL ON FUNCTION public.g8_has_hidden_current_dependents(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_has_hidden_current_dependents(uuid) TO finai_runtime;
CREATE TABLE public.proposal_impact_snapshots (
    tenant_id uuid NOT NULL, proposal_id uuid NOT NULL, access_entity text NOT NULL,
    snapshot jsonb NOT NULL, fingerprint text NOT NULL,
    PRIMARY KEY (tenant_id, proposal_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES public.resource_proposals (tenant_id, proposal_id)
);
ALTER TABLE public.proposal_impact_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.proposal_impact_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY impact_snapshot_access ON public.proposal_impact_snapshots
USING (tenant_id::text=current_setting('finai.tenant_id',true) AND (
    current_setting('finai.tenant_access',true)='true' OR
    (access_entity<>'__TENANT_RESTRICTED__' AND
     (access_entity=current_setting('finai.entity_id',true) OR access_entity='__PLATFORM__'))))
WITH CHECK (tenant_id::text=current_setting('finai.tenant_id',true) AND (
    current_setting('finai.tenant_access',true)='true' OR
    (access_entity<>'__TENANT_RESTRICTED__' AND access_entity=current_setting('finai.entity_id',true))));
GRANT SELECT, INSERT ON public.proposal_impact_snapshots TO finai_runtime;
CREATE TRIGGER immutable_impact_snapshot BEFORE UPDATE OR DELETE OR TRUNCATE
ON public.proposal_impact_snapshots FOR EACH STATEMENT EXECUTE FUNCTION public.deny_evidence_mutation();
INSERT INTO schema_migrations VALUES (7);
COMMIT;
