BEGIN;
CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS hydration_runs (
    tenant_id uuid NOT NULL,
    receipt_id text NOT NULL,
    exact_scope jsonb NOT NULL,
    source_bytes bytea NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    request jsonb NOT NULL,
    receipt jsonb NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, receipt_id),
    CHECK (exact_scope->>'tenant_id' = tenant_id::text),
    CHECK (receipt->'scope' = exact_scope),
    CHECK (request->'scope' = exact_scope),
    CHECK (receipt->>'authority_state' = 'MAPPED_CANDIDATE'),
    CHECK (encode(sha256(source_bytes), 'hex') = source_sha256)
);
ALTER TABLE hydration_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE hydration_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_boundary ON hydration_runs;
CREATE POLICY tenant_boundary ON hydration_runs
    USING (tenant_id::text = current_setting('finai.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('finai.tenant_id', true));
CREATE OR REPLACE FUNCTION deny_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Retained evidence is immutable'; END;
$$;
DROP TRIGGER IF EXISTS immutable_evidence ON hydration_runs;
CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE OR TRUNCATE ON hydration_runs
    FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
INSERT INTO schema_migrations VALUES (1) ON CONFLICT DO NOTHING;
COMMIT;
