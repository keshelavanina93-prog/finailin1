BEGIN;
-- Reserved tenant envelopes cannot be acquired by choosing their text as an entity credential.
DO $$ DECLARE target text; BEGIN
    FOREACH target IN ARRAY ARRAY['canonical_identities','resource_proposals','resource_decisions',
        'resource_versions','resource_heads','resource_dependencies'] LOOP
        EXECUTE format('DROP POLICY resource_access ON public.%I', target);
        EXECUTE format('CREATE POLICY resource_access ON public.%I USING (
            tenant_id::text=current_setting(''finai.tenant_id'',true) AND (
                access_entity=''__PLATFORM__'' OR current_setting(''finai.tenant_access'',true)=''true'' OR
                (access_entity NOT IN (''__TENANT__'',''__TENANT_RESTRICTED__'') AND
                 access_entity=current_setting(''finai.entity_id'',true))))
            WITH CHECK (tenant_id::text=current_setting(''finai.tenant_id'',true) AND (
                current_setting(''finai.tenant_access'',true)=''true'' OR
                (access_entity NOT IN (''__TENANT__'',''__TENANT_RESTRICTED__'') AND
                 access_entity=current_setting(''finai.entity_id'',true))))', target);
    END LOOP;
END $$;
DROP POLICY impact_snapshot_access ON public.proposal_impact_snapshots;
CREATE POLICY impact_snapshot_access ON public.proposal_impact_snapshots
USING (tenant_id::text=current_setting('finai.tenant_id',true) AND (
    current_setting('finai.tenant_access',true)='true' OR
    (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND
     (access_entity=current_setting('finai.entity_id',true) OR access_entity='__PLATFORM__'))))
WITH CHECK (tenant_id::text=current_setting('finai.tenant_id',true) AND (
    current_setting('finai.tenant_access',true)='true' OR
    (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND
     access_entity=current_setting('finai.entity_id',true))));

CREATE OR REPLACE FUNCTION public.enforce_resource_acceptance() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE identity public.canonical_identities%ROWTYPE;
DECLARE decision public.resource_decisions%ROWTYPE;
DECLARE proposal public.resource_proposals%ROWTYPE;
DECLARE mutation jsonb;
DECLARE mutation_count integer;
DECLARE expected_scope text;
DECLARE previous_version uuid;
BEGIN
    SELECT * INTO identity FROM public.canonical_identities
        WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id;
    IF NOT FOUND OR identity.object_type IS DISTINCT FROM NEW.object_type OR
        identity.access_entity IS DISTINCT FROM NEW.access_entity THEN
        RAISE EXCEPTION 'Canonical identity type and access boundary are immutable';
    END IF;
    IF NEW.proposal_id IS NOT NULL THEN
        SELECT * INTO decision FROM public.resource_decisions
            WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
        IF NOT FOUND OR decision.decision IS DISTINCT FROM 'APPROVED' THEN
            RAISE EXCEPTION 'An approved resource proposal is required';
        END IF;
        SELECT * INTO proposal FROM public.resource_proposals
            WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
        IF NOT FOUND OR decision.access_entity IS DISTINCT FROM proposal.access_entity THEN
            RAISE EXCEPTION 'Approved proposal policy mismatch';
        END IF;
        SELECT count(*) INTO mutation_count FROM jsonb_array_elements(proposal.payload->'request'->'mutations') m
            WHERE m->>'resource_id'=NEW.resource_id::text;
        IF mutation_count IS DISTINCT FROM 1 THEN
            RAISE EXCEPTION 'Version must match exactly one approved mutation';
        END IF;
        SELECT m INTO mutation FROM jsonb_array_elements(proposal.payload->'request'->'mutations') m
            WHERE m->>'resource_id'=NEW.resource_id::text;
        expected_scope := coalesce(mutation->>'access_entity',proposal.access_entity);
        IF NEW.access_entity IS DISTINCT FROM expected_scope OR
            (expected_scope IS DISTINCT FROM proposal.access_entity AND proposal.access_entity<>'__TENANT__') OR
            (proposal.access_entity='__TENANT__' AND current_setting('finai.tenant_access',true) IS DISTINCT FROM 'true') THEN
            RAISE EXCEPTION 'Version policy must match its approved mutation';
        END IF;
        IF (NEW.object_type IN ('SchemaDefinition','SemanticContract','LinkType')) IS DISTINCT FROM
            (NEW.access_entity='__PLATFORM__') THEN
            RAISE EXCEPTION 'Platform definition policy cannot contain enterprise facts';
        END IF;
        IF NEW.object_type IS DISTINCT FROM mutation->>'object_type' OR
            identity.identity_key IS DISTINCT FROM mutation->>'identity_key' OR
            NEW.attributes IS DISTINCT FROM mutation->'attributes' OR
            NEW.display_name IS DISTINCT FROM mutation->>'display_name' OR
            NEW.authority_state IS DISTINCT FROM coalesce(mutation->>'authority_state','APPROVED') OR
            NEW.evidence_class IS DISTINCT FROM coalesce(mutation->>'evidence_class','USER_ASSERTED') OR
            NEW.valid_from IS DISTINCT FROM (mutation->>'valid_from')::timestamptz OR
            NEW.valid_to IS DISTINCT FROM (mutation->>'valid_to')::timestamptz OR
            NEW.schema_version_id IS DISTINCT FROM
                (proposal.payload->'validation'->'schema_versions'->>NEW.resource_id::text)::uuid THEN
            RAISE EXCEPTION 'Version content must match its approved mutation';
        END IF;
        SELECT version_id INTO previous_version FROM public.resource_heads
            WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id;
        IF previous_version IS DISTINCT FROM (mutation->>'expected_version_id')::uuid THEN
            RAISE EXCEPTION 'Accepted version changed since the approved mutation';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION public.enforce_dependency_acceptance() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE source public.resource_versions%ROWTYPE;
