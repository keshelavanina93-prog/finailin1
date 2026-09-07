BEGIN;
-- Bind declared calculated inputs and retained values to existing canonical evidence.
CREATE FUNCTION guard_function_calculated_input_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; property resource_versions%ROWTYPE;
 schema_row resource_versions%ROWTYPE; source_intent function_invocations%ROWTYPE;
 declared jsonb; reference jsonb; property_pin jsonb; schema_pin jsonb;
 expected jsonb := '[]'::jsonb; graph_node jsonb; matches integer;
BEGIN
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(NEW.request->'function'->>'resource_id')::uuid
  AND version_id=(NEW.request->'function'->>'version_id')::uuid;
 declared := coalesce(definition.attributes->'definition'->'retained_properties','[]'::jsonb);
 IF declared='[]'::jsonb THEN
  IF NEW.plan ? 'retained_properties'
   THEN RAISE EXCEPTION 'Undeclared calculated Function input'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(declared) IS DISTINCT FROM 'array'
  OR jsonb_array_length(declared) NOT BETWEEN 1 AND 8
  OR NOT (NEW.request ? 'input_result')
  OR (SELECT count(DISTINCT value->>'resource_id') FROM jsonb_array_elements(declared))
     <> jsonb_array_length(declared)
 THEN RAISE EXCEPTION 'Calculated Function inputs require unique reviewed pins and a receipt'; END IF;
 SELECT * INTO source_intent FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=(NEW.request->'input_result'->>'invocation_id')::uuid;
 FOR reference IN SELECT value FROM jsonb_array_elements(declared) LOOP
  SELECT v.* INTO property FROM resource_versions v WHERE v.tenant_id=NEW.tenant_id
   AND v.resource_id=(reference->>'resource_id')::uuid
   AND v.version_id=(reference->>'version_id')::uuid;
  IF property.version_id IS NULL OR property.object_type<>'DerivedProperty'
   OR reference IS DISTINCT FROM jsonb_build_object(
      'resource_id',property.resource_id::text,'version_id',property.version_id::text)
   OR NOT EXISTS(SELECT 1 FROM resource_dependencies d WHERE d.tenant_id=NEW.tenant_id
      AND d.version_id=definition.version_id AND d.target_resource_id=property.resource_id
      AND d.target_version_id=property.version_id
      AND d.relation='FUNCTION_RETAINED_PROPERTY:' || property.resource_id::text)
  THEN RAISE EXCEPTION 'Calculated input lacks its exact reviewed property dependency'; END IF;
  SELECT count(*) INTO matches FROM resource_dependencies d WHERE d.tenant_id=NEW.tenant_id
   AND d.version_id=property.version_id AND d.relation='FIELD:schema_id';
  SELECT v.* INTO schema_row FROM resource_dependencies d JOIN resource_versions v
   ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
   AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
   AND d.version_id=property.version_id AND d.relation='FIELD:schema_id';
  IF matches<>1 OR schema_row.object_type IS DISTINCT FROM 'SchemaDefinition'
  THEN RAISE EXCEPTION 'Calculated input requires its exact canonical schema'; END IF;
  property_pin := jsonb_build_object('resource_id',property.resource_id::text,
   'version_id',property.version_id::text,'content_hash',property.content_hash);
  schema_pin := jsonb_build_object('resource_id',schema_row.resource_id::text,
   'version_id',schema_row.version_id::text,'content_hash',schema_row.content_hash);
  SELECT count(*) INTO matches FROM jsonb_array_elements(NEW.plan->'derived_graph'->'nodes') n
   WHERE n->>'resource_id'=property.resource_id::text;
  SELECT n INTO graph_node FROM jsonb_array_elements(NEW.plan->'derived_graph'->'nodes') n
   WHERE n->>'resource_id'=property.resource_id::text;
  IF matches<>1 OR graph_node->'schema' IS DISTINCT FROM schema_pin
   OR (graph_node - ARRAY['schema','dependencies']) IS DISTINCT FROM property_pin
   OR (SELECT count(*) FROM jsonb_array_elements(source_intent.plan->'derived_properties') n
       WHERE n=property_pin)<>1
  THEN RAISE EXCEPTION 'Calculated input must match the graph and upstream declared output'; END IF;
  expected := expected || jsonb_build_array(property_pin || jsonb_build_object('schema',schema_pin));
 END LOOP;
 IF NEW.plan->'retained_properties' IS DISTINCT FROM expected
 THEN RAISE EXCEPTION 'Calculated input plan differs from reviewed pins'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER function_calculated_input_intent_integrity BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_function_calculated_input_intent();

