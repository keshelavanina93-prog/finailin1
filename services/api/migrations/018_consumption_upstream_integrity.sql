BEGIN;
CREATE FUNCTION guard_consumption_upstream() RETURNS trigger LANGUAGE plpgsql AS $$
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
  SELECT v.* INTO ancestor FROM resource_versions v JOIN resource_heads h USING(tenant_id,resource_id,version_id)
  WHERE v.tenant_id=NEW.tenant_id AND v.version_id=(item->>'version_id')::uuid;
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
CREATE TRIGGER consumption_upstream_integrity BEFORE INSERT ON guarded_consumption_receipts
 FOR EACH ROW EXECUTE FUNCTION guard_consumption_upstream();
INSERT INTO schema_migrations VALUES(18);
COMMIT;