DECLARE target public.resource_versions%ROWTYPE;
DECLARE retained jsonb;
BEGIN
    SELECT * INTO source FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=NEW.version_id;
    SELECT * INTO target FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=NEW.target_version_id;
    IF source.version_id IS NULL OR target.version_id IS NULL OR
        NEW.access_entity IS DISTINCT FROM source.access_entity OR
        NEW.target_resource_id IS DISTINCT FROM target.resource_id OR
        (source.access_entity<>'__TENANT__' AND target.access_entity NOT IN (source.access_entity,'__PLATFORM__')) THEN
        RAISE EXCEPTION 'Dependency cannot broaden its source resource policy';
    END IF;
    IF source.proposal_id IS NOT NULL THEN
        SELECT payload->'validation'->'dependencies'->source.resource_id::text INTO retained
            FROM public.resource_proposals WHERE tenant_id=NEW.tenant_id AND proposal_id=source.proposal_id;
        IF retained IS NULL OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(retained) d
            WHERE d->>'resource_id'=NEW.target_resource_id::text AND
                  d->>'version_id'=NEW.target_version_id::text AND d->>'relation'=NEW.relation) THEN
            RAISE EXCEPTION 'Dependency must match its approved version pin';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER approved_dependency_policy AFTER INSERT ON public.resource_dependencies
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.enforce_dependency_acceptance();

CREATE FUNCTION public.enforce_resource_head_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE version_policy text;
BEGIN
    SELECT access_entity INTO version_policy FROM public.resource_versions
        WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id AND version_id=NEW.version_id;
    IF version_policy IS NULL OR version_policy IS DISTINCT FROM NEW.access_entity THEN
        RAISE EXCEPTION 'Resource head must retain its version policy';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accepted_head_policy BEFORE INSERT OR UPDATE ON public.resource_heads
FOR EACH ROW EXECUTE FUNCTION public.enforce_resource_head_policy();
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
        AND NOT (h.access_entity='__PLATFORM__' OR tenant_access OR
            (h.access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND h.access_entity=caller_entity))
    );
END $$;
INSERT INTO schema_migrations VALUES (9);
COMMIT;
