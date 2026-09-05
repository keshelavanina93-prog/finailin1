BEGIN;
CREATE TABLE public.report_source_assessments (
    tenant_id uuid NOT NULL,
    assessment_id text NOT NULL,
    exact_scope jsonb NOT NULL,
    payload jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, assessment_id),
    CHECK (payload->'scope'=exact_scope)
);
ALTER TABLE public.report_source_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_source_assessments FORCE ROW LEVEL SECURITY;
CREATE POLICY report_source_scope ON public.report_source_assessments
USING (tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
WITH CHECK (tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT, INSERT ON public.report_source_assessments TO finai_runtime;
CREATE TRIGGER immutable_report_source_assessment BEFORE UPDATE OR DELETE OR TRUNCATE
ON public.report_source_assessments FOR EACH STATEMENT
EXECUTE FUNCTION public.deny_evidence_mutation();
INSERT INTO schema_migrations VALUES (14);
COMMIT;
