BEGIN;
CREATE TABLE public.learning_candidate_events (
    tenant_id uuid NOT NULL,
    event_id text NOT NULL,
    candidate_id text NOT NULL,
    event_type text NOT NULL CHECK(event_type IN ('EVALUATED','PROMOTION_APPROVED','REJECTED','ROLLBACK_APPROVED')),
    exact_scope jsonb NOT NULL,
    payload jsonb NOT NULL,
    content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
    actor_id text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, event_id),
    UNIQUE (tenant_id, candidate_id, event_type),
    CHECK(exact_scope->>'tenant_id'=tenant_id::text),
    CHECK(payload->>'candidate_id'=candidate_id),
    CHECK(payload->>'event_type'=event_type)
);
CREATE INDEX learning_candidate_events_current_idx
 ON public.learning_candidate_events(tenant_id,candidate_id,recorded_at DESC,event_id DESC);
ALTER TABLE public.learning_candidate_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.learning_candidate_events FORCE ROW LEVEL SECURITY;
CREATE POLICY learning_candidate_event_exact_scope ON public.learning_candidate_events
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
       AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON public.learning_candidate_events TO finai_runtime;
CREATE TRIGGER immutable_learning_candidate_event BEFORE UPDATE OR DELETE OR TRUNCATE
 ON public.learning_candidate_events FOR EACH STATEMENT EXECUTE FUNCTION public.deny_evidence_mutation();
INSERT INTO schema_migrations VALUES (72);
COMMIT;
