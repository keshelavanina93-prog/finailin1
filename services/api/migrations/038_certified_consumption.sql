BEGIN;
-- Extend guarded consumption without weakening existing exact-pin, RLS or lineage checks.
-- This helper validates scoped evidence even when the requested floor is AUTHORITATIVE.
CREATE FUNCTION g8_current_event_certification(tenant uuid, retained resource_lifecycle_events)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE proof_hash text; contract jsonb; receipt uuid;
BEGIN
 IF retained.tenant_id IS DISTINCT FROM tenant
  OR retained.payload->>'target_state' IS DISTINCT FROM 'CERTIFIED'
 THEN RAISE EXCEPTION 'Certified lifecycle evidence required'; END IF;
 contract := retained.payload->'certification_contract';
 receipt := (retained.payload->>'certification_receipt_id')::uuid;
 IF receipt IS NULL OR jsonb_typeof(contract) IS DISTINCT FROM 'object'
  OR NOT (contract ? 'resource_id' AND contract ? 'version_id')
 THEN RAISE EXCEPTION 'Exact certification receipt and contract required'; END IF;
 proof_hash := g8_check_certification_receipt(tenant,receipt,retained.resource_id,
  retained.version_id,(contract->>'resource_id')::uuid,(contract->>'version_id')::uuid);
 IF proof_hash IS NULL OR retained.certification_proof_hash IS DISTINCT FROM proof_hash
 THEN RAISE EXCEPTION 'Certified lifecycle receipt hash mismatch'; END IF;
 RETURN jsonb_build_object('receipt_id',receipt::text,'contract',contract,
  'proof_hash',proof_hash,'claim','CANONICAL_DEFINITION_CONFORMANCE');
END $$;
GRANT EXECUTE ON FUNCTION g8_current_event_certification(uuid,resource_lifecycle_events) TO finai_runtime;

