BEGIN;
CREATE TABLE fact_calculation_runs (
 tenant_id uuid NOT NULL, run_id text NOT NULL CHECK(run_id ~ '^fcr_[a-f0-9]{64}$'),
 exact_scope jsonb NOT NULL, payload jsonb NOT NULL,
 actor_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,run_id),
 CHECK(exact_scope->>'tenant_id'=tenant_id::text),
 CHECK(payload->'scope'=exact_scope)
);
ALTER TABLE fact_calculation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_calculation_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY fact_run_scope ON fact_calculation_runs
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON fact_calculation_runs TO finai_runtime;
CREATE TRIGGER immutable_fact_calculation BEFORE UPDATE OR DELETE OR TRUNCATE
 ON fact_calculation_runs FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
CREATE INDEX fact_run_history ON fact_calculation_runs(tenant_id,created_at DESC);
INSERT INTO schema_migrations VALUES (25);
COMMIT;
