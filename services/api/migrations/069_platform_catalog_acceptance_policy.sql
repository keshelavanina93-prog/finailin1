BEGIN;

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
        IF (NEW.object_type IN ('SchemaDefinition','SemanticContract','LinkType') AND NEW.access_entity<>'__PLATFORM__')
            OR (NEW.access_entity='__PLATFORM__' AND NEW.object_type NOT IN
                ('SchemaDefinition','SemanticContract','LinkType','ObjectInterface',
                 'ObjectTypeGroup','ObjectTypeImplementation','ObjectSetDefinition',
                 'ObjectBinding','DerivedProperty','FactContract',
                 'FinanceCapabilityDefinition','FinanceClassificationPolicy',
                 'FinanceProjectionDefinition','CertificationContract')) THEN
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

INSERT INTO schema_migrations VALUES(69);
COMMIT;
