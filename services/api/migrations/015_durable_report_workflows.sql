BEGIN;
CREATE TABLE workflow_requests (
 tenant_id uuid NOT NULL, workflow_id text NOT NULL, exact_scope jsonb NOT NULL,
 actor_id text NOT NULL, definition_version text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,workflow_id)
);
CREATE TABLE workflow_events (
 tenant_id uuid NOT NULL, workflow_id text NOT NULL, exact_scope jsonb NOT NULL,
 event_id text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,workflow_id,event_id),
 FOREIGN KEY(tenant_id,workflow_id) REFERENCES workflow_requests
);
ALTER TABLE workflow_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_events FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_request_scope ON workflow_requests
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
CREATE POLICY workflow_event_scope ON workflow_events
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON workflow_requests,workflow_events TO finai_runtime;
CREATE TRIGGER immutable_workflow_requests BEFORE UPDATE OR DELETE OR TRUNCATE
 ON workflow_requests FOR EACH STATEMENT EXECUTE FUNCTION public.deny_evidence_mutation();
CREATE TRIGGER immutable_workflow_events BEFORE UPDATE OR DELETE OR TRUNCATE
 ON workflow_events FOR EACH STATEMENT EXECUTE FUNCTION public.deny_evidence_mutation();
INSERT INTO schema_migrations VALUES(15);
COMMIT;
