BEGIN;
CREATE OR REPLACE FUNCTION guard_function_invocation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; selected resource_versions%ROWTYPE;
 source source_documents%ROWTYPE; evidence resource_versions%ROWTYPE; source_plan jsonb;
 binding resource_versions%ROWTYPE; accounting_scope resource_versions%ROWTYPE;
 retained_hash text; retained_scope jsonb; retained_at timestamptz;
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
 ELSIF definition.attributes->'definition'->>'implementation_id'='accounting.retained-posted-movements/v1' THEN
  SELECT v.* INTO binding FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND v.resource_id=(definition.attributes->>'accounting_binding_id')::uuid LIMIT 1;
  SELECT v.* INTO accounting_scope FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND v.resource_id=(definition.attributes->>'source_scope_id')::uuid LIMIT 1;
  SELECT v.* INTO evidence FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND v.resource_id=(definition.attributes->>'evidence_id')::uuid LIMIT 1;
  IF left(definition.attributes->'definition'->>'document_id',3)='ir_' THEN
   SELECT source_sha256,exact_scope,ingested_at INTO retained_hash,retained_scope,retained_at
    FROM hydration_runs WHERE tenant_id=NEW.tenant_id
    AND receipt_id=definition.attributes->'definition'->>'document_id';
  ELSE
   SELECT source_sha256,exact_scope,created_at INTO retained_hash,retained_scope,retained_at
    FROM source_documents WHERE tenant_id=NEW.tenant_id
    AND document_id=definition.attributes->'definition'->>'document_id';
  END IF;
  IF binding.object_type IS DISTINCT FROM 'SourceAccountingBinding'
   OR accounting_scope.object_type IS DISTINCT FROM 'SourceAccountingScope'
   OR evidence.object_type IS DISTINCT FROM 'SourceEvidence'
   OR binding.attributes->>'scope_id' IS DISTINCT FROM accounting_scope.resource_id::text
   OR accounting_scope.attributes->>'evidence_id' IS DISTINCT FROM evidence.resource_id::text
   OR accounting_scope.attributes->>'source_profile' IS DISTINCT FROM 'seg_expense_base'
   OR accounting_scope.attributes->>'document_id' IS DISTINCT FROM definition.attributes->'definition'->>'document_id'
   OR accounting_scope.attributes->>'worksheet' IS DISTINCT FROM definition.attributes->'definition'->>'sheet'
   OR retained_hash IS NULL OR retained_scope IS DISTINCT FROM NEW.exact_scope
   OR retained_at>(NEW.request->>'known_at')::timestamptz
   OR evidence.attributes->>'sha256' IS DISTINCT FROM retained_hash
   OR definition.attributes->'definition'->>'source_sha256' IS DISTINCT FROM retained_hash
   OR binding.attributes->>'source_use' IS DISTINCT FROM 'ACCOUNTING_INPUT'
   OR binding.attributes->>'amount_field' IS DISTINCT FROM 'source_amount'
   OR binding.attributes->>'vat_treatment' IS DISTINCT FROM 'AS_POSTED'
   OR definition.attributes->>'minimum_authority_state' IS DISTINCT FROM 'OBSERVED'
   OR NEW.request->>'offset' IS DISTINCT FROM '0' OR NEW.request ? 'input_result'
   OR NEW.plan->'object_set' IS DISTINCT FROM 'null'::jsonb
   OR NEW.plan->'derived_properties' IS DISTINCT FROM '[]'::jsonb
  THEN RAISE EXCEPTION 'Posted movement Function requires reviewed exact source accounting authority'; END IF;
  source_plan := NEW.plan->'source_document';
  IF source_plan->'binding' IS DISTINCT FROM jsonb_build_object('resource_id',binding.resource_id::text,
      'version_id',binding.version_id::text,'content_hash',binding.content_hash)
   OR source_plan->'scope' IS DISTINCT FROM jsonb_build_object('resource_id',accounting_scope.resource_id::text,
      'version_id',accounting_scope.version_id::text,'content_hash',accounting_scope.content_hash)
   OR source_plan->'evidence' IS DISTINCT FROM jsonb_build_object('resource_id',evidence.resource_id::text,
      'version_id',evidence.version_id::text,'content_hash',evidence.content_hash)
   OR source_plan->>'sha256' IS DISTINCT FROM retained_hash
   OR source_plan->>'document_id' IS DISTINCT FROM definition.attributes->'definition'->>'document_id'
   OR source_plan->>'sheet' IS DISTINCT FROM definition.attributes->'definition'->>'sheet'
   OR source_plan->'max_source_rows' IS DISTINCT FROM definition.attributes->'definition'->'max_source_rows'
   OR ((source_plan->>'row_count')::int BETWEEN 1 AND (source_plan->>'max_source_rows')::int) IS NOT TRUE
   OR source_plan->>'company_id' IS DISTINCT FROM accounting_scope.attributes->>'legal_entity_id'
   OR source_plan->>'observed_from' IS DISTINCT FROM accounting_scope.attributes->>'observed_from'
   OR source_plan->>'observed_through' IS DISTINCT FROM accounting_scope.attributes->>'observed_through'
  THEN RAISE EXCEPTION 'Posted movement plan differs from pinned source interpretation'; END IF;
  FOREACH key IN ARRAY ARRAY['ledger_id','book_id','period_id','currency_id','functional_currency_id',
    'amount_field','amount_semantics','vat_treatment'] LOOP
   IF source_plan->'context'->key IS DISTINCT FROM binding.attributes->key
    THEN RAISE EXCEPTION 'Posted movement context mismatch'; END IF;
  END LOOP;
  SELECT v.* INTO selected FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id
   WHERE d.tenant_id=NEW.tenant_id AND d.version_id=definition.version_id
   AND v.resource_id=(binding.attributes->>'account_mapping_id')::uuid LIMIT 1;
  IF selected.object_type IS DISTINCT FROM 'MappingVersion'
   OR source_plan->'accounts' IS DISTINCT FROM selected.attributes->'definition'->'accounts'
   THEN RAISE EXCEPTION 'Posted movement account mapping mismatch'; END IF;
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
   'returned_rows',CASE WHEN calculation.payload->'implementation'->>'implementation_id' IN ('source.retained-xls-worksheet/v1','accounting.retained-posted-movements/v1') THEN jsonb_array_length(calculation.payload->'source_rows') ELSE jsonb_array_length(calculation.payload->'objects') END,
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
CREATE FUNCTION guard_posted_movement_function_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; calculation fact_calculation_runs%ROWTYPE;
 proof guarded_consumption_receipts%ROWTYPE; result jsonb; source jsonb; source_row jsonb;
 groups jsonb; expected_groups jsonb; expected_included jsonb; expected_excluded jsonb;
 coordinate text; literal text; included int; total int;
