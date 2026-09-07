BEGIN;
CREATE OR REPLACE FUNCTION guard_function_invocation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; selected resource_versions%ROWTYPE;
 source source_documents%ROWTYPE; evidence resource_versions%ROWTYPE; source_plan jsonb;
 expected_pins jsonb; expected_properties jsonb := '[]'::jsonb; property jsonb; key text;
BEGIN
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=(NEW.request->'function'->>'resource_id')::uuid
 AND version_id=(NEW.request->'function'->>'version_id')::uuid;
 IF definition.version_id IS NULL OR definition.object_type<>'FunctionDefinition'
 OR definition.authority_state<>'APPROVED'
 OR definition.access_entity IS DISTINCT FROM NEW.exact_scope->>'legal_entity_id'
 OR g8_effective_version_id(NEW.tenant_id,definition.resource_id,statement_timestamp())
    IS DISTINCT FROM definition.version_id
 OR NEW.plan->>'contract' IS DISTINCT FROM 'function-plan/1'
 OR NEW.plan->'function' IS DISTINCT FROM jsonb_build_object('resource_id',definition.resource_id::text,
    'version_id',definition.version_id::text,'content_hash',definition.content_hash)
 OR (NEW.request->>'known_at')::timestamptz>statement_timestamp()
 OR NEW.request->>'known_at' IS NULL OR NEW.request->>'valid_at' IS NULL
 THEN RAISE EXCEPTION 'Exact current company Function definition required'; END IF;
 FOREACH key IN ARRAY ARRAY['implementation_id','determinism','code_sha256','dependency_sha256'] LOOP
  IF NEW.plan->'implementation'->key IS DISTINCT FROM definition.attributes->'definition'->key
   OR definition.attributes->'definition'->key IS NULL
  THEN RAISE EXCEPTION 'Function implementation manifest mismatch'; END IF;
 END LOOP;
 SELECT coalesce(jsonb_agg(jsonb_build_object('resource_id',p.resource_id::text,
   'version_id',p.version_id::text,'content_hash',p.content_hash) ORDER BY p.version_id::text),'[]'::jsonb)
 INTO expected_pins FROM (SELECT DISTINCT v.resource_id,v.version_id,v.content_hash
 FROM resource_dependencies d JOIN resource_versions v ON v.tenant_id=d.tenant_id
 AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
 WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id) p;
 IF NEW.plan->'static_dependencies' IS DISTINCT FROM expected_pins
 OR jsonb_array_length(expected_pins)<>(SELECT count(DISTINCT target_version_id)
   FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=definition.version_id)
 THEN RAISE EXCEPTION 'Function static dependency pins mismatch'; END IF;
 IF definition.attributes->'definition'->>'implementation_id'='source.retained-xls-worksheet/v1' THEN
  SELECT v.* INTO evidence FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND v.resource_id=(definition.attributes->>'evidence_id')::uuid;
  SELECT * INTO source FROM source_documents WHERE tenant_id=NEW.tenant_id
   AND document_id=definition.attributes->'definition'->>'document_id'
   AND exact_scope=NEW.exact_scope;
  IF evidence.version_id IS NULL OR evidence.object_type<>'SourceEvidence'
   OR evidence.authority_state<>'APPROVED' OR source.document_id IS NULL
   OR evidence.attributes->>'sha256' IS DISTINCT FROM source.source_sha256
   OR definition.attributes->'definition'->>'source_sha256' IS DISTINCT FROM source.source_sha256
   OR source.created_at>(NEW.request->>'known_at')::timestamptz
   OR evidence.system_from>(NEW.request->>'known_at')::timestamptz
   OR ((NEW.request->>'offset')::int>=0 AND (NEW.request->>'limit')::int BETWEEN 1 AND 50
       AND (NEW.request->>'offset')::int+(NEW.request->>'limit')::int<=
           (definition.attributes->'definition'->>'row_count')::int) IS NOT TRUE
   OR NEW.plan->'object_set' IS DISTINCT FROM 'null'::jsonb
   OR NEW.plan->'derived_properties' IS DISTINCT FROM '[]'::jsonb
  THEN RAISE EXCEPTION 'Exact retained worksheet source evidence required'; END IF;
  source_plan := jsonb_build_object('document_id',source.document_id,'sha256',source.source_sha256,
    'filename',source.filename,
    'sheet',definition.attributes->'definition'->'sheet',
    'first_row',definition.attributes->'definition'->'first_row',
    'row_count',definition.attributes->'definition'->'row_count',
    'evidence',jsonb_build_object('resource_id',evidence.resource_id::text,
      'version_id',evidence.version_id::text,'content_hash',evidence.content_hash));
  IF NEW.plan->'source_document' IS DISTINCT FROM source_plan
  THEN RAISE EXCEPTION 'Retained worksheet source or window mismatch'; END IF;
 ELSIF definition.attributes->'definition'->>'implementation_id'='ontology.object-set-derived/v1' THEN
 SELECT v.* INTO selected FROM resource_dependencies d JOIN resource_versions v
 ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
 WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
 AND v.resource_id=(definition.attributes->>'object_set_id')::uuid;
 IF selected.version_id IS NULL OR selected.object_type<>'ObjectSetDefinition'
 OR NEW.plan->'object_set' IS DISTINCT FROM jsonb_build_object('resource_id',selected.resource_id::text,
   'version_id',selected.version_id::text,'content_hash',selected.content_hash)
 THEN RAISE EXCEPTION 'Function Object Set pin mismatch'; END IF;
 FOR property IN SELECT value FROM jsonb_array_elements(
   definition.attributes->'definition'->'derived_property_ids') LOOP
  SELECT v.* INTO selected FROM resource_dependencies d JOIN resource_versions v
  ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
  WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
  AND v.resource_id=(property#>>'{}')::uuid;
  IF selected.version_id IS NULL OR selected.object_type<>'DerivedProperty'
  THEN RAISE EXCEPTION 'Function derived property dependency missing'; END IF;
  expected_properties := expected_properties || jsonb_build_array(jsonb_build_object(
    'resource_id',selected.resource_id::text,'version_id',selected.version_id::text,
    'content_hash',selected.content_hash));
 END LOOP;
 IF NEW.plan->'derived_properties' IS DISTINCT FROM expected_properties
 THEN RAISE EXCEPTION 'Function derived property pins mismatch'; END IF;
 ELSE RAISE EXCEPTION 'Unsupported Function adapter';
 END IF;
 NEW.created_at := clock_timestamp(); RETURN NEW;
END $$;
CREATE FUNCTION guard_worksheet_function_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; output fact_calculation_runs%ROWTYPE;
 source_row jsonb;
BEGIN
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 IF NEW.status<>'SUCCEEDED' OR intent.plan->'implementation'->>'implementation_id'
  IS DISTINCT FROM 'source.retained-xls-worksheet/v1' THEN RETURN NEW; END IF;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 IF output.payload->'source_document' IS DISTINCT FROM intent.plan->'source_document'
  OR output.payload->>'authority' IS DISTINCT FROM 'SOURCE_CELLS_ONLY'
  OR output.payload->>'coverage' IS DISTINCT FROM 'REVIEWED_WORKSHEET_PAGE_ONLY'
  OR output.payload->>'temporal_semantics' IS DISTINCT FROM 'IMMUTABLE_RETAINED_SNAPSHOT_NOT_VALID_TIME_FACTS'
  OR output.payload->'query'->'offset' IS DISTINCT FROM intent.request->'offset'
  OR output.payload->'query'->'limit' IS DISTINCT FROM intent.request->'limit'
  OR (output.payload->'query'->>'known_at')::timestamptz IS DISTINCT FROM (intent.request->>'known_at')::timestamptz
  OR (output.payload->'query'->>'valid_at')::timestamptz IS DISTINCT FROM (intent.request->>'valid_at')::timestamptz
  OR output.payload->'returned_rows' IS DISTINCT FROM to_jsonb(jsonb_array_length(output.payload->'source_rows'))
  OR output.payload->'objects' IS DISTINCT FROM '[]'::jsonb
  OR output.payload->'derived_values' IS DISTINCT FROM '[]'::jsonb
  OR jsonb_typeof(output.payload->'source_rows') IS DISTINCT FROM 'array'
  OR jsonb_array_length(output.payload->'source_rows')>least((intent.request->>'limit')::int,
      (intent.plan->'source_document'->>'row_count')::int)
  OR jsonb_array_length(output.payload->'source_rows')<>(SELECT count(DISTINCT value->>'row')
      FROM jsonb_array_elements(output.payload->'source_rows'))
 THEN RAISE EXCEPTION 'Worksheet output must preserve exact retained source and bounded rows'; END IF;
 FOR source_row IN SELECT value FROM jsonb_array_elements(output.payload->'source_rows') LOOP
  IF ((source_row->>'row')::int>=(intent.plan->'source_document'->>'first_row')::int+
      (intent.request->>'offset')::int+1
   AND (source_row->>'row')::int<=(intent.plan->'source_document'->>'first_row')::int+
     (intent.request->>'offset')::int+(intent.request->>'limit')::int) IS NOT TRUE
   OR jsonb_typeof(source_row->'cells') IS DISTINCT FROM 'array'
   OR jsonb_array_length(source_row->'cells')>256
  THEN RAISE EXCEPTION 'Worksheet row is outside reviewed source window'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER worksheet_function_result_integrity BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_worksheet_function_result();
CREATE OR REPLACE FUNCTION guard_transformation_budget_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE retained workflow_requests%ROWTYPE; node jsonb; budget jsonb; expected_usage jsonb;
 result function_invocation_results%ROWTYPE; calculation fact_calculation_runs%ROWTYPE;
 invocation function_invocations%ROWTYPE; expected_reference jsonb; cumulative jsonb; dependency jsonb;
 used_rows bigint; used_evaluations bigint; used_bytes bigint; exceeds boolean;
BEGIN
 SELECT * INTO retained FROM workflow_requests
 WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id;
 IF retained.definition_version IS DISTINCT FROM 'transformation-functions/1'
 OR retained.payload->'compiled_plan'->'resource_budget' IS NULL THEN RETURN NEW; END IF;
 -- Serialize aggregate accounting for this retained run, including direct/retried event inserts.
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text||':'||NEW.workflow_id,45));
 budget := retained.payload->'compiled_plan'->'resource_budget';
 IF NEW.exact_scope IS DISTINCT FROM retained.exact_scope
 THEN RAISE EXCEPTION 'Transformation budget scope mismatch'; END IF;
 IF NEW.payload->>'state' IN ('COMPLETED','BUDGET_REFUSED') THEN
  SELECT value INTO node FROM jsonb_array_elements(retained.payload->'compiled_plan'->'nodes')
  WHERE value->>'node_id'=NEW.payload->>'node';
  SELECT * INTO result FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(node->'invocation'->>'request_id')::uuid;
  SELECT * INTO invocation FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=(node->'invocation'->>'request_id')::uuid;
  SELECT * INTO calculation FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=result.run_id AND exact_scope=NEW.exact_scope;
  IF node IS NULL OR result.status IS DISTINCT FROM 'SUCCEEDED'
  OR calculation.run_id IS NULL OR result.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR result.actor_id IS DISTINCT FROM retained.actor_id
  OR invocation.request IS DISTINCT FROM node->'invocation'
  OR invocation.plan IS DISTINCT FROM node->'function_plan'
  THEN RAISE EXCEPTION 'Budget usage requires exact retained Function result'; END IF;
  expected_reference := jsonb_build_object('invocation_id',result.request_id::text,
   'receipt_hash',result.proof_hash,'run_id',result.run_id);
  expected_usage := jsonb_build_object('measurement','POSTGRES_JSONB_TEXT_UTF8_V1',
   'returned_rows',CASE WHEN calculation.payload->'implementation'->>'implementation_id'='source.retained-xls-worksheet/v1' THEN jsonb_array_length(calculation.payload->'source_rows') ELSE jsonb_array_length(calculation.payload->'objects') END,
   'derived_evaluations',jsonb_array_length(calculation.payload->'derived_values'),
   'published_result_bytes',octet_length(convert_to(calculation.payload::text,'UTF8')));
  IF expected_usage IS DISTINCT FROM NEW.payload->'usage'
  OR expected_reference IS DISTINCT FROM NEW.payload->'output'
  THEN RAISE EXCEPTION 'Transformation usage differs from retained result'; END IF;
  SELECT coalesce(sum((payload->'usage'->>'returned_rows')::bigint),0),
   coalesce(sum((payload->'usage'->>'derived_evaluations')::bigint),0),
   coalesce(sum((payload->'usage'->>'published_result_bytes')::bigint),0)
  INTO used_rows,used_evaluations,used_bytes FROM workflow_events
  WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id
  AND payload->>'state'='COMPLETED' AND payload->>'node'<>node->>'node_id';
  used_rows := used_rows+(expected_usage->>'returned_rows')::bigint;
  used_evaluations := used_evaluations+(expected_usage->>'derived_evaluations')::bigint;
  used_bytes := used_bytes+(expected_usage->>'published_result_bytes')::bigint;
  exceeds := used_rows>(budget->>'max_returned_rows')::bigint
   OR used_evaluations>(budget->>'max_derived_evaluations')::bigint
   OR used_bytes>(budget->>'max_published_result_bytes')::bigint;
  IF NEW.payload->>'state'='COMPLETED' THEN
   IF exceeds THEN RAISE EXCEPTION 'Transformation aggregate budget exceeded'; END IF;
  ELSE
   FOR dependency IN SELECT value FROM jsonb_array_elements(node->'depends_on') LOOP
    IF NOT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
     AND workflow_id=NEW.workflow_id AND event_id='node:'||(dependency#>>'{}')||':terminal'
     AND payload->>'state'='COMPLETED')
    THEN RAISE EXCEPTION 'Budget refusal requires completed dependency barriers'; END IF;
   END LOOP;
   cumulative := jsonb_build_object('measurement','POSTGRES_JSONB_TEXT_UTF8_V1',
    'returned_rows',used_rows,'derived_evaluations',used_evaluations,'published_result_bytes',used_bytes);
   IF NOT exceeds OR NEW.event_id IS DISTINCT FROM 'node:'||(node->>'node_id')||':budget-refused'
    OR NEW.payload->'resource_budget' IS DISTINCT FROM budget
    OR NEW.payload->'cumulative_usage' IS DISTINCT FROM cumulative
    OR NEW.payload->'new_run_required' IS DISTINCT FROM 'true'::jsonb
   THEN RAISE EXCEPTION 'Budget refusal must retain exact exceeded limits and usage'; END IF;
  END IF;
 ELSIF NEW.payload->>'state'='PUBLISHED' THEN
  IF EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
   AND workflow_id=NEW.workflow_id AND payload->>'state'='BUDGET_REFUSED')
  THEN RAISE EXCEPTION 'Budget-refused transformation cannot publish'; END IF;
  SELECT sum((payload->'usage'->>'returned_rows')::bigint),
   sum((payload->'usage'->>'derived_evaluations')::bigint),
   sum((payload->'usage'->>'published_result_bytes')::bigint)
  INTO used_rows,used_evaluations,used_bytes FROM workflow_events
  WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id AND payload->>'state'='COMPLETED';
  IF used_rows IS NULL OR used_evaluations IS NULL OR used_bytes IS NULL
   OR used_rows>(budget->>'max_returned_rows')::bigint
   OR used_evaluations>(budget->>'max_derived_evaluations')::bigint
   OR used_bytes>(budget->>'max_published_result_bytes')::bigint
  THEN RAISE EXCEPTION 'Complete publication requires retained usage within budget'; END IF;
 END IF;
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(46);
COMMIT;