CREATE OR REPLACE FUNCTION guard_consumption_proof() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE consumer resource_versions%ROWTYPE; input jsonb; source resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE; required text; minimum text;
 requirements jsonb; mapping record; policy resource_versions%ROWTYPE;
 controls uuid[] := ARRAY[]::uuid[]; input_minimum text; expected_certification jsonb;
 progression text[] := ARRAY['OBSERVED','PARSED','MAPPED_CANDIDATE','VALIDATED','RECONCILED','APPROVED','AUTHORITATIVE','CERTIFIED'];
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 SELECT v.* INTO consumer FROM resource_versions v
 WHERE v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp())
 AND v.tenant_id=NEW.tenant_id AND v.resource_id=NEW.consumer_resource_id AND v.version_id=NEW.consumer_version_id;
 required := consumer.attributes->>'minimum_authority_state'; minimum := NEW.payload->>'minimum_state';
 IF consumer.version_id IS NULL OR consumer.authority_state<>'APPROVED'
 OR consumer.access_entity IS DISTINCT FROM NEW.access_entity
 OR NEW.payload->>'access_entity' IS DISTINCT FROM NEW.access_entity
 OR NEW.payload->>'purpose' IS DISTINCT FROM 'GUARDED_CURRENT_CONSUMPTION'
 OR NEW.payload->>'consumption_id' IS DISTINCT FROM NEW.consumption_id::text
 OR NEW.payload->'consumer'->>'resource_id' IS DISTINCT FROM NEW.consumer_resource_id::text
 OR NEW.payload->'consumer'->>'version_id' IS DISTINCT FROM NEW.consumer_version_id::text
 OR NEW.payload->>'consumer_content_hash' IS DISTINCT FROM consumer.content_hash
 OR (array_position(progression,minimum)>=array_position(progression,required)) IS NOT TRUE
 THEN RAISE EXCEPTION 'Invalid canonical consumption contract'; END IF;
 SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
 IF event.payload->>'target_state' IN ('REVOKED','SUPERSEDED')
 OR NEW.payload->>'consumer_event_id' IS DISTINCT FROM event.event_id::text
 THEN RAISE EXCEPTION 'Consumer lifecycle changed'; END IF;
 IF event.payload->>'target_state'='CERTIFIED' THEN
  expected_certification := g8_current_event_certification(NEW.tenant_id,event);
  IF NEW.payload->>'contract_version' IS DISTINCT FROM 'guarded-consumption/3'
   OR NEW.payload->'consumer_certification' IS DISTINCT FROM expected_certification
  THEN RAISE EXCEPTION 'Consumer certification proof mismatch'; END IF;
 ELSIF NEW.payload ? 'consumer_certification' THEN
  RAISE EXCEPTION 'Unexpected consumer certification proof';
 END IF;
 IF minimum='CERTIFIED' THEN
  requirements := consumer.attributes->'certification_requirements';
  IF jsonb_typeof(requirements) IS DISTINCT FROM 'object'
   OR (SELECT count(*) FROM jsonb_object_keys(requirements)) NOT BETWEEN 1 AND 1000
   OR NEW.payload->'certification_requirements' IS DISTINCT FROM requirements
   OR NEW.payload->>'contract_version' IS DISTINCT FROM 'guarded-consumption/3'
  THEN RAISE EXCEPTION 'Exact certification requirements required'; END IF;
  IF consumer.schema_version_id IS NOT NULL THEN
   SELECT coalesce(array_agg(DISTINCT target_resource_id),'{}'::uuid[]) INTO controls
   FROM resource_dependencies WHERE tenant_id=NEW.tenant_id
    AND version_id=NEW.consumer_version_id AND target_version_id=consumer.schema_version_id;
   IF cardinality(controls)<>1 THEN RAISE EXCEPTION 'Consumer schema dependency missing'; END IF;
  END IF;
  FOR mapping IN SELECT key,value FROM jsonb_each(requirements) LOOP
   IF mapping.key IS DISTINCT FROM (mapping.key::uuid)::text
    OR mapping.key::uuid=NEW.consumer_resource_id
    OR jsonb_typeof(mapping.value) IS DISTINCT FROM 'object'
    OR (SELECT count(*) FROM jsonb_object_keys(mapping.value))<>2
    OR NOT (mapping.value ? 'resource_id' AND mapping.value ? 'version_id')
   THEN RAISE EXCEPTION 'Invalid certification requirement'; END IF;
   SELECT v.* INTO policy FROM resource_versions v WHERE v.tenant_id=NEW.tenant_id
    AND v.resource_id=(mapping.value->>'resource_id')::uuid
    AND v.version_id=(mapping.value->>'version_id')::uuid;
   IF policy.version_id IS NULL OR policy.object_type<>'CertificationContract'
    OR policy.resource_id=NEW.consumer_resource_id
    OR NOT EXISTS(SELECT 1 FROM resource_dependencies d WHERE d.tenant_id=NEW.tenant_id
      AND d.version_id=NEW.consumer_version_id AND d.target_resource_id=policy.resource_id
      AND d.target_version_id=policy.version_id)
    OR NOT EXISTS(SELECT 1 FROM resource_dependencies d JOIN resource_versions v
      ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
      AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
      AND d.version_id=NEW.consumer_version_id AND d.target_resource_id=mapping.key::uuid
      AND v.object_type=policy.attributes->'definition'->>'subject_type')
   THEN RAISE EXCEPTION 'Certification policy dependency or applicability mismatch'; END IF;
   controls := array_append(controls,policy.resource_id);
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_object_keys(requirements) AS keys(key)
    WHERE key::uuid=ANY(controls))
   OR EXISTS(SELECT 1 FROM resource_dependencies d WHERE d.tenant_id=NEW.tenant_id
     AND d.version_id=NEW.consumer_version_id AND NOT (d.target_resource_id=ANY(controls))
     AND NOT (requirements ? d.target_resource_id::text))
   OR EXISTS(SELECT target_resource_id FROM resource_dependencies
     WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id
     GROUP BY target_resource_id HAVING count(DISTINCT target_version_id)>1)
  THEN RAISE EXCEPTION 'Certification mappings must cover all and only material pins'; END IF;
 ELSIF NEW.payload ? 'certification_requirements' THEN
  RAISE EXCEPTION 'Unexpected certification requirements';
 END IF;

 IF jsonb_typeof(NEW.payload->'inputs') IS DISTINCT FROM 'array' OR
 jsonb_array_length(NEW.payload->'inputs') <> (SELECT count(DISTINCT target_version_id) FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id)
 THEN RAISE EXCEPTION 'Incomplete consumption input pins'; END IF;
 IF (SELECT count(DISTINCT value->'subject'->>'version_id') FROM jsonb_array_elements(NEW.payload->'inputs')) <> jsonb_array_length(NEW.payload->'inputs')
 THEN RAISE EXCEPTION 'Duplicate consumption input pins'; END IF;
 FOR input IN SELECT value FROM jsonb_array_elements(NEW.payload->'inputs') LOOP
  SELECT v.* INTO source FROM resource_versions v
  WHERE v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp())
 AND v.tenant_id=NEW.tenant_id AND v.version_id=(input->'subject'->>'version_id')::uuid
  AND v.resource_id=(input->'subject'->>'resource_id')::uuid;
  SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id AND version_id=source.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
  input_minimum := CASE WHEN source.resource_id=ANY(controls) THEN 'AUTHORITATIVE' ELSE minimum END;
  IF (input->>'authority_control')::boolean IS DISTINCT FROM true AND source.resource_id=ANY(controls)
   OR input ? 'authority_control' AND NOT (source.resource_id=ANY(controls))
  THEN RAISE EXCEPTION 'Consumption control role mismatch'; END IF;
  IF source.version_id IS NULL OR source.authority_state<>'APPROVED' OR event.event_id IS NULL
  OR input->>'event_id' IS DISTINCT FROM event.event_id::text
  OR input->>'content_hash' IS DISTINCT FROM source.content_hash
  OR input->'attributes' IS DISTINCT FROM source.attributes
  OR input->>'access_entity' IS DISTINCT FROM source.access_entity
  OR (NEW.access_entity<>'__TENANT__' AND source.access_entity NOT IN (NEW.access_entity,'__PLATFORM__'))
  OR (array_position(progression,event.payload->>'target_state')>=array_position(progression,input_minimum)) IS NOT TRUE
  OR event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE'
  OR NOT EXISTS(SELECT 1 FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id AND target_version_id=source.version_id AND target_resource_id=source.resource_id)
  THEN RAISE EXCEPTION 'Invalid or unauthorized consumption input'; END IF;
  IF event.payload->>'target_state'='CERTIFIED' THEN
   expected_certification := g8_current_event_certification(NEW.tenant_id,event);
   IF NEW.payload->>'contract_version' IS DISTINCT FROM 'guarded-consumption/3'
    OR input->'certification' IS DISTINCT FROM expected_certification
    OR (minimum='CERTIFIED' AND NOT (source.resource_id=ANY(controls))
      AND expected_certification->'contract' IS DISTINCT FROM requirements->source.resource_id::text)
   THEN RAISE EXCEPTION 'Input certification proof mismatch'; END IF;
  ELSIF input ? 'certification' THEN
   RAISE EXCEPTION 'Unexpected input certification proof';
  END IF;

 END LOOP;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION guard_consumption_upstream() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE versions uuid[]; item jsonb; ancestor resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE;