BEGIN
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 IF NEW.status<>'SUCCEEDED' OR intent.plan->'implementation'->>'implementation_id'
  IS DISTINCT FROM 'accounting.retained-posted-movements/v1' THEN RETURN NEW; END IF;
 SELECT * INTO calculation FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 result := calculation.payload; source := intent.plan->'source_document';
 SELECT * INTO proof FROM guarded_consumption_receipts WHERE tenant_id=NEW.tenant_id
  AND consumption_id=(result->'authority_check'->>'consumption_id')::uuid;
 IF proof.proof_hash IS DISTINCT FROM result->'authority_check'->>'proof_hash'
  OR proof.consumer_version_id::text IS DISTINCT FROM intent.request->'function'->>'version_id'
  OR proof.consumer_resource_id::text IS DISTINCT FROM intent.request->'function'->>'resource_id'
  OR proof.actor_id IS DISTINCT FROM intent.actor_id
  OR proof.access_entity IS DISTINCT FROM intent.exact_scope->>'legal_entity_id'
  OR result->'source_document' IS DISTINCT FROM source
  OR result->>'authority' IS DISTINCT FROM 'GUARDED_POSTED_MOVEMENT_ANALYSIS'
  OR result->>'coverage' IS DISTINCT FROM 'RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS'
  OR result->>'temporal_semantics' IS DISTINCT FROM 'IMMUTABLE_RETAINED_SNAPSHOT_WITH_POSTING_DATES'
  OR result->'objects' IS DISTINCT FROM '[]'::jsonb
  OR result->'derived_values' IS DISTINCT FROM '[]'::jsonb
  OR result->'next_offset' IS DISTINCT FROM 'null'::jsonb
  OR jsonb_typeof(result->'source_rows') IS DISTINCT FROM 'array'
  OR result->'returned_rows' IS DISTINCT FROM source->'row_count'
  OR jsonb_array_length(result->'source_rows')<>(source->>'row_count')::int
  OR (result->'query'->>'known_at')::timestamptz IS DISTINCT FROM (intent.request->>'known_at')::timestamptz
  OR (result->'query'->>'valid_at')::timestamptz IS DISTINCT FROM (intent.request->>'valid_at')::timestamptz
 THEN RAISE EXCEPTION 'Posted movement output requires exact guarded calculation evidence'; END IF;
 total := jsonb_array_length(result->'source_rows');
 IF total<>(SELECT count(DISTINCT value->>'row') FROM jsonb_array_elements(result->'source_rows'))
  OR total<>(SELECT count(DISTINCT jsonb_build_array(value->'attributes'->>'source_recorder',
     value->'attributes'->>'source_line_number')) FROM jsonb_array_elements(result->'source_rows'))
 THEN RAISE EXCEPTION 'Posted movement source rows and recorder keys must be unique'; END IF;
 FOR source_row IN SELECT value FROM jsonb_array_elements(result->'source_rows') LOOP
  IF NOT (source->'accounts' ? (source_row->'attributes'->>'account_code'))
   OR NOT (source->'accounts' ? (source_row->'attributes'->>'credit_account_code'))
   OR ((source_row->'attributes'->>'posting_date')::date BETWEEN
      (source->>'observed_from')::date AND (source->>'observed_through')::date) IS NOT TRUE
   THEN RAISE EXCEPTION 'Posted movement row requires mapped accounts and in-period date'; END IF;
  literal := source_row->'numeric_observations'->'source_amount'->>'literal_decimal';
  coordinate := source_row->'numeric_observations'->'source_amount'->>'coordinate';
  IF literal IS NOT NULL AND (
    source_row->'numeric_observations'->'source_amount'->>'header' IS DISTINCT FROM 'Сумма'
    OR source_row->'numeric_observations'->'source_amount'->>'formula' IS NOT NULL
    OR source_row->'cells'->coordinate->>'type' IS DISTINCT FROM 'n'
    OR source_row->'cells'->coordinate->>'formula' IS NOT NULL
    OR source_row->'cells'->coordinate->>'value' IS DISTINCT FROM literal
    OR length(literal)>160)
   THEN RAISE EXCEPTION 'Posted movement amount must preserve exact literal source cell'; END IF;
 END LOOP;
 SELECT coalesce(jsonb_agg(value->'numeric_observations'->'source_amount'->'coordinate'
   ORDER BY (value->>'row')::int),'[]'::jsonb) INTO expected_included
  FROM jsonb_array_elements(result->'source_rows')
  WHERE value->'numeric_observations'->'source_amount'->>'literal_decimal' IS NOT NULL;
 included := jsonb_array_length(expected_included);
 IF result->'posted_movements'->'included_coordinates' IS DISTINCT FROM expected_included
  OR result->'posted_movements'->'coverage' IS DISTINCT FROM jsonb_build_object(
   'source_rows',total,'included_rows',included,'excluded_rows',total-included,
   'ledger_completeness','UNESTABLISHED')
  OR jsonb_array_length(result->'posted_movements'->'excluded_rows')<>total-included
 THEN RAISE EXCEPTION 'Posted movement exclusions and coverage must reconcile'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(result->'posted_movements'->'excluded_rows') excluded
   WHERE excluded->>'reason' IS DISTINCT FROM 'MISSING_LITERAL_POSTED_AMOUNT'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(result->'source_rows') r
      WHERE r->'row'=excluded->'row'
      AND r->'numeric_observations'->'source_amount'->>'literal_decimal' IS NULL))
 THEN RAISE EXCEPTION 'Excluded posting must be a retained row lacking literal amount'; END IF;
 WITH rows AS (SELECT value r FROM jsonb_array_elements(result->'source_rows')
   WHERE value->'numeric_observations'->'source_amount'->>'literal_decimal' IS NOT NULL),
 sides AS (SELECT r, 'debit'::text side, r->'attributes'->>'account_code' code FROM rows
   UNION ALL SELECT r,'credit',r->'attributes'->>'credit_account_code' FROM rows),
 summed AS (SELECT code,side,sum((r->'numeric_observations'->'source_amount'->>'literal_decimal')::numeric) amount,
   jsonb_agg(r->'numeric_observations'->'source_amount'->'coordinate' ORDER BY (r->>'row')::int) coordinates
   FROM sides GROUP BY code,side)
 SELECT coalesce(jsonb_agg(jsonb_build_object('account_code',code,'side',side,
   'account',source->'accounts'->code,'value',amount,
   'currency_id',source->'context'->'currency_id','source_coordinates',coordinates)
   ORDER BY code,side),'[]'::jsonb) INTO expected_groups FROM summed;
 SELECT coalesce(jsonb_agg(jsonb_set(value,'{value}',to_jsonb((value->>'value')::numeric))
   ORDER BY value->>'account_code',value->>'side'),'[]'::jsonb) INTO groups
   FROM jsonb_array_elements(result->'posted_movements'->'groups');
 IF groups IS DISTINCT FROM expected_groups
  THEN RAISE EXCEPTION 'Posted account totals must equal retained literal source contributors'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER posted_movement_result_integrity BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_posted_movement_function_result();
