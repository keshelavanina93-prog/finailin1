BEGIN;
-- Reviewed aggregate limits supplement, rather than replace, the exact-plan and receipt guards.
CREATE FUNCTION guard_transformation_budget_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; budget jsonb; canonical_budget jsonb; estimates jsonb;
 rows_bound bigint; evaluations_bound bigint;
BEGIN
 IF NEW.definition_version<>'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan'; budget := compiled->'resource_budget';
 SELECT attributes->'resource_budget' INTO canonical_budget FROM resource_versions
 WHERE tenant_id=NEW.tenant_id
 AND version_id=(compiled->'request'->'transformation'->>'version_id')::uuid
 AND resource_id=(compiled->'request'->'transformation'->>'resource_id')::uuid;
 IF budget IS NULL OR budget IS DISTINCT FROM canonical_budget
 OR compiled->>'result_bytes_accounting' IS DISTINCT FROM 'POSTGRES_JSONB_TEXT_UTF8_V1'
 OR jsonb_typeof(budget->'max_returned_rows') IS DISTINCT FROM 'number'
 OR jsonb_typeof(budget->'max_derived_evaluations') IS DISTINCT FROM 'number'
 OR jsonb_typeof(budget->'max_published_result_bytes') IS DISTINCT FROM 'number'
 THEN RAISE EXCEPTION 'Reviewed transformation resource budget required'; END IF;
 IF (budget->>'max_returned_rows')::bigint NOT BETWEEN 1 AND 6400
 OR (budget->>'max_derived_evaluations')::bigint NOT BETWEEN 0 AND 51200
 OR (budget->>'max_published_result_bytes')::bigint NOT BETWEEN 1 AND 16000000
 THEN RAISE EXCEPTION 'Transformation resource budget exceeds installed limits'; END IF;
 SELECT sum((n.value->'invocation'->>'limit')::bigint),
 sum((n.value->'invocation'->>'limit')::bigint *
     jsonb_array_length(coalesce(v.attributes->'definition'->'derived_property_ids','[]'::jsonb)))
 INTO rows_bound,evaluations_bound
 FROM jsonb_array_elements(compiled->'nodes') n
 JOIN resource_versions v ON v.tenant_id=NEW.tenant_id
 AND v.resource_id=(n.value->'function'->>'resource_id')::uuid
 AND v.version_id=(n.value->'function'->>'version_id')::uuid;
 estimates := jsonb_build_object('returned_rows',rows_bound,'derived_evaluations',evaluations_bound);
 IF rows_bound IS NULL OR evaluations_bound IS NULL
 OR estimates IS DISTINCT FROM compiled->'estimated_work'
 OR rows_bound>(budget->>'max_returned_rows')::bigint
 OR evaluations_bound>(budget->>'max_derived_evaluations')::bigint
 THEN RAISE EXCEPTION 'Transformation estimated work exceeds reviewed budget'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_budget_intent_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_budget_intent();

CREATE FUNCTION guard_transformation_budget_event() RETURNS trigger LANGUAGE plpgsql AS $$
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
   'returned_rows',jsonb_array_length(calculation.payload->'objects'),
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
CREATE TRIGGER transformation_budget_event_integrity BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_budget_event();
INSERT INTO schema_migrations VALUES(45);
COMMIT;