BEGIN
 WITH RECURSIVE lineage(version_id) AS (
  SELECT target_version_id FROM resource_dependencies
  WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id
  UNION
  SELECT d.target_version_id FROM resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
  WHERE d.tenant_id=NEW.tenant_id
 ) SELECT coalesce(array_agg(version_id),'{}'::uuid[]) INTO versions FROM lineage
 WHERE version_id<>NEW.consumer_version_id;
 IF jsonb_typeof(NEW.payload->'upstream_authority') IS DISTINCT FROM 'array'
 OR cardinality(versions)>999
 OR jsonb_array_length(NEW.payload->'upstream_authority')<>cardinality(versions)
 OR (SELECT count(DISTINCT value->>'version_id') FROM jsonb_array_elements(NEW.payload->'upstream_authority'))<>cardinality(versions)
 THEN RAISE EXCEPTION 'Incomplete transitive authority proof'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.payload->'upstream_authority') LOOP
  SELECT v.* INTO ancestor FROM resource_versions v
  WHERE v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp())
 AND v.tenant_id=NEW.tenant_id AND v.version_id=(item->>'version_id')::uuid;
  SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id
  AND version_id=ancestor.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
  IF ancestor.version_id IS NULL OR NOT (ancestor.version_id=ANY(versions))
  OR ancestor.resource_id::text IS DISTINCT FROM item->>'resource_id'
  OR ancestor.content_hash IS DISTINCT FROM item->>'content_hash'
  OR ancestor.access_entity IS DISTINCT FROM item->>'access_entity'
  OR ancestor.authority_state<>'APPROVED' OR ancestor.valid_from>clock_timestamp()
  OR (ancestor.valid_to IS NOT NULL AND ancestor.valid_to<=clock_timestamp())
  OR event.event_id::text IS DISTINCT FROM item->>'event_id'
  OR (NEW.access_entity<>'__TENANT__' AND ancestor.access_entity NOT IN (NEW.access_entity,'__PLATFORM__'))
  OR (event.event_id IS NOT NULL AND (event.payload->>'target_state' IN ('REVOKED','SUPERSEDED')
      OR event.payload->>'availability_state'<>'AVAILABLE'))
  THEN RAISE EXCEPTION 'Upstream authority unavailable or proof mismatch'; END IF;
  IF event.payload->>'target_state'='CERTIFIED' THEN
   PERFORM g8_current_event_certification(NEW.tenant_id,event);
  END IF;

 END LOOP;
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(38);
COMMIT;
