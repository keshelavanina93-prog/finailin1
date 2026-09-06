BEGIN;
-- Editing heads retain optimistic concurrency semantics. Current-use authority
-- resolves the last recorded version effective at the requested instant instead.
-- State is deliberately not filtered here: a revoked winner must fail closed.
CREATE FUNCTION g8_effective_version_id(tenant uuid, resource uuid, at_time timestamptz)
RETURNS uuid LANGUAGE sql STABLE SECURITY INVOKER AS $$
 SELECT version_id FROM resource_versions
 WHERE tenant_id=tenant AND resource_id=resource AND system_from<=at_time
 AND valid_from<=at_time AND (valid_to IS NULL OR valid_to>at_time)
 ORDER BY system_from DESC,version_id LIMIT 1
$$;
GRANT EXECUTE ON FUNCTION g8_effective_version_id(uuid,uuid,timestamptz) TO finai_runtime;
CREATE OR REPLACE FUNCTION g8_lifecycle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE req resource_lifecycle_requests%ROWTYPE; ver resource_versions%ROWTYPE;
 prior resource_lifecycle_events%ROWTYPE; wanted text; previous text;
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
    OR NOT EXISTS(SELECT 1 FROM resource_lifecycle_decisions WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id AND decision='APPROVED')
   THEN RAISE EXCEPTION 'Approved lifecycle request required'; END IF;
  END IF;
 END IF;
 SELECT * INTO prior FROM resource_lifecycle_events WHERE tenant_id=req.tenant_id AND version_id=req.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
 IF (req.payload->>'expected_event_id') IS DISTINCT FROM prior.event_id::text THEN RAISE EXCEPTION 'Lifecycle compare and swap failed'; END IF;
 previous := prior.payload->>'target_state'; wanted := req.payload->>'target_state';
 IF NOT ((previous IS NULL AND wanted='OBSERVED') OR
  (wanted=progression[array_position(progression,previous)+1]) OR
  (previous=ANY(progression) AND wanted=previous AND (
    req.payload->>'epistemic_state' IS DISTINCT FROM prior.payload->>'epistemic_state' OR
    req.payload->>'business_state' IS DISTINCT FROM prior.payload->>'business_state' OR
    req.payload->>'availability_state' IS DISTINCT FROM prior.payload->>'availability_state')) OR
  (previous=ANY(progression) AND wanted IN ('SUPERSEDED','REVOKED'))) IS TRUE
 THEN RAISE EXCEPTION 'Unsupported lifecycle transition'; END IF;
 IF wanted='AUTHORITATIVE' AND TG_TABLE_NAME<>'resource_lifecycle_requests' AND current_setting('finai.tenant_access',true) IS DISTINCT FROM 'true'
 THEN RAISE EXCEPTION 'Authority administrator required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM resource_versions v
 WHERE v.tenant_id=req.tenant_id AND v.resource_id=req.resource_id AND v.version_id=req.version_id
 AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp()) AND v.authority_state='APPROVED'
 AND v.valid_from<=clock_timestamp() AND (v.valid_to IS NULL OR v.valid_to>clock_timestamp()))
 THEN RAISE EXCEPTION 'Current accepted version required'; END IF;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION guard_consumption_proof() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE consumer resource_versions%ROWTYPE; input jsonb; source resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE; required text; minimum text;
 progression text[] := ARRAY['OBSERVED','PARSED','MAPPED_CANDIDATE','VALIDATED','RECONCILED','APPROVED','AUTHORITATIVE'];
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
  IF source.version_id IS NULL OR source.authority_state<>'APPROVED' OR event.event_id IS NULL
  OR input->>'event_id' IS DISTINCT FROM event.event_id::text
  OR input->>'content_hash' IS DISTINCT FROM source.content_hash
  OR input->'attributes' IS DISTINCT FROM source.attributes
  OR input->>'access_entity' IS DISTINCT FROM source.access_entity
  OR (NEW.access_entity<>'__TENANT__' AND source.access_entity NOT IN (NEW.access_entity,'__PLATFORM__'))
  OR (array_position(progression,event.payload->>'target_state')>=array_position(progression,minimum)) IS NOT TRUE
  OR event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE'
  OR NOT EXISTS(SELECT 1 FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=NEW.consumer_version_id AND target_version_id=source.version_id AND target_resource_id=source.resource_id)
  THEN RAISE EXCEPTION 'Invalid or unauthorized consumption input'; END IF;
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
 END LOOP;
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(32);
COMMIT;
