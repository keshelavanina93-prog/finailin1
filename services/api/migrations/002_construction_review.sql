BEGIN;
ALTER TABLE hydration_runs ADD COLUMN IF NOT EXISTS submitted_by text;

CREATE TABLE IF NOT EXISTS construction_decisions (
    tenant_id uuid NOT NULL,
    receipt_id text NOT NULL,
    decision_id uuid NOT NULL,
    exact_scope jsonb NOT NULL,
    decision text NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    actor_id text NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 10 AND 2000),
    previous_head text,
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, receipt_id),
    UNIQUE (tenant_id, decision_id),
    FOREIGN KEY (tenant_id, receipt_id) REFERENCES hydration_runs (tenant_id, receipt_id),
    CHECK (exact_scope->>'tenant_id' = tenant_id::text)
);
CREATE TABLE IF NOT EXISTS workspace_heads (
    tenant_id uuid NOT NULL,
    scope_hash text NOT NULL,
    source_class text NOT NULL,
    exact_scope jsonb NOT NULL,
    receipt_id text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, scope_hash, source_class),
    FOREIGN KEY (tenant_id, receipt_id) REFERENCES construction_decisions (tenant_id, receipt_id),
    CHECK (exact_scope->>'tenant_id' = tenant_id::text)
);
CREATE TABLE IF NOT EXISTS workspace_objects (
    tenant_id uuid NOT NULL,
    object_id text NOT NULL,
    receipt_id text NOT NULL,
    exact_scope jsonb NOT NULL,
    object_index integer NOT NULL CHECK (object_index >= 0),
    object_type text NOT NULL,
    object_payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, receipt_id, object_index),
    FOREIGN KEY (tenant_id, receipt_id) REFERENCES construction_decisions (tenant_id, receipt_id),
    CHECK (exact_scope->>'tenant_id' = tenant_id::text),
    CHECK (object_payload->>'authority_state' = 'APPROVED')
);
CREATE INDEX IF NOT EXISTS hydration_scope_time ON hydration_runs (tenant_id, ingested_at DESC);
CREATE INDEX IF NOT EXISTS objects_scope_type ON workspace_objects (tenant_id, object_type);

DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['construction_decisions', 'workspace_heads', 'workspace_objects'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', target);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', target);
        EXECUTE format('DROP POLICY IF EXISTS tenant_boundary ON %I', target);
        EXECUTE format('CREATE POLICY tenant_boundary ON %I USING (tenant_id::text = current_setting(''finai.tenant_id'', true)) WITH CHECK (tenant_id::text = current_setting(''finai.tenant_id'', true))', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY['construction_decisions', 'workspace_objects'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS immutable_evidence ON %I', target);
        EXECUTE format('CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation()', target);
    END LOOP;
END $$;

-- The deployment migration identity owns tables; the API may only append evidence.
GRANT SELECT, INSERT ON construction_decisions, workspace_objects TO finai_runtime;
GRANT SELECT, INSERT, UPDATE ON workspace_heads TO finai_runtime;
INSERT INTO schema_migrations VALUES (2) ON CONFLICT DO NOTHING;
COMMIT;
