BEGIN;
CREATE TABLE guarded_consumption_receipts (
 tenant_id uuid NOT NULL, consumption_id uuid NOT NULL,
 consumer_resource_id uuid NOT NULL, consumer_version_id uuid NOT NULL,
 access_entity text NOT NULL, actor_id text NOT NULL,
 request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 proof_hash text NOT NULL CHECK(proof_hash ~ '^[a-f0-9]{64}$'),
 payload jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,consumption_id),
 FOREIGN KEY(tenant_id,consumer_resource_id,consumer_version_id)
 REFERENCES resource_versions(tenant_id,resource_id,version_id)
);
ALTER TABLE guarded_consumption_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE guarded_consumption_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY consumption_access ON guarded_consumption_receipts
 USING(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR access_entity='__PLATFORM__' OR
 (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__') AND
 access_entity=current_setting('finai.entity_id',true))))
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR
 (access_entity NOT IN ('__TENANT__','__TENANT_RESTRICTED__','__PLATFORM__') AND
 access_entity=current_setting('finai.entity_id',true))));
GRANT SELECT,INSERT ON guarded_consumption_receipts TO finai_runtime;
CREATE TRIGGER immutable_consumption BEFORE UPDATE OR DELETE OR TRUNCATE
 ON guarded_consumption_receipts FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE FUNCTION guard_consumption_proof() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE consumer resource_versions%ROWTYPE; input jsonb; source resource_versions%ROWTYPE;
 event resource_lifecycle_events%ROWTYPE; required text; minimum text;
 progression text[] := ARRAY['OBSERVED','PARSED','MAPPED_CANDIDATE','VALIDATED','RECONCILED','APPROVED','AUTHORITATIVE'];
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 SELECT v.* INTO consumer FROM resource_versions v JOIN resource_heads h USING(tenant_id,resource_id,version_id)
 WHERE v.tenant_id=NEW.tenant_id AND v.resource_id=NEW.consumer_resource_id AND v.version_id=NEW.consumer_version_id;
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
  SELECT v.* INTO source FROM resource_versions v JOIN resource_heads h USING(tenant_id,resource_id,version_id)
  WHERE v.tenant_id=NEW.tenant_id AND v.version_id=(input->'subject'->>'version_id')::uuid
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
CREATE TRIGGER consumption_integrity BEFORE INSERT ON guarded_consumption_receipts
 FOR EACH ROW EXECUTE FUNCTION guard_consumption_proof();
INSERT INTO schema_migrations VALUES(16);
COMMIT;
