BEGIN;
ALTER TABLE resource_lifecycle_requests ADD COLUMN certification_proof_hash text
 CHECK(certification_proof_hash ~ '^[a-f0-9]{64}$');
ALTER TABLE resource_lifecycle_events ADD COLUMN certification_proof_hash text
 CHECK(certification_proof_hash ~ '^[a-f0-9]{64}$');
CREATE FUNCTION g8_check_certification_receipt(tenant uuid,receipt uuid,subjectresource uuid,
 subjectversion uuid,contractresource uuid,contractversion uuid,
 allow_subject_unavailable boolean DEFAULT false) RETURNS text
 LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE retained certification_receipts%ROWTYPE; subject resource_versions%ROWTYPE; contract resource_versions%ROWTYPE;
 proposal resource_proposals%ROWTYPE; spec jsonb; input jsonb; source resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE; pin uuid; schema_count integer;
BEGIN
 SELECT * INTO retained FROM certification_receipts WHERE tenant_id=tenant AND receipt_id=receipt;
 IF retained.receipt_id IS NULL OR retained.subject_resource_id IS DISTINCT FROM subjectresource
 OR retained.subject_version_id IS DISTINCT FROM subjectversion
 OR retained.contract_resource_id IS DISTINCT FROM contractresource
 OR retained.contract_version_id IS DISTINCT FROM contractversion
 THEN RAISE EXCEPTION 'Certification receipt exact pins required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||retained.tenant_id::text,0));
 SELECT * INTO subject FROM resource_versions WHERE tenant_id=retained.tenant_id
 AND resource_id=retained.subject_resource_id AND version_id=retained.subject_version_id;
 SELECT * INTO contract FROM resource_versions WHERE tenant_id=retained.tenant_id
 AND resource_id=retained.contract_resource_id AND version_id=retained.contract_version_id;
 spec := contract.attributes->'definition';
 IF subject.version_id IS NULL OR contract.version_id IS NULL
 OR subject.authority_state<>'APPROVED' OR contract.authority_state<>'APPROVED'
 OR g8_effective_version_id(retained.tenant_id,subject.resource_id,statement_timestamp()) IS DISTINCT FROM subject.version_id
 OR g8_effective_version_id(retained.tenant_id,contract.resource_id,statement_timestamp()) IS DISTINCT FROM contract.version_id
 OR contract.object_type<>'CertificationContract'
 OR spec->>'claim' IS DISTINCT FROM 'CANONICAL_DEFINITION_CONFORMANCE'
 OR spec->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR spec->>'subject_type' IS DISTINCT FROM subject.object_type
 OR subject.object_type NOT IN ('SchemaDefinition','SemanticContract','LinkType',
 'ObjectSetDefinition','ObjectInterface','ObjectTypeImplementation','ObjectTypeGroup',
 'DerivedProperty','ObjectBinding','FactContract','FactReconciliation','RegulatoryRule')
 OR subject.access_entity IS DISTINCT FROM retained.access_entity
 OR (subject.access_entity<>'__TENANT__' AND contract.access_entity NOT IN (subject.access_entity,'__PLATFORM__'))
 OR retained.payload->>'access_entity' IS DISTINCT FROM retained.access_entity
 OR retained.payload->>'purpose' IS DISTINCT FROM 'CANONICAL_DEFINITION_CONFORMANCE'
 OR retained.payload->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR retained.payload->>'status' IS DISTINCT FROM 'PASS'
 OR retained.payload->'subject'->>'resource_id' IS DISTINCT FROM subject.resource_id::text
 OR retained.payload->'subject'->>'version_id' IS DISTINCT FROM subject.version_id::text
 OR retained.payload->'contract'->>'resource_id' IS DISTINCT FROM contract.resource_id::text
 OR retained.payload->'contract'->>'version_id' IS DISTINCT FROM contract.version_id::text
 OR retained.payload->>'subject_content_hash' IS DISTINCT FROM subject.content_hash
 OR retained.payload->>'contract_content_hash' IS DISTINCT FROM contract.content_hash
 OR retained.payload->'contract_attributes' IS DISTINCT FROM contract.attributes
 THEN RAISE EXCEPTION 'Invalid canonical certification contract'; END IF;
 IF contract.attributes->>'subject_schema_id' IS NOT NULL THEN
   SELECT count(DISTINCT target_version_id) INTO schema_count FROM resource_dependencies
   WHERE tenant_id=retained.tenant_id AND version_id=contract.version_id
   AND target_resource_id=(contract.attributes->>'subject_schema_id')::uuid;
   SELECT target_version_id INTO pin FROM resource_dependencies
   WHERE tenant_id=retained.tenant_id AND version_id=contract.version_id
   AND target_resource_id=(contract.attributes->>'subject_schema_id')::uuid LIMIT 1;
   IF schema_count<>1 OR pin IS DISTINCT FROM subject.schema_version_id
   OR retained.payload->'subject_schema'->>'resource_id' IS DISTINCT FROM contract.attributes->>'subject_schema_id'
   OR retained.payload->'subject_schema'->>'version_id' IS DISTINCT FROM pin::text
   THEN RAISE EXCEPTION 'Certification subject schema pin mismatch'; END IF;
 ELSIF subject.object_type NOT IN ('SchemaDefinition','SemanticContract','LinkType') THEN
   RAISE EXCEPTION 'Certification subject schema required';
 END IF;
 SELECT * INTO proposal FROM resource_proposals WHERE tenant_id=retained.tenant_id AND proposal_id=subject.proposal_id;
 IF proposal.proposal_id IS NULL OR NOT EXISTS(SELECT 1 FROM resource_decisions
 WHERE tenant_id=retained.tenant_id AND proposal_id=subject.proposal_id AND decision='APPROVED')
 OR retained.payload->>'promotion_proposal_id' IS DISTINCT FROM subject.proposal_id::text
 OR retained.payload->'promotion_evaluation' IS DISTINCT FROM proposal.payload->'validation'->'evaluation'
 OR retained.payload->'promotion_evaluation'->>'status' IS DISTINCT FROM 'PASS'
 OR retained.payload->'promotion_evaluation'->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1'
 OR retained.payload->'promotion_evaluation'->>'proposal_hash' IS DISTINCT FROM proposal.request_hash
 OR jsonb_typeof(spec->'required_checks') IS DISTINCT FROM 'array'
 OR jsonb_array_length(spec->'required_checks') NOT BETWEEN 1 AND 4
 OR NOT (retained.payload->'promotion_evaluation'->'checks' @> (spec->'required_checks'))
 OR NOT ('["schema compatibility","identity cycles","dependency version pins","impact"]'::jsonb @> (spec->'required_checks'))
 THEN RAISE EXCEPTION 'Matching retained promotion evaluation required'; END IF;
 -- Recompute the complete transitive pin set; caller cannot omit a withdrawn ancestor.
 FOR source IN WITH RECURSIVE lineage(version_id) AS (
   SELECT subject.version_id UNION SELECT contract.version_id
   UNION SELECT d.target_version_id FROM resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
   WHERE d.tenant_id=retained.tenant_id
 ) SELECT v.* FROM resource_versions v JOIN lineage l USING(version_id) WHERE v.tenant_id=retained.tenant_id
 LOOP
   IF source.authority_state<>'APPROVED' OR
   g8_effective_version_id(retained.tenant_id,source.resource_id,statement_timestamp()) IS DISTINCT FROM source.version_id
   THEN RAISE EXCEPTION 'Certification input unavailable for current use'; END IF;
   SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=retained.tenant_id
   AND version_id=source.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
   IF event.payload->>'target_state' IN ('REVOKED','SUPERSEDED') OR
   (event.event_id IS NOT NULL AND event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE'
    AND NOT(allow_subject_unavailable AND source.version_id=subjectversion))
   THEN RAISE EXCEPTION 'Certification input authority withdrawn'; END IF;
 END LOOP;
 RETURN retained.proof_hash;
