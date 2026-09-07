BEGIN;
CREATE FUNCTION guard_transformation_review_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition jsonb; declared jsonb; compiled jsonb;
BEGIN
 IF NEW.definition_version <> 'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan';
 SELECT attributes INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND version_id=(compiled->'request'->'transformation'->>'version_id')::uuid;
 declared := nullif(definition->'publication_review','null'::jsonb);
 IF compiled->'publication_review' IS DISTINCT FROM declared
 THEN RAISE EXCEPTION 'Publication review must match the reviewed definition'; END IF;
 IF declared IS NOT NULL AND (
  declared IS DISTINCT FROM jsonb_build_object('question',declared->>'question')
  OR (length(btrim(declared->>'question')) BETWEEN 10 AND 2000) IS NOT TRUE)
 THEN RAISE EXCEPTION 'A meaningful publication review question is required'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_review_intent_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_review_intent();

CREATE FUNCTION guard_transformation_publication_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run workflow_requests%ROWTYPE; task workflow_events%ROWTYPE; decision workflow_events%ROWTYPE;
 declared jsonb; expected jsonb; cancelled boolean; published boolean;
BEGIN
 SELECT * INTO run FROM workflow_requests WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id;
 IF run.definition_version IS DISTINCT FROM 'transformation-functions/1' THEN RETURN NEW; END IF;
 declared := run.payload->'compiled_plan'->'publication_review';
 IF declared IS NULL THEN
  IF NEW.event_id LIKE 'publication-review:%'
  THEN RAISE EXCEPTION 'Review event requires a reviewed publication gate'; END IF;
  RETURN NEW;
 END IF;
 -- Order decisions, cancellation and publication on the same durable run.
 PERFORM pg_advisory_xact_lock(hashtextextended('transformation-review:'||NEW.tenant_id::text||':'||NEW.workflow_id,0));
 SELECT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND payload->>'command'='cancel') INTO cancelled;
 SELECT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='publication:0') INTO published;
 SELECT * INTO task FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='publication-review:task';
 SELECT * INTO decision FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='publication-review:decision';
 IF NEW.event_id='publication-review:task' THEN
  SELECT jsonb_agg(jsonb_build_object('output_id',o->>'output_id','node_id',o->>'node_id',
   'invocation_id',e.payload->'output'->>'invocation_id',
   'receipt_hash',e.payload->'output'->>'receipt_hash','run_id',e.payload->'output'->>'run_id')
   ORDER BY o->>'output_id') INTO expected
  FROM jsonb_array_elements(run.payload->'compiled_plan'->'outputs') o
  JOIN workflow_events e ON e.tenant_id=NEW.tenant_id AND e.workflow_id=NEW.workflow_id
   AND e.event_id='node:'||(o->>'node_id')||':terminal' AND e.payload->>'state'='COMPLETED';
  IF cancelled OR published OR NEW.exact_scope IS DISTINCT FROM run.exact_scope
   OR NEW.payload->>'state' IS DISTINCT FROM 'PENDING'
   OR NEW.payload->>'question' IS DISTINCT FROM declared->>'question'
   OR NEW.payload->'outputs' IS DISTINCT FROM expected
   OR jsonb_array_length(expected) IS DISTINCT FROM jsonb_array_length(run.payload->'compiled_plan'->'outputs')
   OR (NEW.payload->>'task_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-5[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$') IS NOT TRUE
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(run.payload->'compiled_plan'->'nodes') n
    WHERE NOT EXISTS(SELECT 1 FROM workflow_events e WHERE e.tenant_id=NEW.tenant_id
     AND e.workflow_id=NEW.workflow_id AND e.event_id='node:'||(n->>'node_id')||':terminal'
     AND e.payload->>'state'='COMPLETED'))
  THEN RAISE EXCEPTION 'Review task requires complete exact retained outputs'; END IF;
 ELSIF NEW.event_id='publication-review:decision' THEN
  IF cancelled OR published OR task.event_id IS NULL
   OR NEW.exact_scope IS DISTINCT FROM run.exact_scope
   OR NEW.payload->>'task_id' IS DISTINCT FROM task.payload->>'task_id'
   OR (NEW.payload->>'state' IN ('APPROVED','REJECTED')) IS NOT TRUE
   OR (length(btrim(NEW.payload->>'reason')) BETWEEN 10 AND 2000) IS NOT TRUE
   OR (NEW.payload->>'decision_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') IS NOT TRUE
   OR coalesce(NEW.payload->>'actor_id','')=''
   OR NEW.payload->>'actor_id'=run.actor_id
   OR NEW.payload->>'actor_id' IS DISTINCT FROM current_setting('finai.actor_id',true)
   OR (coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb ? 'review') IS NOT TRUE
  THEN RAISE EXCEPTION 'Independent authorized decision on the pending task required'; END IF;
 ELSIF NEW.event_id LIKE 'publication-review:%' THEN
  RAISE EXCEPTION 'Undeclared publication review event';
 ELSIF NEW.payload->>'state'='PUBLISHED' THEN
  IF cancelled OR task.event_id IS NULL OR decision.payload->>'state' IS DISTINCT FROM 'APPROVED'
  THEN RAISE EXCEPTION 'Publication requires an approved uncancelled review'; END IF;
 ELSIF NEW.payload->>'command'='cancel' AND published THEN
  RAISE EXCEPTION 'Published evidence cannot be cancelled retroactively';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_publication_review_integrity BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_publication_review();
INSERT INTO schema_migrations VALUES(49);
COMMIT;
