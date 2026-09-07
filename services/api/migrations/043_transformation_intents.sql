BEGIN;
-- Verify canonical orchestration identity, not execution of Function code.
CREATE FUNCTION guard_transformation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; request jsonb; definition resource_versions%ROWTYPE;
 function resource_versions%ROWTYPE; node jsonb; declared jsonb; dependency jsonb;
 ids text[]; key text;
BEGIN
 IF NEW.definition_version<>'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan'; request := compiled->'request';
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=(request->'transformation'->>'resource_id')::uuid
 AND version_id=(request->'transformation'->>'version_id')::uuid;
 IF definition.version_id IS NULL OR definition.object_type<>'TransformationDefinition'
 OR definition.authority_state<>'APPROVED'
 OR definition.access_entity IS DISTINCT FROM NEW.exact_scope->>'legal_entity_id'
 OR g8_effective_version_id(NEW.tenant_id,definition.resource_id,statement_timestamp())
    IS DISTINCT FROM definition.version_id
 OR NEW.exact_scope->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR compiled->'exact_scope' IS DISTINCT FROM NEW.exact_scope
 OR NEW.workflow_id IS DISTINCT FROM 'transformation:'||(request->>'request_id')
 OR compiled->>'contract' IS DISTINCT FROM 'transformation-plan/1'
 OR compiled->>'mode' IS DISTINCT FROM 'EVIDENCE_ANALYSIS_ONLY'
 OR compiled->>'dependency_semantics' IS DISTINCT FROM 'COMPLETION_BARRIER_ONLY'
 OR compiled->'current_use_authorized' IS DISTINCT FROM 'false'::jsonb
 OR compiled->'business_effect_authorized' IS DISTINCT FROM 'false'::jsonb
 OR (compiled->>'plan_hash' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR (NEW.payload->>'request_hash' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR NEW.payload->'definition'->>'version' IS DISTINCT FROM NEW.definition_version
 OR NEW.payload->'definition'->'nodes' IS DISTINCT FROM compiled->'nodes'
 OR compiled->'transformation' IS DISTINCT FROM jsonb_build_object(
  'resource_id',definition.resource_id::text,'version_id',definition.version_id::text,
  'content_hash',definition.content_hash)
 OR request->>'valid_at' IS NULL OR request->>'known_at' IS NULL
 OR (request->>'known_at')::timestamptz>statement_timestamp()
 OR compiled->'outputs' IS DISTINCT FROM definition.attributes->'definition'->'outputs'
 THEN RAISE EXCEPTION 'Exact canonical transformation intent required'; END IF;
 IF jsonb_typeof(compiled->'nodes') IS DISTINCT FROM 'array'
 OR jsonb_typeof(compiled->'node_order') IS DISTINCT FROM 'array'
 OR jsonb_array_length(compiled->'nodes') NOT BETWEEN 1 AND 32
 OR jsonb_array_length(compiled->'nodes')<>jsonb_array_length(definition.attributes->'definition'->'nodes')
 OR jsonb_array_length(compiled->'node_order')<>jsonb_array_length(compiled->'nodes')
 THEN RAISE EXCEPTION 'Invalid transformation node set'; END IF;
 SELECT array_agg(value#>>'{}') INTO ids FROM jsonb_array_elements(compiled->'node_order');
 IF cardinality(ids)<>(SELECT count(DISTINCT id) FROM unnest(ids) id)
 OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(compiled->'nodes'))<>cardinality(ids)
 OR (SELECT count(DISTINCT value->'invocation'->>'request_id') FROM jsonb_array_elements(compiled->'nodes'))<>cardinality(ids)
 THEN RAISE EXCEPTION 'Duplicate transformation node or invocation identity'; END IF;
 FOR node IN SELECT value FROM jsonb_array_elements(compiled->'nodes') LOOP
  SELECT value INTO declared FROM jsonb_array_elements(definition.attributes->'definition'->'nodes')
   WHERE value->>'node_id'=node->>'node_id';
  IF declared IS NULL OR NOT (node->>'node_id'=ANY(ids))
   OR node->'depends_on' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(value ORDER BY value),'[]'::jsonb)
     FROM jsonb_array_elements(coalesce(declared->'depends_on','[]'::jsonb)))
   OR jsonb_array_length(node->'depends_on')<>(SELECT count(DISTINCT value)
     FROM jsonb_array_elements(node->'depends_on'))
   OR node->'invocation'->'valid_at' IS DISTINCT FROM request->'valid_at'
   OR node->'invocation'->'known_at' IS DISTINCT FROM request->'known_at'
   OR node->'invocation'->'offset' IS DISTINCT FROM coalesce(declared->'offset','0'::jsonb)
   OR node->'invocation'->'limit' IS DISTINCT FROM coalesce(declared->'limit','50'::jsonb)
  THEN RAISE EXCEPTION 'Transformation node differs from canonical definition'; END IF;
  FOR dependency IN SELECT value FROM jsonb_array_elements(node->'depends_on') LOOP
   IF (array_position(ids,dependency#>>'{}')<array_position(ids,node->>'node_id')) IS NOT TRUE
   THEN RAISE EXCEPTION 'Transformation dependency order is invalid'; END IF;
  END LOOP;
  SELECT v.* INTO function FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND d.relation='TRANSFORMATION_FUNCTION:'||(node->>'node_id')
   AND v.resource_id=(declared->>'function_id')::uuid;
  IF function.version_id IS NULL OR function.object_type<>'FunctionDefinition'
   OR node->'function' IS DISTINCT FROM jsonb_build_object('resource_id',function.resource_id::text,
       'version_id',function.version_id::text,'content_hash',function.content_hash)
   OR node->'invocation'->'function' IS DISTINCT FROM jsonb_build_object(
       'resource_id',function.resource_id::text,'version_id',function.version_id::text)
   OR node->'function_plan'->'function' IS DISTINCT FROM node->'function'
   OR node->'function_plan'->'request' IS DISTINCT FROM node->'invocation'
   OR node->'function_plan'->'exact_scope' IS DISTINCT FROM NEW.exact_scope
  THEN RAISE EXCEPTION 'Transformation Function pin mismatch'; END IF;
 END LOOP;
 IF NEW.payload->'definition'->'outputs' IS DISTINCT FROM (
  SELECT jsonb_object_agg(value->>'output_id','function-invocation/1')
  FROM jsonb_array_elements(compiled->'outputs'))
 THEN RAISE EXCEPTION 'Transformation publication slots differ from canonical definition'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_intent_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_intent();
CREATE FUNCTION guard_transformation_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run workflow_requests%ROWTYPE; node jsonb; declared jsonb; result function_invocation_results%ROWTYPE;
 invocation function_invocations%ROWTYPE; expected jsonb; staged workflow_events%ROWTYPE;
 output jsonb; dependency jsonb;
BEGIN
 SELECT * INTO run FROM workflow_requests WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id;
 IF run.definition_version IS DISTINCT FROM 'transformation-functions/1' THEN RETURN NEW; END IF;
 IF NEW.exact_scope IS DISTINCT FROM run.exact_scope THEN RAISE EXCEPTION 'Transformation event scope mismatch'; END IF;
 IF NEW.payload->>'state' IN ('COMPLETED','FAILED','RUNNING') THEN
  SELECT value INTO node FROM jsonb_array_elements(run.payload->'compiled_plan'->'nodes')
   WHERE value->>'node_id'=NEW.payload->>'node';
  IF node IS NULL THEN RAISE EXCEPTION 'Undeclared transformation node event'; END IF;
  IF NEW.payload->>'state'='RUNNING' THEN
   IF NEW.event_id IS DISTINCT FROM 'node:'||(node->>'node_id')||':started'
   THEN RAISE EXCEPTION 'Invalid node start identity'; END IF;
   RETURN NEW;
  END IF;
  SELECT * INTO result FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
   AND request_id=(node->'invocation'->>'request_id')::uuid;
  SELECT * INTO invocation FROM function_invocations WHERE tenant_id=NEW.tenant_id
   AND request_id=(node->'invocation'->>'request_id')::uuid;
  expected := jsonb_build_object('invocation_id',result.request_id::text,'receipt_hash',result.proof_hash);
  IF result.status='SUCCEEDED' THEN expected := expected || jsonb_build_object('run_id',result.run_id); END IF;
  IF result.request_id IS NULL OR result.exact_scope IS DISTINCT FROM NEW.exact_scope
   OR result.actor_id IS DISTINCT FROM run.actor_id
   OR invocation.request IS DISTINCT FROM node->'invocation'
   OR invocation.plan IS DISTINCT FROM node->'function_plan'
   OR NEW.payload->'output' IS DISTINCT FROM expected
   OR NEW.event_id IS DISTINCT FROM 'node:'||(node->>'node_id')||':terminal'
   OR NEW.payload->>'state' IS DISTINCT FROM (CASE WHEN result.status='SUCCEEDED' THEN 'COMPLETED' ELSE 'FAILED' END)
   OR NEW.payload->'new_run_required' IS DISTINCT FROM to_jsonb(result.status<>'SUCCEEDED')
  THEN RAISE EXCEPTION 'Node completion must match retained Function receipt'; END IF;
  FOR dependency IN SELECT value FROM jsonb_array_elements(node->'depends_on') LOOP
   IF NOT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id
    AND event_id='node:'||(dependency#>>'{}')||':terminal' AND payload->>'state'='COMPLETED')
   THEN RAISE EXCEPTION 'Node completion barrier missing'; END IF;
  END LOOP;
 ELSIF NEW.payload->>'state'='STAGED' THEN
  SELECT value INTO declared FROM jsonb_array_elements(run.payload->'compiled_plan'->'outputs')
   WHERE value->>'output_id'=NEW.payload->>'node';
  SELECT * INTO staged FROM workflow_events WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id
   AND event_id='node:'||(declared->>'node_id')||':terminal';
  IF declared IS NULL OR staged.event_id IS NULL OR staged.payload->>'state' IS DISTINCT FROM 'COMPLETED'
   OR NEW.payload->'value' IS DISTINCT FROM staged.payload->'output'
   OR NEW.payload->>'artifact_type' IS DISTINCT FROM 'function-invocation/1'
   OR NEW.payload->'generation' IS DISTINCT FROM '0'::jsonb
  THEN RAISE EXCEPTION 'Staged output requires exact completed Function evidence'; END IF;
 ELSIF NEW.payload->>'state'='PUBLISHED' THEN
  IF NEW.event_id IS DISTINCT FROM 'publication:0'
   OR NEW.payload->'manifest'->>'workflow_id' IS DISTINCT FROM NEW.workflow_id
   OR NEW.payload->'manifest'->>'authority' IS DISTINCT FROM 'EXECUTION_ONLY'
   OR NEW.payload->'manifest'->'generation' IS DISTINCT FROM '0'::jsonb
   OR jsonb_typeof(NEW.payload->'manifest'->'outputs') IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.payload->'manifest'->'outputs')<>
      jsonb_array_length(run.payload->'compiled_plan'->'outputs')
   OR (SELECT count(DISTINCT value->>'slot') FROM jsonb_array_elements(NEW.payload->'manifest'->'outputs'))<>
      jsonb_array_length(run.payload->'compiled_plan'->'outputs')
  THEN RAISE EXCEPTION 'Invalid transformation publication set'; END IF;
  FOR node IN SELECT value FROM jsonb_array_elements(run.payload->'compiled_plan'->'nodes') LOOP
   IF NOT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id
    AND event_id='node:'||(node->>'node_id')||':terminal' AND payload->>'state'='COMPLETED')
   THEN RAISE EXCEPTION 'Unfinished transformation cannot publish'; END IF;
  END LOOP;
  FOR output IN SELECT value FROM jsonb_array_elements(NEW.payload->'manifest'->'outputs') LOOP
   SELECT * INTO staged FROM workflow_events WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id
    AND event_id=output->>'event_id';
   IF staged.event_id IS NULL OR staged.payload->>'state' IS DISTINCT FROM 'STAGED'
    OR staged.payload->>'node' IS DISTINCT FROM output->>'slot'
    OR staged.payload->'value' IS DISTINCT FROM output->'value'
    OR staged.payload->'sha256' IS DISTINCT FROM output->'sha256'
    OR output->>'artifact_type' IS DISTINCT FROM 'function-invocation/1'
   THEN RAISE EXCEPTION 'Publication requires retained exact output references'; END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_event_integrity BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_event();
INSERT INTO schema_migrations VALUES(43);
COMMIT;
