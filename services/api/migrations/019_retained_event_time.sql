BEGIN;
CREATE TABLE retained_source_events (
 tenant_id uuid NOT NULL, stream_id uuid NOT NULL, stream_version_id uuid NOT NULL,
 access_entity text NOT NULL, event_id text NOT NULL, partition_key text NOT NULL,
 event_time timestamptz NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 arrival_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 admission text NOT NULL CHECK(admission IN ('IN_WINDOW','RETAINED_LATE')),
 watermark timestamptz, payload jsonb NOT NULL, actor_id text NOT NULL,
 PRIMARY KEY(tenant_id,stream_id,event_id),
 FOREIGN KEY(tenant_id,stream_id,stream_version_id) REFERENCES resource_versions(tenant_id,resource_id,version_id),
 CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=1000000),
 CHECK(length(event_id) BETWEEN 1 AND 256 AND length(partition_key) BETWEEN 1 AND 256)
);
CREATE INDEX event_time_replay ON retained_source_events(tenant_id,stream_id,recorded_at,arrival_sequence);
ALTER TABLE retained_source_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE retained_source_events FORCE ROW LEVEL SECURITY;
CREATE POLICY event_access ON retained_source_events
 USING(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR
 (access_entity NOT IN ('__PLATFORM__','__TENANT__','__TENANT_RESTRICTED__') AND access_entity=current_setting('finai.entity_id',true))))
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true) AND
 (current_setting('finai.tenant_access',true)='true' OR
 (access_entity NOT IN ('__PLATFORM__','__TENANT__','__TENANT_RESTRICTED__') AND access_entity=current_setting('finai.entity_id',true))));
GRANT SELECT,INSERT ON retained_source_events TO finai_runtime;
GRANT USAGE,SELECT ON SEQUENCE retained_source_events_arrival_sequence_seq TO finai_runtime;
CREATE TRIGGER immutable_source_event BEFORE UPDATE OR DELETE OR TRUNCATE ON retained_source_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE FUNCTION guard_source_event_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE stream resource_versions%ROWTYPE; high timestamptz; allowed integer; future integer; expected_watermark timestamptz;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 SELECT v.* INTO stream FROM resource_versions v JOIN resource_heads h USING(tenant_id,resource_id,version_id)
 WHERE v.tenant_id=NEW.tenant_id AND v.resource_id=NEW.stream_id AND v.version_id=NEW.stream_version_id;
 IF stream.version_id IS NULL OR stream.access_entity IS DISTINCT FROM NEW.access_entity
 OR stream.access_entity='__PLATFORM__' OR stream.authority_state<>'APPROVED'
 OR stream.valid_from>clock_timestamp() OR (stream.valid_to IS NOT NULL AND stream.valid_to<=clock_timestamp())
 OR stream.attributes->>'event_time_policy_version' IS DISTINCT FROM 'event-time/1'
 OR stream.attributes->>'late_policy' IS DISTINCT FROM 'RETAIN_ONLY'
 THEN RAISE EXCEPTION 'Accepted enterprise event-time policy required'; END IF;
 allowed := (stream.attributes->>'allowed_lateness_seconds')::integer;
 future := (stream.attributes->>'allowed_future_seconds')::integer;
 IF (allowed BETWEEN 0 AND 31536000 AND future BETWEEN 0 AND 86400) IS NOT TRUE
 OR NEW.event_time>clock_timestamp()+make_interval(secs=>future)
 THEN RAISE EXCEPTION 'Event time outside accepted policy'; END IF;
 SELECT max(event_time) INTO high FROM retained_source_events
 WHERE tenant_id=NEW.tenant_id AND stream_id=NEW.stream_id AND stream_version_id=NEW.stream_version_id;
 expected_watermark := high-make_interval(secs=>allowed);
 IF NEW.watermark IS DISTINCT FROM expected_watermark
 OR NEW.admission IS DISTINCT FROM (CASE WHEN NEW.event_time<expected_watermark THEN 'RETAINED_LATE' ELSE 'IN_WINDOW' END)
 THEN RAISE EXCEPTION 'Event watermark or admission mismatch'; END IF;
 NEW.recorded_at := clock_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER source_event_integrity BEFORE INSERT ON retained_source_events
 FOR EACH ROW EXECUTE FUNCTION guard_source_event_time();
INSERT INTO schema_migrations VALUES(19);
COMMIT;
