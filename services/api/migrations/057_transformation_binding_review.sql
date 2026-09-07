BEGIN;
CREATE FUNCTION guard_transformation_binding_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; declared jsonb; gate jsonb; source_node jsonb;
 definition resource_versions%ROWTYPE; binding resource_versions%ROWTYPE;
 property_reference jsonb;
BEGIN
 IF NEW.definition_version<>'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan'; gate := compiled->'binding_review';
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(compiled->'transformation'->>'resource_id')::uuid
  AND version_id=(compiled->'transformation'->>'version_id')::uuid;
 declared := nullif(definition.attributes->'binding_review','null'::jsonb);
 IF declared IS NULL THEN
  IF gate IS NOT NULL THEN RAISE EXCEPTION 'Binding review requires a reviewed declaration'; END IF;
  RETURN NEW;
 END IF;
 SELECT v.* INTO binding FROM resource_dependencies d JOIN resource_versions v
  ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
  AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
  AND d.version_id=definition.version_id AND d.relation='TRANSFORMATION_BINDING_REVIEW';
 SELECT n INTO source_node FROM jsonb_array_elements(compiled->'nodes') n
  WHERE n->>'node_id'=declared->>'source_node_id';
 IF gate IS NULL OR binding.object_type IS DISTINCT FROM 'ObjectBinding'
  OR binding.authority_state IS DISTINCT FROM 'APPROVED'
  OR binding.resource_id::text IS DISTINCT FROM declared->>'binding_id'
  OR gate->'binding' IS DISTINCT FROM jsonb_build_object(
   'resource_id',binding.resource_id::text,'version_id',binding.version_id::text,
   'content_hash',binding.content_hash)
  OR gate->>'source_node_id' IS DISTINCT FROM declared->>'source_node_id'
  OR gate->>'rationale' IS DISTINCT FROM declared->>'rationale'
  OR gate IS DISTINCT FROM jsonb_build_object('binding',gate->'binding',
   'source_node_id',declared->'source_node_id','rationale',declared->'rationale',
   'operation_request_id',gate->'operation_request_id')
  OR (length(btrim(gate->>'rationale')) BETWEEN 10 AND 2000) IS NOT TRUE
  OR (gate->>'operation_request_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-5[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$') IS NOT TRUE
  OR source_node IS NULL
  OR source_node->'invocation'->>'offset' IS DISTINCT FROM '0'
  OR ((source_node->'invocation'->>'limit')::integer BETWEEN 1 AND 100) IS NOT TRUE
  OR source_node->'function_plan'->'implementation'->>'implementation_id'
     IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR (coalesce(nullif(current_setting('finai.read_permissions',true),''),'[]')::jsonb
      ? 'ontology_propose') IS NOT TRUE
 THEN RAISE EXCEPTION 'Binding review intent differs from its exact reviewed contracts'; END IF;
 IF NOT (binding.attributes->'definition' ? 'display_property') AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(binding.attributes->'definition'->'fields') f
   WHERE f ? 'derived_property')
 THEN RAISE EXCEPTION 'Transformation binding review requires calculated values'; END IF;
 FOR property_reference IN
  SELECT binding.attributes->'definition'->'display_property'
   WHERE binding.attributes->'definition' ? 'display_property'
  UNION ALL SELECT f->'derived_property'
   FROM jsonb_array_elements(binding.attributes->'definition'->'fields') f
   WHERE f ? 'derived_property'
 LOOP
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source_node->'function_plan'->'derived_properties') p
   WHERE p->>'resource_id'=property_reference->>'resource_id'
    AND p->>'version_id'=property_reference->>'version_id')
  THEN RAISE EXCEPTION 'Binding review source does not declare its exact calculated outputs'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_binding_intent_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_binding_intent();

CREATE FUNCTION guard_transformation_binding_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run workflow_requests%ROWTYPE; prepared workflow_events%ROWTYPE;
 operation workflow_requests%ROWTYPE; proposal resource_proposals%ROWTYPE;
 decision resource_decisions%ROWTYPE; receipt function_invocation_results%ROWTYPE;
 output fact_calculation_runs%ROWTYPE; gate jsonb; source_node jsonb; invocation jsonb;
 expected_input jsonb; cancelled boolean; published boolean;
