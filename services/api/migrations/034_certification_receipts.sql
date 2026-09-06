BEGIN;
CREATE TABLE certification_receipts (
 tenant_id uuid NOT NULL, receipt_id uuid NOT NULL,
 subject_resource_id uuid NOT NULL, subject_version_id uuid NOT NULL,
 contract_resource_id uuid NOT NULL, contract_version_id uuid NOT NULL,
 access_entity text NOT NULL, actor_id text NOT NULL,
 request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 proof_hash text NOT NULL CHECK(proof_hash ~ '^[a-f0-9]{64}$'),
 payload jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,receipt_id),
 FOREIGN KEY(tenant_id,subject_resource_id,subject_version_id)
 REFERENCES resource_versions(tenant_id,resource_id,version_id),
 FOREIGN KEY(tenant_id,contract_resource_id,contract_version_id)
 REFERENCES resource_versions(tenant_id,resource_id,version_id)
);
ALTER TABLE certification_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE certification_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY certification_access ON certification_receipts
 USING(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR access_entity='__PLATFORM__' OR
 (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND
 access_entity=current_setting('finai.entity_id',true))))
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR
 (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__','__PLATFORM__') AND
 access_entity=current_setting('finai.entity_id',true))));
GRANT SELECT,INSERT ON certification_receipts TO finai_runtime;
CREATE TRIGGER immutable_certification BEFORE UPDATE OR DELETE OR TRUNCATE
 ON certification_receipts FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();

CREATE FUNCTION guard_certification_proof() RETURNS trigger LANGUAGE plpgsql AS $$
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
 OR NOT (NEW.payload->'promotion_evaluation'->'checks' @> spec->'required_checks')
 OR NOT ('["schema compatibility","identity cycles","dependency version pins","impact"]'::jsonb @> spec->'required_checks')
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
CREATE TRIGGER certification_integrity BEFORE INSERT ON certification_receipts
 FOR EACH ROW EXECUTE FUNCTION guard_certification_proof();
INSERT INTO schema_migrations VALUES(34);
COMMIT;
