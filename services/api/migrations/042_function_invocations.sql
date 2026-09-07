BEGIN;
CREATE TABLE function_invocations (
 tenant_id uuid NOT NULL, request_id uuid NOT NULL, exact_scope jsonb NOT NULL,
 actor_id text NOT NULL, request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 request jsonb NOT NULL, plan jsonb NOT NULL, plan_hash text NOT NULL CHECK(plan_hash ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(tenant_id,request_id),
 CHECK((exact_scope->>'tenant_id'=tenant_id::text) IS TRUE),
 CHECK((request->>'request_id'=request_id::text) IS TRUE),
 CHECK((plan->'request'=request) IS TRUE), CHECK((plan->'exact_scope'=exact_scope) IS TRUE),
 CHECK((plan->>'plan_hash'=plan_hash) IS TRUE),
 CHECK((plan->>'mode'='EVIDENCE_ANALYSIS_ONLY') IS TRUE)
);
CREATE TABLE function_invocation_results (
 tenant_id uuid NOT NULL, request_id uuid NOT NULL, exact_scope jsonb NOT NULL,
 actor_id text NOT NULL, status text NOT NULL CHECK(status IN ('SUCCEEDED','FAILED')),
 run_id text, payload jsonb NOT NULL, proof_hash text NOT NULL CHECK(proof_hash ~ '^[a-f0-9]{64}$'),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(tenant_id,request_id),
 FOREIGN KEY(tenant_id,request_id) REFERENCES function_invocations(tenant_id,request_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES fact_calculation_runs(tenant_id,run_id),
 CHECK((exact_scope->>'tenant_id'=tenant_id::text) IS TRUE),
 CHECK((status='SUCCEEDED')=(run_id IS NOT NULL))
);
ALTER TABLE function_invocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE function_invocations FORCE ROW LEVEL SECURITY;
ALTER TABLE function_invocation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE function_invocation_results FORCE ROW LEVEL SECURITY;
CREATE POLICY function_invocation_scope ON function_invocations
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
CREATE POLICY function_result_scope ON function_invocation_results
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON function_invocations,function_invocation_results TO finai_runtime;
CREATE TRIGGER immutable_function_invocation BEFORE UPDATE OR DELETE OR TRUNCATE
 ON function_invocations FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE TRIGGER immutable_function_result BEFORE UPDATE OR DELETE OR TRUNCATE
 ON function_invocation_results FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE FUNCTION guard_function_invocation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; selected resource_versions%ROWTYPE;
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
 NEW.created_at := clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER function_intent_integrity BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_function_invocation_intent();
CREATE FUNCTION guard_function_invocation_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; output fact_calculation_runs%ROWTYPE;
BEGIN
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 IF intent.request_id IS NULL OR intent.exact_scope IS DISTINCT FROM NEW.exact_scope
 OR intent.actor_id IS DISTINCT FROM NEW.actor_id
 OR NEW.payload->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NEW.payload->>'status' IS DISTINCT FROM NEW.status
 OR NEW.payload->>'plan_hash' IS DISTINCT FROM intent.plan_hash
 OR NEW.payload->'request' IS DISTINCT FROM intent.request
 OR NEW.payload->'exact_scope' IS DISTINCT FROM intent.exact_scope
 OR NEW.payload->'function' IS DISTINCT FROM intent.plan->'function'
 OR NEW.payload->'implementation' IS DISTINCT FROM intent.plan->'implementation'
 OR NEW.payload->>'mode' IS DISTINCT FROM 'EVIDENCE_ANALYSIS_ONLY'
 OR NEW.payload->'current_use_authorized' IS DISTINCT FROM 'false'::jsonb
 OR NEW.payload->'business_effect_authorized' IS DISTINCT FROM 'false'::jsonb
 THEN RAISE EXCEPTION 'Invocation result must match immutable scoped intent'; END IF;
 IF NEW.status='SUCCEEDED' THEN
  SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
  IF output.run_id IS NULL OR output.exact_scope IS DISTINCT FROM NEW.exact_scope
   OR NEW.payload->>'run_id' IS DISTINCT FROM NEW.run_id
   OR output.payload->>'invocation_request_id' IS DISTINCT FROM NEW.request_id::text
   OR output.payload->>'invocation_plan_hash' IS DISTINCT FROM intent.plan_hash
   OR output.payload->'function' IS DISTINCT FROM intent.plan->'function'
   OR output.payload->>'plan_hash' IS DISTINCT FROM intent.plan_hash
   OR output.payload->'implementation' IS DISTINCT FROM intent.plan->'implementation'
   OR output.payload->'static_dependencies' IS DISTINCT FROM intent.plan->'static_dependencies'
   OR output.payload->>'mode' IS DISTINCT FROM 'EVIDENCE_ANALYSIS_ONLY'
   OR output.payload->>'calculation_runtime' IS DISTINCT FROM 'shared-functions/1'
   OR output.payload->'current_use_authorized' IS DISTINCT FROM 'false'::jsonb
   OR output.payload->'business_effect_authorized' IS DISTINCT FROM 'false'::jsonb
  THEN RAISE EXCEPTION 'Invocation output must match retained calculation evidence'; END IF;
 ELSE
  IF (NEW.payload->>'failure_code' IN ('EXECUTION_REJECTED','EXECUTION_FAILED')) IS NOT TRUE
   OR NEW.payload ? 'run_id' THEN RAISE EXCEPTION 'Invalid terminal failure'; END IF;
 END IF;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER function_result_integrity BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_function_invocation_result();
INSERT INTO schema_migrations VALUES(42);
COMMIT;