END $$;
GRANT EXECUTE ON FUNCTION g8_check_certification_receipt(uuid,uuid,uuid,uuid,uuid,uuid,boolean) TO finai_runtime;
CREATE OR REPLACE FUNCTION g8_lifecycle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE req resource_lifecycle_requests%ROWTYPE; ver resource_versions%ROWTYPE;
 prior resource_lifecycle_events%ROWTYPE; wanted text; previous text; receipt certification_receipts%ROWTYPE; proof text;
 progression text[] := ARRAY['OBSERVED','PARSED','MAPPED_CANDIDATE','VALIDATED','RECONCILED','APPROVED','AUTHORITATIVE'];
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 IF TG_TABLE_NAME='resource_lifecycle_requests' THEN
  SELECT * INTO ver FROM resource_versions WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id AND version_id=NEW.version_id;
  IF ver.version_id IS NULL OR ver.access_entity IS DISTINCT FROM NEW.access_entity
   OR NEW.payload->'subject'->>'resource_id' IS DISTINCT FROM NEW.resource_id::text
   OR NEW.payload->'subject'->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR NEW.payload->>'request_id' IS DISTINCT FROM NEW.request_id::text
   OR (length(btrim(NEW.payload->>'reason'))>=10) IS NOT TRUE
   OR (NEW.payload->>'epistemic_state' IN ('OBSERVED','DERIVED','INFERRED')) IS NOT TRUE
   OR (NEW.payload->>'business_state' IN ('PROVISIONAL','LIVE','RECONCILED')) IS NOT TRUE
   OR (NEW.payload->>'availability_state' IN ('AVAILABLE','DEGRADED','STALE','UNAVAILABLE','CONFLICTING')) IS NOT TRUE
  THEN RAISE EXCEPTION 'Invalid lifecycle subject or state'; END IF;
  req := NEW;
 ELSE
  SELECT * INTO req FROM resource_lifecycle_requests WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
  IF req.request_id IS NULL OR req.access_entity IS DISTINCT FROM NEW.access_entity THEN RAISE EXCEPTION 'Lifecycle policy mismatch'; END IF;
  IF TG_TABLE_NAME='resource_lifecycle_decisions' THEN
   IF req.submitted_by=NEW.reviewed_by THEN RAISE EXCEPTION 'Independent lifecycle review required'; END IF;
   IF NEW.decision='REJECTED' THEN RETURN NEW; END IF;
  ELSE
   IF NEW.payload IS DISTINCT FROM req.payload OR NEW.version_id IS DISTINCT FROM req.version_id OR NEW.resource_id IS DISTINCT FROM req.resource_id
    OR NEW.certification_proof_hash IS DISTINCT FROM req.certification_proof_hash
    OR NOT EXISTS(SELECT 1 FROM resource_lifecycle_decisions WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id AND decision='APPROVED')
   THEN RAISE EXCEPTION 'Approved lifecycle request required'; END IF;
  END IF;
 END IF;
 SELECT * INTO prior FROM resource_lifecycle_events WHERE tenant_id=req.tenant_id AND version_id=req.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
 IF (req.payload->>'expected_event_id') IS DISTINCT FROM prior.event_id::text THEN RAISE EXCEPTION 'Lifecycle compare and swap failed'; END IF;
 previous := prior.payload->>'target_state'; wanted := req.payload->>'target_state';
 IF NOT ((previous IS NULL AND wanted='OBSERVED') OR
  (wanted=progression[array_position(progression,previous)+1]) OR
  ((previous=ANY(progression) OR previous='CERTIFIED') AND wanted=previous AND (
    req.payload->>'epistemic_state' IS DISTINCT FROM prior.payload->>'epistemic_state' OR
    req.payload->>'business_state' IS DISTINCT FROM prior.payload->>'business_state' OR
    req.payload->>'availability_state' IS DISTINCT FROM prior.payload->>'availability_state')) OR
  (previous='AUTHORITATIVE' AND wanted='CERTIFIED') OR
  ((previous=ANY(progression) OR previous='CERTIFIED') AND wanted IN ('SUPERSEDED','REVOKED'))) IS TRUE
 THEN RAISE EXCEPTION 'Unsupported lifecycle transition'; END IF;
 IF wanted IN ('AUTHORITATIVE','CERTIFIED') AND TG_TABLE_NAME<>'resource_lifecycle_requests' AND current_setting('finai.tenant_access',true) IS DISTINCT FROM 'true'
 THEN RAISE EXCEPTION 'Authority administrator required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM resource_versions v
 WHERE v.tenant_id=req.tenant_id AND v.resource_id=req.resource_id AND v.version_id=req.version_id
 AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp()) AND v.authority_state='APPROVED'
 AND v.valid_from<=clock_timestamp() AND (v.valid_to IS NULL OR v.valid_to>clock_timestamp()))
 THEN RAISE EXCEPTION 'Current accepted version required'; END IF;
 IF previous='CERTIFIED' OR wanted='CERTIFIED' THEN
  IF req.payload->>'certification_receipt_id' IS NULL OR req.payload->'certification_contract'->>'resource_id' IS NULL
  OR req.payload->'certification_contract'->>'version_id' IS NULL THEN
    RAISE EXCEPTION 'Certified lifecycle requires exact receipt and contract pins'; END IF;
  IF previous='CERTIFIED' AND (
   req.payload->'certification_receipt_id' IS DISTINCT FROM prior.payload->'certification_receipt_id' OR
   req.payload->'certification_contract' IS DISTINCT FROM prior.payload->'certification_contract') THEN
    RAISE EXCEPTION 'Certified lifecycle must retain original binding'; END IF;
  IF wanted IN ('REVOKED','SUPERSEDED') THEN
   SELECT * INTO receipt FROM certification_receipts WHERE tenant_id=req.tenant_id
   AND receipt_id=(req.payload->>'certification_receipt_id')::uuid;
   IF receipt.receipt_id IS NULL OR receipt.subject_resource_id IS DISTINCT FROM req.resource_id
   OR receipt.subject_version_id IS DISTINCT FROM req.version_id
   OR receipt.contract_resource_id::text IS DISTINCT FROM req.payload->'certification_contract'->>'resource_id'
   OR receipt.contract_version_id::text IS DISTINCT FROM req.payload->'certification_contract'->>'version_id'
   THEN RAISE EXCEPTION 'Original certification evidence required'; END IF;
   proof := receipt.proof_hash;
  ELSE
   proof := g8_check_certification_receipt(req.tenant_id,(req.payload->>'certification_receipt_id')::uuid,
    req.resource_id,req.version_id,(req.payload->'certification_contract'->>'resource_id')::uuid,
    (req.payload->'certification_contract'->>'version_id')::uuid,
    previous='CERTIFIED' AND wanted='CERTIFIED');
  END IF;
  IF req.certification_proof_hash IS DISTINCT FROM proof THEN
   RAISE EXCEPTION 'Exact retained certification proof hash required'; END IF;
 ELSIF req.certification_proof_hash IS NOT NULL OR req.payload->>'certification_receipt_id' IS NOT NULL
 OR req.payload->>'certification_contract' IS NOT NULL THEN
   RAISE EXCEPTION 'Certification binding requires certified lifecycle';
 END IF;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;

INSERT INTO schema_migrations VALUES(37);
COMMIT;
