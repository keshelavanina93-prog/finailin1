BEGIN;
-- Event admission uses the effective policy; publication heads remain editing authority.
CREATE OR REPLACE FUNCTION guard_source_event_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE stream resource_versions%ROWTYPE; high timestamptz; allowed integer; future integer; expected_watermark timestamptz;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 SELECT v.* INTO stream FROM resource_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.resource_id=NEW.stream_id AND v.version_id=NEW.stream_version_id
 AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,clock_timestamp());
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
INSERT INTO schema_migrations VALUES(33);
COMMIT;
