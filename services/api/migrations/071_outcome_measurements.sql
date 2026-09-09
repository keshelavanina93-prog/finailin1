BEGIN;
CREATE TABLE public.outcome_measurements (
    tenant_id uuid NOT NULL,
    measurement_id text NOT NULL,
    exact_scope jsonb NOT NULL,
    payload jsonb NOT NULL,
    content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
    actor_id text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, measurement_id),
    CHECK(exact_scope->>'tenant_id'=tenant_id::text),
    CHECK(payload->>'contract'='outcome-measurement/1'),
    CHECK(payload->>'measurement_id'=measurement_id),
    CHECK(payload->'scope'=jsonb_build_object('legal_entity_id', exact_scope->>'legal_entity_id'))
);
ALTER TABLE public.outcome_measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcome_measurements FORCE ROW LEVEL SECURITY;
CREATE POLICY outcome_measurement_exact_scope ON public.outcome_measurements
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT, INSERT ON public.outcome_measurements TO finai_runtime;
CREATE TRIGGER immutable_outcome_measurement BEFORE UPDATE OR DELETE OR TRUNCATE
 ON public.outcome_measurements FOR EACH STATEMENT EXECUTE FUNCTION public.deny_evidence_mutation();
INSERT INTO schema_migrations VALUES (71);
COMMIT;
