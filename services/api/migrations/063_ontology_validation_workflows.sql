BEGIN;
-- Guard retained identities and publication linkage. The bounded worker and
-- authorized service establish validation semantics; SQL does not run SHACL.
CREATE FUNCTION guard_ontology_validation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE plan jsonb; request jsonb; pin jsonb; resource resource_versions%ROWTYPE;
BEGIN
 IF NEW.definition_version<>'ontology-validation/1' THEN RETURN NEW; END IF;
 plan := NEW.payload->'plan'; request := NEW.payload->'request';
 IF NEW.workflow_id IS DISTINCT FROM 'ontology-validation:'||(request->>'request_id')
 OR (request->>'request_id' ~ '^[a-f0-9-]{36}$') IS NOT TRUE
 OR NEW.exact_scope->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR plan->>'contract' IS DISTINCT FROM 'ontology-validation-plan/1'
 OR plan->>'validator' IS DISTINCT FROM 'pyshacl/0.40.1-core-offline/1'
 OR plan->'business_effect_authorized' IS DISTINCT FROM 'false'::jsonb
 OR (plan->>'request_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR (plan->>'validator_manifest_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR (NEW.payload->>'plan_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR request->'constraint_profile' IS DISTINCT FROM plan->'constraint_profile'
 OR request->'data'->'release' IS DISTINCT FROM plan->'data'->'release'
 OR request->'data'->'graph_iris' IS DISTINCT FROM plan->'data'->'graph_iris'
 OR NEW.payload->'definition' IS DISTINCT FROM '{"version":"ontology-validation/1","nodes":[{"id":"validate","function":"pyshacl/0.40.1-core-offline/1","depends_on":[]}],"outputs":{"report":"ontology-validation-report/1"}}'::jsonb
 THEN RAISE EXCEPTION 'Exact ontology validation intent required'; END IF;
 FOR pin IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
  jsonb_build_object('pin',plan->'ontology_profile','type','OntologyProfile'),
  jsonb_build_object('pin',plan->'constraint_profile','type','ExternalConstraintProfile'),
  jsonb_build_object('pin',plan->'data'->'release','type','ExternalOntologyRelease'),
  jsonb_build_object('pin',plan->'shapes'->'release','type','ExternalOntologyRelease'))) LOOP
  SELECT * INTO resource FROM resource_versions WHERE tenant_id=NEW.tenant_id
   AND resource_id=(pin->'pin'->>'resource_id')::uuid
   AND version_id=(pin->'pin'->>'version_id')::uuid;
  IF resource.version_id IS NULL OR resource.object_type IS DISTINCT FROM pin->>'type'
   OR resource.content_hash IS DISTINCT FROM pin->'pin'->>'content_hash'
   OR resource.access_entity IS DISTINCT FROM NEW.exact_scope->>'legal_entity_id'
   OR resource.authority_state IS DISTINCT FROM 'APPROVED'
   OR g8_effective_version_id(NEW.tenant_id,resource.resource_id,statement_timestamp())
      IS DISTINCT FROM resource.version_id
  THEN RAISE EXCEPTION 'Validation requires approved exact scoped inputs'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER ontology_validation_intent_integrity BEFORE INSERT ON workflow_requests
 FOR EACH ROW EXECUTE FUNCTION guard_ontology_validation_intent();

CREATE FUNCTION guard_ontology_validation_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run workflow_requests%ROWTYPE; previous jsonb; terminal jsonb; report jsonb;
 staged workflow_events%ROWTYPE; output jsonb;