CREATE FUNCTION guard_function_calculated_input_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; source function_invocation_results%ROWTYPE;
 source_output fact_calculation_runs%ROWTYPE; output fact_calculation_runs%ROWTYPE;
 reference jsonb; object_row jsonb; source_value jsonb; consumed jsonb;
 source_reference jsonb; expected jsonb := '[]'::jsonb; matches integer;
BEGIN
 IF NEW.status<>'SUCCEEDED' THEN RETURN NEW; END IF;
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=NEW.request_id;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=NEW.run_id;
 IF NOT (intent.plan ? 'retained_properties') THEN
  IF output.payload ? 'consumed_property_values'
  THEN RAISE EXCEPTION 'Undeclared retained calculated values'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO source FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(intent.request->'input_result'->>'invocation_id')::uuid;
 SELECT * INTO source_output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=source.run_id;
 IF source.status IS DISTINCT FROM 'SUCCEEDED' OR source_output.run_id IS NULL
  OR source.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR source_output.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR jsonb_typeof(source_output.payload->'derived_values') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Calculated input requires scoped successful retained values'; END IF;
 source_reference := jsonb_build_object('invocation_id',source.request_id::text,
  'receipt_hash',source.proof_hash,'run_id',source.run_id);
 FOR reference IN SELECT value FROM jsonb_array_elements(intent.plan->'retained_properties') LOOP
  FOR object_row IN SELECT value FROM jsonb_array_elements(source_output.payload->'objects') LOOP
   SELECT count(*) INTO matches FROM jsonb_array_elements(source_output.payload->'derived_values') n
    WHERE n->>'definition_id'=reference->>'resource_id'
     AND n->>'definition_version_id'=reference->>'version_id'
     AND n->>'object_id'=object_row->>'resource_id'
     AND n->>'object_version_id'=object_row->>'version_id';
   IF matches<>1 THEN RAISE EXCEPTION 'Calculated input row missing or duplicated'; END IF;
   SELECT n INTO source_value FROM jsonb_array_elements(source_output.payload->'derived_values') n
    WHERE n->>'definition_id'=reference->>'resource_id'
     AND n->>'definition_version_id'=reference->>'version_id'
     AND n->>'object_id'=object_row->>'resource_id'
     AND n->>'object_version_id'=object_row->>'version_id';
   consumed := jsonb_build_object(
    'object_id',source_value->'object_id','object_version_id',source_value->'object_version_id',
    'definition_id',source_value->'definition_id',
    'definition_version_id',source_value->'definition_version_id',
    'name',source_value->'name','kind',source_value->'kind',
    'epistemic_state',source_value->'epistemic_state','status',source_value->'status',
    'value',source_value->'value','content_hash',reference->'content_hash',
    'schema',reference->'schema','source_result',source_reference);
   IF source_value ? 'reason' THEN consumed := consumed ||
    jsonb_build_object('reason',source_value->'reason'); END IF;
   expected := expected || jsonb_build_array(consumed);
  END LOOP;
 END LOOP;
 IF output.payload->'consumed_property_values' IS DISTINCT FROM expected
 THEN RAISE EXCEPTION 'Calculated input values differ from the exact upstream receipt'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER function_calculated_input_result_integrity BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_function_calculated_input_result();
INSERT INTO schema_migrations VALUES(55);
COMMIT;
