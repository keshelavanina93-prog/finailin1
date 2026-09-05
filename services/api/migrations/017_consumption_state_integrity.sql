BEGIN;
CREATE FUNCTION guard_consumption_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE input jsonb; event resource_lifecycle_events%ROWTYPE;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND version_id=NEW.consumer_version_id AND valid_from<=clock_timestamp()
 AND (valid_to IS NULL OR valid_to>clock_timestamp()))
 THEN RAISE EXCEPTION 'Consumer outside effective interval'; END IF;
 FOR input IN SELECT value FROM jsonb_array_elements(NEW.payload->'inputs') LOOP
  SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id
  AND event_id=(input->>'event_id')::uuid;
  IF input->>'authority_state' IS DISTINCT FROM event.payload->>'target_state'
  OR input->>'epistemic_state' IS DISTINCT FROM event.payload->>'epistemic_state'
  OR input->>'business_state' IS DISTINCT FROM event.payload->>'business_state'
  OR input->>'availability_state' IS DISTINCT FROM event.payload->>'availability_state'
  OR NOT EXISTS(SELECT 1 FROM resource_versions WHERE tenant_id=NEW.tenant_id
    AND version_id=(input->'subject'->>'version_id')::uuid AND valid_from<=clock_timestamp()
    AND (valid_to IS NULL OR valid_to>clock_timestamp()))
  THEN RAISE EXCEPTION 'Consumption state differs from retained event or effective interval'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER consumption_state_integrity BEFORE INSERT ON guarded_consumption_receipts
 FOR EACH ROW EXECUTE FUNCTION guard_consumption_state();
INSERT INTO schema_migrations VALUES(17);
COMMIT;