BEGIN
 SELECT * INTO run FROM workflow_requests WHERE tenant_id=NEW.tenant_id AND workflow_id=NEW.workflow_id;
 IF run.definition_version IS DISTINCT FROM 'ontology-validation/1' THEN RETURN NEW; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('ontology-validation:'||NEW.tenant_id::text||':'||NEW.workflow_id,0));
 IF NEW.exact_scope IS DISTINCT FROM run.exact_scope
 THEN RAISE EXCEPTION 'Validation event scope mismatch'; END IF;
 SELECT payload INTO previous FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id=NEW.event_id;
 IF previous IS NOT NULL THEN
  IF previous IS DISTINCT FROM NEW.payload THEN RAISE EXCEPTION 'Validation event identity conflict'; END IF;
  RETURN NEW;
 END IF;
 IF EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='validation:cancelled')
 THEN RAISE EXCEPTION 'Cancelled validation cannot append execution events'; END IF;
 SELECT payload INTO terminal FROM workflow_events WHERE tenant_id=NEW.tenant_id
  AND workflow_id=NEW.workflow_id AND event_id='validation:terminal';
 IF NEW.event_id='validation:started' THEN
  IF NEW.payload IS DISTINCT FROM '{"state":"RUNNING"}'::jsonb OR terminal IS NOT NULL
  THEN RAISE EXCEPTION 'Invalid validation start event'; END IF;
 ELSIF NEW.event_id='validation:cancelled' THEN
  IF NEW.payload->>'state' IS DISTINCT FROM 'CANCELLED'
   OR NEW.payload->>'command' IS DISTINCT FROM 'cancel'
   OR NEW.payload->>'actor_id' IS DISTINCT FROM run.actor_id
   OR (NEW.payload->>'idempotency_key' ~ '^[a-f0-9-]{36}$') IS NOT TRUE
   OR length(trim(NEW.payload->>'reason')) NOT BETWEEN 10 AND 2000
   OR NEW.payload->>'reason' IS NULL
   OR EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
    AND workflow_id=NEW.workflow_id AND event_id='publication:0')
  THEN RAISE EXCEPTION 'Invalid validation cancellation'; END IF;
 ELSIF NEW.event_id='validation:terminal' THEN
  report := NEW.payload->'report';
  IF NEW.payload->>'state' IS DISTINCT FROM 'COMPLETED'
   OR report->>'contract' IS DISTINCT FROM 'ontology-validation-report/1'
   OR report->>'workflow_id' IS DISTINCT FROM NEW.workflow_id
   OR report->>'request_sha256' IS DISTINCT FROM run.payload->'plan'->>'request_sha256'
   OR report->>'plan_sha256' IS DISTINCT FROM run.payload->>'plan_sha256'
   OR report->'business_effect_authorized' IS DISTINCT FROM 'false'::jsonb
   OR (report->>'outcome' IN ('CONFORMS','VIOLATES','NOT_EVALUATED','REFUSED')) IS NOT TRUE
   OR NOT EXISTS(SELECT 1 FROM workflow_events WHERE tenant_id=NEW.tenant_id
    AND workflow_id=NEW.workflow_id AND event_id='validation:started')
   OR NOT EXISTS(SELECT 1 FROM source_documents WHERE tenant_id=NEW.tenant_id
    AND exact_scope=NEW.exact_scope AND document_id=report->'report'->>'document_id'
    AND source_sha256=report->'report'->>'sha256')
  THEN RAISE EXCEPTION 'Validation terminal requires exact retained report evidence'; END IF;
 ELSIF NEW.payload->>'state'='STAGED' THEN
  IF terminal IS NULL OR NEW.payload->>'node' IS DISTINCT FROM 'report'
   OR (NEW.event_id ~ '^output:[a-f0-9]{64}$') IS NOT TRUE
   OR NEW.payload->>'artifact_type' IS DISTINCT FROM 'ontology-validation-report/1'
   OR NEW.payload->'generation' IS DISTINCT FROM '0'::jsonb
   OR NEW.payload->'value' IS DISTINCT FROM terminal->'report'
   OR (NEW.payload->>'sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
  THEN RAISE EXCEPTION 'Validation stage requires the exact terminal report'; END IF;
 ELSIF NEW.event_id='publication:0' THEN
  IF terminal IS NULL OR NEW.payload->>'state' IS DISTINCT FROM 'PUBLISHED'
   OR NEW.payload->'manifest'->>'workflow_id' IS DISTINCT FROM NEW.workflow_id
   OR NEW.payload->'manifest'->>'authority' IS DISTINCT FROM 'EXECUTION_ONLY'
   OR NEW.payload->'manifest'->'generation' IS DISTINCT FROM '0'::jsonb
   OR jsonb_typeof(NEW.payload->'manifest'->'outputs') IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.payload->'manifest'->'outputs')<>1
  THEN RAISE EXCEPTION 'Invalid validation publication'; END IF;
  output := NEW.payload->'manifest'->'outputs'->0;
  SELECT * INTO staged FROM workflow_events WHERE tenant_id=NEW.tenant_id
   AND workflow_id=NEW.workflow_id AND event_id=output->>'event_id';
  IF staged.event_id IS NULL OR staged.payload->>'state' IS DISTINCT FROM 'STAGED'
   OR output->>'slot' IS DISTINCT FROM 'report'
   OR output->>'artifact_type' IS DISTINCT FROM 'ontology-validation-report/1'
   OR output->'value' IS DISTINCT FROM terminal->'report'
   OR output->'value' IS DISTINCT FROM staged.payload->'value'
   OR output->'sha256' IS DISTINCT FROM staged.payload->'sha256'
  THEN RAISE EXCEPTION 'Validation publication requires exact staged evidence'; END IF;
 ELSE RAISE EXCEPTION 'Undeclared ontology validation event';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ontology_validation_event_integrity BEFORE INSERT ON workflow_events
 FOR EACH ROW EXECUTE FUNCTION guard_ontology_validation_event();
INSERT INTO schema_migrations VALUES(63);
COMMIT;
