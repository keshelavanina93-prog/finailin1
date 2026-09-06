BEGIN;
CREATE OR REPLACE FUNCTION guard_artifact_retention_evaluation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE artifact jsonb; ref jsonb; class text; hash text; scope jsonb; recorded timestamptz;
 policy resource_versions%ROWTYPE; spec jsonb; basis jsonb; at_time timestamptz; eligible timestamptz;
 reasons jsonb := '[]'::jsonb; expected_status text; ancestor resource_versions%ROWTYPE; event resource_lifecycle_events%ROWTYPE;
 lineage_count integer := 0; edge_count integer := 0;
BEGIN
 artifact := NEW.payload->'artifact'; ref := artifact->'reference';
 CASE ref->>'kind'
 WHEN 'SOURCE_RECEIPT' THEN
  SELECT source_sha256,exact_scope,ingested_at INTO hash,scope,recorded FROM hydration_runs
  WHERE tenant_id=NEW.tenant_id AND receipt_id=ref->>'receipt_id';
  class := 'IMMUTABLE_SOURCE_EVIDENCE';
 WHEN 'SOURCE_DOCUMENT' THEN
  SELECT source_sha256,exact_scope,created_at INTO hash,scope,recorded FROM source_documents
  WHERE tenant_id=NEW.tenant_id AND document_id=ref->>'document_id';
  class := 'IMMUTABLE_SOURCE_EVIDENCE';
 WHEN 'FACT_RUN' THEN
  SELECT substring(run_id FROM 5),exact_scope,created_at INTO hash,scope,recorded FROM fact_calculation_runs
  WHERE tenant_id=NEW.tenant_id AND run_id=ref->>'run_id';
  class := 'REPRODUCIBLE_DERIVED_ARTIFACT';
 WHEN 'PUBLICATION_MANIFEST' THEN
  SELECT substring(payload->'manifest'->>'publication_id' FROM 5),exact_scope,created_at INTO hash,scope,recorded
  FROM workflow_events WHERE tenant_id=NEW.tenant_id AND workflow_id=ref->>'workflow_id'
  AND event_id='publication:'||(ref->>'generation')
  AND payload->'manifest'->>'publication_id'=ref->>'publication_id'
  AND payload->>'state'='PUBLISHED';
  class := 'AUTHORITATIVE_RECORD';
  IF artifact->>'authority_scope' IS DISTINCT FROM 'EXECUTION_ONLY' THEN
    RAISE EXCEPTION 'Publication record does not establish financial authority'; END IF;
 ELSE RAISE EXCEPTION 'Unsupported artifact retention reference';
 END CASE;
 IF (class='IMMUTABLE_SOURCE_EVIDENCE' AND artifact->>'authority_scope' IS DISTINCT FROM 'SOURCE_OBSERVATION')
 OR (class='REPRODUCIBLE_DERIVED_ARTIFACT' AND artifact->>'authority_scope' IS DISTINCT FROM 'CALCULATION_EVIDENCE_ONLY')
 OR hash IS NULL OR scope IS DISTINCT FROM NEW.exact_scope
 OR artifact->'exact_scope' IS DISTINCT FROM scope OR artifact->>'content_hash' IS DISTINCT FROM hash
 OR artifact->>'artifact_class' IS DISTINCT FROM class
 OR (artifact->>'recorded_at')::timestamptz IS DISTINCT FROM recorded
 OR NEW.payload->>'purpose' IS DISTINCT FROM 'DISPOSITION_EVALUATION_ONLY'
 OR NEW.payload->>'contract_version' IS DISTINCT FROM 'artifact-retention/1'
 OR NEW.payload->>'effective_disposition' IS DISTINCT FROM 'PRESERVE'
 OR NEW.payload->'execution_authorized' IS DISTINCT FROM 'false'::jsonb
 OR NEW.payload->'legal_compliance_established' IS DISTINCT FROM 'false'::jsonb
 OR (NEW.payload->>'requested_action' IN ('PRESERVE','ARCHIVE','DELETE')) IS NOT TRUE
 OR (NEW.payload->>'status' IN ('PRESERVED','BLOCKED','POLICY_CONDITIONS_MET')) IS NOT TRUE
 THEN RAISE EXCEPTION 'Retention evidence must preserve exact artifact and non-execution boundary'; END IF;
 at_time := (NEW.payload->>'evaluated_at')::timestamptz;
 IF at_time IS NULL OR at_time>clock_timestamp() OR at_time<statement_timestamp()-interval '1 minute'
 THEN RAISE EXCEPTION 'Retention evaluation requires current server time'; END IF;
 IF NEW.payload->'policy' IS NOT NULL AND NEW.payload->'policy'<>'null'::jsonb THEN
  basis := NEW.payload->'policy';
  SELECT * INTO policy FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(basis->'reference'->>'resource_id')::uuid
  AND version_id=(basis->'reference'->>'version_id')::uuid;
  spec := policy.attributes->'definition';
  IF policy.version_id IS NULL OR policy.object_type<>'RetentionPolicy' OR policy.authority_state<>'APPROVED'
  OR policy.access_entity IS DISTINCT FROM NEW.exact_scope->>'legal_entity_id'
  OR g8_effective_version_id(NEW.tenant_id,policy.resource_id,statement_timestamp()) IS DISTINCT FROM policy.version_id
  OR basis->>'content_hash' IS DISTINCT FROM policy.content_hash OR basis->'attributes' IS DISTINCT FROM policy.attributes
  OR basis->'reference' IS DISTINCT FROM NEW.payload->'requested_policy'
  OR jsonb_typeof(spec->'artifact_classes') IS DISTINCT FROM 'array'
  OR jsonb_typeof(spec->'minimum_retention_days') IS DISTINCT FROM 'number'
  OR (spec->>'minimum_retention_days')::integer NOT BETWEEN 0 AND 365000
  OR spec->>'legal_basis_state' NOT IN ('DECLARED','NOT_ESTABLISHED')
  OR jsonb_typeof(spec->'legal_hold') IS DISTINCT FROM 'boolean'
  THEN RAISE EXCEPTION 'Retention policy snapshot does not match current canonical policy'; END IF;
  IF NOT ((spec->'artifact_classes') @> jsonb_build_array(class)) THEN
   reasons := reasons || '["ARTIFACT_CLASS_OUTSIDE_POLICY"]'::jsonb; END IF;
  IF spec->>'legal_basis_state'<>'DECLARED' THEN
   reasons := reasons || '["LEGAL_BASIS_NOT_ESTABLISHED"]'::jsonb;
  ELSIF coalesce(length(btrim(spec->>'legal_basis')),0)<10 THEN
   RAISE EXCEPTION 'Declared retention policy requires explicit basis'; END IF;
  IF spec->'legal_hold'='true'::jsonb THEN reasons := reasons || '["LEGAL_HOLD_DECLARED"]'::jsonb; END IF;
  eligible := recorded + make_interval(days => (spec->>'minimum_retention_days')::integer);
  IF eligible>at_time THEN reasons := reasons || '["MINIMUM_RETENTION_NOT_ELAPSED"]'::jsonb; END IF;
  IF (NEW.payload->>'eligible_at')::timestamptz IS DISTINCT FROM eligible THEN
   RAISE EXCEPTION 'Retention eligibility time mismatch'; END IF;
  FOR ancestor IN WITH RECURSIVE lineage(version_id) AS (
   SELECT policy.version_id UNION SELECT d.target_version_id FROM resource_dependencies d
   JOIN lineage l ON d.version_id=l.version_id WHERE d.tenant_id=NEW.tenant_id
  ) SELECT v.* FROM resource_versions v JOIN lineage l USING(version_id) WHERE v.tenant_id=NEW.tenant_id
  LOOP
   lineage_count := lineage_count+1;
   edge_count := edge_count+(SELECT count(*) FROM (SELECT DISTINCT target_resource_id,target_version_id
    FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=ancestor.version_id) d);
   IF lineage_count>1000 OR edge_count>5000 THEN RAISE EXCEPTION 'Retention policy lineage exceeds bounds'; END IF;
   SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id
   AND version_id=ancestor.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
   IF ancestor.authority_state<>'APPROVED' OR
   g8_effective_version_id(NEW.tenant_id,ancestor.resource_id,statement_timestamp()) IS DISTINCT FROM ancestor.version_id
   OR (event.event_id IS NOT NULL AND (event.payload->>'target_state' IN ('REVOKED','SUPERSEDED')
       OR event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE'))
   THEN RAISE EXCEPTION 'Retention policy authority unavailable'; END IF;
   IF event.payload->>'target_state'='CERTIFIED' THEN
    IF
   g8_check_certification_receipt(NEW.tenant_id,(event.payload->>'certification_receipt_id')::uuid,
    ancestor.resource_id,ancestor.version_id,
    (event.payload->'certification_contract'->>'resource_id')::uuid,
    (event.payload->'certification_contract'->>'version_id')::uuid)
    IS DISTINCT FROM event.certification_proof_hash THEN
     RAISE EXCEPTION 'Retention policy certification unavailable'; END IF;
   END IF;
  END LOOP;
 ELSE
  IF NEW.payload->'requested_policy' IS NULL OR NEW.payload->'requested_policy'='null'::jsonb THEN
   reasons := '["POLICY_NOT_ESTABLISHED"]'::jsonb;
  ELSE reasons := '["POLICY_UNAVAILABLE_FOR_CURRENT_USE"]'::jsonb; END IF;
  IF NEW.payload->'eligible_at' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Unestablished retention cannot assert eligibility time'; END IF;
 END IF;
 expected_status := CASE WHEN NEW.payload->>'requested_action'='PRESERVE' THEN 'PRESERVED'
  WHEN reasons='[]'::jsonb THEN 'POLICY_CONDITIONS_MET' ELSE 'BLOCKED' END;
 IF NEW.payload->'reasons' IS DISTINCT FROM reasons OR NEW.payload->>'status' IS DISTINCT FROM expected_status
 THEN RAISE EXCEPTION 'Retention evaluation does not match policy conditions'; END IF;
 IF (NEW.payload->>'requested_action'='PRESERVE') IS DISTINCT FROM (NEW.payload->>'status'='PRESERVED')
 THEN RAISE EXCEPTION 'Preservation disposition mismatch'; END IF;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(40);
COMMIT;
