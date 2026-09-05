BEGIN;
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
 IF NOT EXISTS(SELECT 1 FROM resource_heads h JOIN resource_versions v USING(tenant_id,resource_id,version_id)
 WHERE h.tenant_id=req.tenant_id AND h.resource_id=req.resource_id AND h.version_id=req.version_id AND v.authority_state='APPROVED'
 AND v.valid_from<=clock_timestamp() AND (v.valid_to IS NULL OR v.valid_to>clock_timestamp()))
 THEN RAISE EXCEPTION 'Current accepted version required'; END IF;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES (12);
COMMIT;
