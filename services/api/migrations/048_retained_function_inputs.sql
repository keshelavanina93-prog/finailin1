BEGIN;
-- Add data-input integrity without changing completion-barrier semantics or old receipts.
CREATE FUNCTION guard_transformation_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; definition jsonb; node jsonb; declared jsonb; source jsonb;
 binding jsonb; has_inputs boolean := false;
BEGIN
 IF NEW.definition_version <> 'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan';
 SELECT attributes->'definition' INTO definition FROM resource_versions
 WHERE tenant_id=NEW.tenant_id
 AND version_id=(compiled->'request'->'transformation'->>'version_id')::uuid;
 FOR node IN SELECT value FROM jsonb_array_elements(compiled->'nodes') LOOP
  SELECT value INTO declared FROM jsonb_array_elements(definition->'nodes')
   WHERE value->>'node_id'=node->>'node_id';
  binding := nullif(declared->'input_binding','null'::jsonb);
  IF binding IS NULL THEN
   IF node ? 'input_binding' OR node->'invocation' ? 'input_result'
   THEN RAISE EXCEPTION 'Undeclared transformation data input'; END IF;
   CONTINUE;
  END IF;
  has_inputs := true;
  SELECT value INTO source FROM jsonb_array_elements(compiled->'nodes')
   WHERE value->>'node_id'=binding->>'upstream_node_id';
  IF binding IS DISTINCT FROM jsonb_build_object('upstream_node_id',binding->>'upstream_node_id')
   OR node->'input_binding' IS DISTINCT FROM binding
   OR source IS NULL OR source->>'node_id'=node->>'node_id'
   OR (node->'depends_on' ? (source->>'node_id')) IS NOT TRUE
   OR node->'invocation'->'input_result' IS DISTINCT FROM jsonb_build_object(
       'invocation_id',source->'invocation'->>'request_id')
   OR node->'invocation'->'offset' IS DISTINCT FROM '0'::jsonb
   OR (node->'invocation'->>'limit')::int < (source->'invocation'->>'limit')::int
   OR node->'function_plan'->'object_set' IS DISTINCT FROM source->'function_plan'->'object_set'
   OR node->'function_plan'->'object_set' IS NULL
   OR node->'function_plan'->'implementation'->>'implementation_id'
       IS DISTINCT FROM 'ontology.object-set-derived/v1'
   OR source->'function_plan'->'implementation'->>'implementation_id'
       IS DISTINCT FROM 'ontology.object-set-derived/v1'
  THEN RAISE EXCEPTION 'Transformation input must pin a compatible declared upstream step'; END IF;
 END LOOP;
 IF has_inputs THEN
  IF compiled->>'input_semantics' IS DISTINCT FROM 'EXPLICIT_RETAINED_RESULT'
  THEN RAISE EXCEPTION 'Explicit retained input semantics required'; END IF;
 ELSIF compiled ? 'input_semantics' THEN
  RAISE EXCEPTION 'Input semantics require a declared binding';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_input_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_inputs();

CREATE FUNCTION guard_function_input_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference jsonb; source function_invocation_results%ROWTYPE;
 source_intent function_invocations%ROWTYPE; output fact_calculation_runs%ROWTYPE;
BEGIN
 IF NOT (NEW.request ? 'input_result') THEN RETURN NEW; END IF;
 reference := NEW.request->'input_result';
 IF reference IS DISTINCT FROM jsonb_build_object('invocation_id',reference->>'invocation_id')
  OR (reference->>'invocation_id')::uuid=NEW.request_id
 THEN RAISE EXCEPTION 'Invalid retained Function input identity'; END IF;
 SELECT * INTO source FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(reference->>'invocation_id')::uuid;
 SELECT * INTO source_intent FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=source.request_id;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=source.run_id;
 IF source.request_id IS NULL OR source.status IS DISTINCT FROM 'SUCCEEDED'
  OR source.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR source_intent.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR output.run_id IS NULL OR output.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR NEW.plan->'implementation'->>'implementation_id' IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR source_intent.plan->'implementation'->>'implementation_id' IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR NEW.plan->'object_set' IS DISTINCT FROM source_intent.plan->'object_set'
  OR NEW.request->'valid_at' IS DISTINCT FROM source_intent.request->'valid_at'
  OR NEW.request->'known_at' IS DISTINCT FROM source_intent.request->'known_at'
  OR NEW.request->'offset' IS DISTINCT FROM '0'::jsonb
  OR jsonb_typeof(output.payload->'objects') IS DISTINCT FROM 'array'
  OR jsonb_array_length(output.payload->'objects') > (NEW.request->>'limit')::int
 THEN RAISE EXCEPTION 'Function input requires compatible succeeded exact-scope evidence'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER function_input_intent_integrity BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_function_input_intent();

CREATE FUNCTION guard_function_input_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; source function_invocation_results%ROWTYPE;
 source_output fact_calculation_runs%ROWTYPE; output fact_calculation_runs%ROWTYPE;
BEGIN
 IF NEW.status <> 'SUCCEEDED' THEN RETURN NEW; END IF;
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 IF NOT (intent.request ? 'input_result') THEN
  IF output.payload ? 'input_result' THEN RAISE EXCEPTION 'Undeclared retained input result'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO source FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(intent.request->'input_result'->>'invocation_id')::uuid;
 SELECT * INTO source_output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=source.run_id;
 IF source.request_id IS NULL OR source.status IS DISTINCT FROM 'SUCCEEDED'
  OR source.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR source_output.run_id IS NULL OR source_output.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR output.payload->'input_result' IS DISTINCT FROM jsonb_build_object(
      'invocation_id',source.request_id::text,'receipt_hash',source.proof_hash,'run_id',source.run_id)
  OR output.payload->'objects' IS DISTINCT FROM source_output.payload->'objects'
  OR output.payload->'query' IS DISTINCT FROM source_output.payload->'query'
 THEN RAISE EXCEPTION 'Function output must preserve exact retained input objects and provenance'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER function_input_result_integrity BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_function_input_result();
INSERT INTO schema_migrations VALUES(48);
COMMIT;
