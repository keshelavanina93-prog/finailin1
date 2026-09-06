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
                ('SchemaDefinition','SemanticContract','LinkType','CertificationContract')) THEN
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

CREATE OR REPLACE FUNCTION guard_certification_proof() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE subject resource_versions%ROWTYPE; contract resource_versions%ROWTYPE;
 proposal resource_proposals%ROWTYPE; spec jsonb; input jsonb; source resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE; pin uuid; schema_count integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 SELECT * INTO subject FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=NEW.subject_resource_id AND version_id=NEW.subject_version_id;
 SELECT * INTO contract FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=NEW.contract_resource_id AND version_id=NEW.contract_version_id;
 spec := contract.attributes->'definition';
 IF subject.version_id IS NULL OR contract.version_id IS NULL
 OR subject.authority_state<>'APPROVED' OR contract.authority_state<>'APPROVED'
 OR g8_effective_version_id(NEW.tenant_id,subject.resource_id,statement_timestamp()) IS DISTINCT FROM subject.version_id
 OR g8_effective_version_id(NEW.tenant_id,contract.resource_id,statement_timestamp()) IS DISTINCT FROM contract.version_id
 OR contract.object_type<>'CertificationContract'
 OR spec->>'claim' IS DISTINCT FROM 'CANONICAL_DEFINITION_CONFORMANCE'
 OR spec->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR spec->>'subject_type' IS DISTINCT FROM subject.object_type
 OR subject.object_type NOT IN ('SchemaDefinition','SemanticContract','LinkType',
 'ObjectSetDefinition','ObjectInterface','ObjectTypeImplementation','ObjectTypeGroup',
 'DerivedProperty','ObjectBinding','FactContract','FactReconciliation','RegulatoryRule')
 OR subject.access_entity IS DISTINCT FROM NEW.access_entity
 OR (subject.access_entity<>'__TENANT__' AND contract.access_entity NOT IN (subject.access_entity,'__PLATFORM__'))
 OR NEW.payload->>'access_entity' IS DISTINCT FROM NEW.access_entity
 OR NEW.payload->>'purpose' IS DISTINCT FROM 'CANONICAL_DEFINITION_CONFORMANCE'
 OR NEW.payload->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR NEW.payload->>'status' IS DISTINCT FROM 'PASS'
 OR NEW.payload->'subject'->>'resource_id' IS DISTINCT FROM subject.resource_id::text
 OR NEW.payload->'subject'->>'version_id' IS DISTINCT FROM subject.version_id::text
 OR NEW.payload->'contract'->>'resource_id' IS DISTINCT FROM contract.resource_id::text
 OR NEW.payload->'contract'->>'version_id' IS DISTINCT FROM contract.version_id::text
 OR NEW.payload->>'subject_content_hash' IS DISTINCT FROM subject.content_hash
 OR NEW.payload->>'contract_content_hash' IS DISTINCT FROM contract.content_hash
 OR NEW.payload->'contract_attributes' IS DISTINCT FROM contract.attributes
 THEN RAISE EXCEPTION 'Invalid canonical certification contract'; END IF;
 IF contract.attributes->>'subject_schema_id' IS NOT NULL THEN
   SELECT count(DISTINCT target_version_id) INTO schema_count FROM resource_dependencies
   WHERE tenant_id=NEW.tenant_id AND version_id=contract.version_id
   AND target_resource_id=(contract.attributes->>'subject_schema_id')::uuid;
   SELECT target_version_id INTO pin FROM resource_dependencies
   WHERE tenant_id=NEW.tenant_id AND version_id=contract.version_id
   AND target_resource_id=(contract.attributes->>'subject_schema_id')::uuid LIMIT 1;
   IF schema_count<>1 OR pin IS DISTINCT FROM subject.schema_version_id
   OR NEW.payload->'subject_schema'->>'resource_id' IS DISTINCT FROM contract.attributes->>'subject_schema_id'
   OR NEW.payload->'subject_schema'->>'version_id' IS DISTINCT FROM pin::text
   THEN RAISE EXCEPTION 'Certification subject schema pin mismatch'; END IF;
 ELSIF subject.object_type NOT IN ('SchemaDefinition','SemanticContract','LinkType') THEN
   RAISE EXCEPTION 'Certification subject schema required';
 END IF;
 SELECT * INTO proposal FROM resource_proposals WHERE tenant_id=NEW.tenant_id AND proposal_id=subject.proposal_id;
 IF proposal.proposal_id IS NULL OR NOT EXISTS(SELECT 1 FROM resource_decisions
 WHERE tenant_id=NEW.tenant_id AND proposal_id=subject.proposal_id AND decision='APPROVED')
 OR NEW.payload->>'promotion_proposal_id' IS DISTINCT FROM subject.proposal_id::text
 OR NEW.payload->'promotion_evaluation' IS DISTINCT FROM proposal.payload->'validation'->'evaluation'
 OR NEW.payload->'promotion_evaluation'->>'status' IS DISTINCT FROM 'PASS'
 OR NEW.payload->'promotion_evaluation'->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR NEW.payload->'promotion_evaluation'->>'proposal_hash' IS DISTINCT FROM proposal.request_hash
 OR jsonb_typeof(spec->'required_checks') IS DISTINCT FROM 'array'
 OR jsonb_array_length(spec->'required_checks') NOT BETWEEN 1 AND 4
 OR NOT (NEW.payload->'promotion_evaluation'->'checks' @> (spec->'required_checks'))
 OR NOT ('["schema compatibility","identity cycles","dependency version pins","impact"]'::jsonb @> (spec->'required_checks'))
 THEN RAISE EXCEPTION 'Matching retained promotion evaluation required'; END IF;
 -- Recompute the complete transitive pin set; caller cannot omit a withdrawn ancestor.
 FOR source IN WITH RECURSIVE lineage(version_id) AS (
   SELECT subject.version_id UNION SELECT contract.version_id
   UNION SELECT d.target_version_id FROM resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
   WHERE d.tenant_id=NEW.tenant_id
 ) SELECT v.* FROM resource_versions v JOIN lineage l USING(version_id) WHERE v.tenant_id=NEW.tenant_id
 LOOP
   IF source.authority_state<>'APPROVED' OR
   g8_effective_version_id(NEW.tenant_id,source.resource_id,statement_timestamp()) IS DISTINCT FROM source.version_id
   THEN RAISE EXCEPTION 'Certification input unavailable for current use'; END IF;
   SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id
   AND version_id=source.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
   IF event.payload->>'target_state' IN ('REVOKED','SUPERSEDED') OR
   (event.event_id IS NOT NULL AND event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE')
   THEN RAISE EXCEPTION 'Certification input authority withdrawn'; END IF;
 END LOOP;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(36);
COMMIT;