CREATE OR REPLACE FUNCTION guard_transformation_budget_intent() RETURNS trigger LANGUAGE plpgsql AS $$
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
 SELECT sum((CASE WHEN v.attributes->'definition'->>'implementation_id'='accounting.retained-posted-movements/v1' THEN (n.value->'function_plan'->'source_document'->>'row_count')::bigint WHEN v.attributes->'definition' ? 'materialization' THEN
 least((v.attributes->'definition'->'materialization'->>'max_objects')::bigint,
 (n.value->'invocation'->>'limit')::bigint *
 (v.attributes->'definition'->'materialization'->>'max_pages')::bigint)
 ELSE (n.value->'invocation'->>'limit')::bigint END)),
 sum((CASE WHEN v.attributes->'definition'->>'implementation_id'='accounting.retained-posted-movements/v1' THEN (n.value->'function_plan'->'source_document'->>'row_count')::bigint WHEN v.attributes->'definition' ? 'materialization' THEN
 least((v.attributes->'definition'->'materialization'->>'max_objects')::bigint,
 (n.value->'invocation'->>'limit')::bigint *
 (v.attributes->'definition'->'materialization'->>'max_pages')::bigint)
 ELSE (n.value->'invocation'->>'limit')::bigint END) *
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

INSERT INTO schema_migrations VALUES(62);
COMMIT;