BEGIN
 SELECT * INTO run FROM workflow_requests WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id;
 IF run.definition_version IS DISTINCT FROM 'transformation-functions/1' THEN RETURN NEW; END IF;
 gate := run.payload->'compiled_plan'->'binding_review';
 IF gate IS NULL THEN
  IF NEW.event_id LIKE 'binding-review:%' THEN RAISE EXCEPTION 'Undeclared binding review event'; END IF;
  RETURN NEW;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'transformation-review:'||NEW.tenant_id::text||':'||NEW.workflow_id,0));
 SELECT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND payload->>'command'='cancel') INTO cancelled;
 SELECT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='publication:0') INTO published;
 SELECT * INTO prepared FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='binding-review:prepared';
 IF NEW.event_id='binding-review:prepared' THEN
  SELECT n INTO source_node FROM jsonb_array_elements(run.payload->'compiled_plan'->'nodes') n
   WHERE n->>'node_id'=gate->>'source_node_id';
  SELECT * INTO receipt FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
   AND request_id=(source_node->'invocation'->>'request_id')::uuid;
  SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=receipt.run_id;
  expected_input := jsonb_build_object('invocation_id',receipt.request_id::text,
   'receipt_hash',receipt.proof_hash,'run_id',receipt.run_id);
  SELECT * INTO operation FROM workflow_requests WHERE tenant_id=NEW.tenant_id
   AND workflow_id=NEW.payload->>'operation_id';
  invocation := operation.payload->'invocation';
  SELECT * INTO proposal FROM resource_proposals WHERE tenant_id=NEW.tenant_id
   AND proposal_id=(NEW.payload->>'proposal_id')::uuid;
  IF cancelled OR published OR NEW.exact_scope IS DISTINCT FROM run.exact_scope
   OR NEW.payload->>'state' IS DISTINCT FROM 'PENDING'
   OR NEW.payload->>'source_node_id' IS DISTINCT FROM gate->>'source_node_id'
   OR NEW.payload->'input_result' IS DISTINCT FROM expected_input
   OR receipt.status IS DISTINCT FROM 'SUCCEEDED' OR output.run_id IS NULL
   OR receipt.exact_scope IS DISTINCT FROM run.exact_scope
   OR receipt.actor_id IS DISTINCT FROM run.actor_id
   OR operation.definition_version IS DISTINCT FROM 'ontology-action/1'
   OR operation.exact_scope IS DISTINCT FROM run.exact_scope
   OR operation.actor_id IS DISTINCT FROM run.actor_id
   OR invocation->>'request_id' IS DISTINCT FROM gate->>'operation_request_id'
   OR invocation->>'binding_id' IS DISTINCT FROM gate->'binding'->>'resource_id'
   OR invocation->>'binding_version_id' IS DISTINCT FROM gate->'binding'->>'version_id'
   OR invocation->>'rationale' IS DISTINCT FROM gate->>'rationale'
   OR invocation->'input_result' IS DISTINCT FROM jsonb_build_object('invocation_id',receipt.request_id::text)
   OR ((invocation->'query') - ARRAY['valid_at','known_at']) IS DISTINCT FROM
      ((output.payload->'query') - ARRAY['valid_at','known_at'])
   OR (invocation->'query'->>'valid_at')::timestamptz IS DISTINCT FROM
      (output.payload->'query'->>'valid_at')::timestamptz
   OR (invocation->'query'->>'known_at')::timestamptz IS DISTINCT FROM
      (output.payload->'query'->>'known_at')::timestamptz
   OR proposal.proposal_id IS NULL OR proposal.submitted_by IS DISTINCT FROM run.actor_id
   OR proposal.payload->'request' IS DISTINCT FROM operation.payload->'prepared_proposal'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(run.payload->'compiled_plan'->'nodes') n
    WHERE NOT EXISTS(SELECT 1 FROM workflow_events e WHERE e.tenant_id=NEW.tenant_id
     AND e.workflow_id=NEW.workflow_id AND e.event_id='node:'||(n->>'node_id')||':terminal'
     AND e.payload->>'state'='COMPLETED'))
  THEN RAISE EXCEPTION 'Binding review must retain the exact completed source and canonical proposal'; END IF;
 ELSIF NEW.event_id LIKE 'binding-review:%' THEN
  RAISE EXCEPTION 'Binding review decisions belong to the canonical resource proposal';
 ELSIF NEW.payload->>'state'='PUBLISHED' OR NEW.event_id='publication-review:task' THEN
  SELECT * INTO decision FROM resource_decisions WHERE tenant_id=NEW.tenant_id
   AND proposal_id=(prepared.payload->>'proposal_id')::uuid;
  IF cancelled OR prepared.event_id IS NULL OR decision.decision IS DISTINCT FROM 'APPROVED'
   OR decision.reviewed_by=run.actor_id
  THEN RAISE EXCEPTION 'Transformation publication requires its canonical binding approval'; END IF;
 ELSIF NEW.payload->>'command'='cancel' AND published THEN
  RAISE EXCEPTION 'Published evidence cannot be cancelled retroactively';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transformation_binding_event_integrity BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION guard_transformation_binding_event();
INSERT INTO schema_migrations VALUES(57);
COMMIT;
