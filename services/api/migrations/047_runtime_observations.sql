BEGIN;
CREATE TABLE runtime_observations (
 tenant_id uuid NOT NULL,request_id uuid NOT NULL,exact_scope jsonb NOT NULL,actor_id text NOT NULL,
 request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),run_id text NOT NULL,
 proof_hash text NOT NULL CHECK(proof_hash ~ '^[a-f0-9]{64}$'),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(tenant_id,request_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES fact_calculation_runs(tenant_id,run_id),
 CHECK((exact_scope->>'tenant_id'=tenant_id::text) IS TRUE)
);
ALTER TABLE runtime_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY runtime_observation_scope ON runtime_observations
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON runtime_observations TO finai_runtime;
CREATE TRIGGER immutable_runtime_observation BEFORE UPDATE OR DELETE OR TRUNCATE
 ON runtime_observations FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE INDEX runtime_observation_history ON runtime_observations(tenant_id,exact_scope,recorded_at DESC,request_id DESC);
CREATE FUNCTION guard_runtime_observation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE output fact_calculation_runs%ROWTYPE; desired resource_versions%ROWTYPE;
 agent resource_versions%ROWTYPE; target resource_versions%ROWTYPE; item jsonb;
 control resource_versions%ROWTYPE; actual jsonb; wanted jsonb; expected text;
BEGIN
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 IF output.run_id IS NULL OR output.exact_scope IS DISTINCT FROM NEW.exact_scope
 OR output.actor_id IS DISTINCT FROM NEW.actor_id OR NEW.proof_hash IS DISTINCT FROM substring(NEW.run_id FROM 5)
 OR output.payload->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR output.payload->>'contract' IS DISTINCT FROM 'runtime-observation/1'
 OR output.payload->>'calculation_runtime' IS DISTINCT FROM 'local-api-observer/1'
 OR output.payload->>'release_provenance' IS DISTINCT FROM 'LOCAL_DEVELOPMENT_UNATTESTED'
 OR output.payload->'deployment_authorized' IS DISTINCT FROM 'false'::jsonb
 OR output.payload->'current_use_authorized' IS DISTINCT FROM 'false'::jsonb
 THEN RAISE EXCEPTION 'Invalid scoped runtime observation evidence'; END IF;
 FOR item IN SELECT output.payload->'desired_state' UNION ALL SELECT output.payload->'runtime_agent'
  UNION ALL SELECT output.payload->'deployment_target' LOOP
  SELECT * INTO control FROM resource_versions WHERE tenant_id=NEW.tenant_id
   AND resource_id=(item->>'resource_id')::uuid AND version_id=(item->>'version_id')::uuid;
  IF control.version_id IS NULL OR control.authority_state<>'APPROVED'
   OR g8_effective_version_id(NEW.tenant_id,control.resource_id,statement_timestamp()) IS DISTINCT FROM control.version_id
   OR item->>'content_hash' IS DISTINCT FROM control.content_hash
   OR item->>'display_name' IS DISTINCT FROM control.display_name
   OR (control.access_entity NOT IN (NEW.exact_scope->>'legal_entity_id','__PLATFORM__'))
  THEN RAISE EXCEPTION 'Current exact runtime control required'; END IF;
 END LOOP;
 SELECT * INTO desired FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND version_id=(output.payload->'desired_state'->>'version_id')::uuid;
 SELECT * INTO agent FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND version_id=(output.payload->'runtime_agent'->>'version_id')::uuid;
 SELECT * INTO target FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND version_id=(output.payload->'deployment_target'->>'version_id')::uuid;
 IF desired.object_type<>'DesiredState' OR agent.object_type<>'RuntimeAgent' OR target.object_type<>'DeploymentTarget'
 OR agent.attributes->'definition'->>'actor_id' IS DISTINCT FROM NEW.actor_id
 OR target.attributes->'definition'->>'component' IS DISTINCT FROM 'api'
 OR target.attributes->'definition'->>'environment_class' IS DISTINCT FROM 'LOCAL_DEVELOPMENT'
 OR output.payload->'desired_definition' IS DISTINCT FROM desired.attributes->'definition'
 OR NOT EXISTS(SELECT 1 FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=desired.version_id
  AND target_resource_id=agent.resource_id AND target_version_id=agent.version_id AND relation='FIELD:runtime_agent_id')
 OR NOT EXISTS(SELECT 1 FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=desired.version_id
  AND target_resource_id=target.resource_id AND target_version_id=target.version_id AND relation='FIELD:deployment_target_id')
 OR NOT EXISTS(SELECT 1 FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=agent.version_id
  AND target_resource_id=target.resource_id AND target_version_id=target.version_id AND relation='FIELD:deployment_target_id')
 THEN RAISE EXCEPTION 'Runtime observation control relationship mismatch'; END IF;
 actual := output.payload->'observation'; wanted := desired.attributes->'definition';
 IF (actual->>'observer_instance_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') IS NOT TRUE
  OR (actual->>'observer_started_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$') IS NOT TRUE
  OR (actual->>'observer_started_at')::timestamptz>(actual->>'observed_at')::timestamptz
  OR (actual->>'database_schema_version' ~ '^[0-9]+$') IS NOT TRUE
  OR jsonb_typeof(actual->'database_schema_version') IS DISTINCT FROM 'number'
  OR (actual->'disk_identity'<>'null'::jsonb AND (
    (actual->'disk_identity'->>'code_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
    OR (actual->'disk_identity'->>'dependency_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE))
 THEN RAISE EXCEPTION 'Schema coverage and disk identity must be explicit'; END IF;
 IF (actual->>'observed_at')::timestamptz>statement_timestamp() OR actual->>'observed_at' IS NULL
 OR actual->>'identity_semantics' IS DISTINCT FROM 'FUNCTION_PACKAGE_STARTUP_SNAPSHOT_NOT_RELEASE_ATTESTATION'
 OR (actual->'loaded_identity'->>'code_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR (actual->'loaded_identity'->>'dependency_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR actual->'disk_matches_loaded' IS DISTINCT FROM to_jsonb(actual->'disk_identity'=actual->'loaded_identity')
 THEN RAISE EXCEPTION 'Invalid local runtime identity observation'; END IF;
 IF actual->'disk_identity'='null'::jsonb OR actual->'disk_identity' IS NULL
 OR actual->'health'->>'database' IS DISTINCT FROM 'ready'
 OR actual->'health'->>'schema' IS DISTINCT FROM 'ready'
 OR actual->'health'->>'evidence_store' IS DISTINCT FROM 'ready' THEN expected := 'DEGRADED';
 ELSIF actual->'disk_matches_loaded'<>'true'::jsonb
 OR actual->'loaded_identity'->>'code_sha256' IS DISTINCT FROM wanted->>'expected_code_sha256'
 OR actual->'loaded_identity'->>'dependency_sha256' IS DISTINCT FROM wanted->>'expected_dependency_sha256'
 OR (actual->>'database_schema_version')::int<(wanted->>'required_schema_version')::int
 THEN expected := 'DRIFT'; ELSE expected := 'MATCH'; END IF;
 IF output.payload->>'recorded_state' IS DISTINCT FROM expected
 THEN RAISE EXCEPTION 'Runtime reconciliation outcome mismatch'; END IF;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER runtime_observation_integrity BEFORE INSERT ON runtime_observations
 FOR EACH ROW EXECUTE FUNCTION guard_runtime_observation();
INSERT INTO schema_migrations VALUES(47);
COMMIT;
