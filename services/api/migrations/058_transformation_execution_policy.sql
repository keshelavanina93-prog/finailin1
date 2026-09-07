BEGIN;
CREATE FUNCTION guard_transformation_execution_policy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; declared jsonb; policy jsonb;
BEGIN
 IF NEW.definition_version <> 'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan';
 policy := compiled->'execution_policy';
 SELECT nullif(attributes->'execution_policy','null'::jsonb) INTO declared
 FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(compiled->'transformation'->>'resource_id')::uuid
  AND version_id=(compiled->'transformation'->>'version_id')::uuid;
 IF declared IS NULL THEN
  IF policy IS NOT NULL THEN
   RAISE EXCEPTION 'Concurrent execution requires a reviewed policy';
  END IF;
  RETURN NEW;
 END IF;
 IF policy IS DISTINCT FROM declared
  OR jsonb_typeof(policy) IS DISTINCT FROM 'object'
  OR policy IS DISTINCT FROM jsonb_build_object('max_concurrent_nodes',policy->'max_concurrent_nodes')
  OR jsonb_typeof(policy->'max_concurrent_nodes') IS DISTINCT FROM 'number'
  OR (policy->>'max_concurrent_nodes' ~ '^[1-4]$') IS NOT TRUE
 THEN RAISE EXCEPTION 'Execution policy differs from the exact reviewed concurrency limit'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_execution_policy_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_execution_policy();
-- Review decisions can hold the review lock before inserting events. Acquire locks in
-- that same order before budget/binding/publication guards, including legacy runs.
CREATE FUNCTION lock_transformation_event_order() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM workflow_requests WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND definition_version='transformation-functions/1')
 THEN RETURN NEW; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'transformation-review:'||NEW.tenant_id::text||':'||NEW.workflow_id,0));
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text||':'||NEW.workflow_id,45));
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_00_execution_lock_order BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION lock_transformation_event_order();
INSERT INTO schema_migrations VALUES(58);
COMMIT;
