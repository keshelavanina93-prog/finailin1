BEGIN;
CREATE TABLE journal_production_attempts (
 tenant_id uuid NOT NULL, request_id uuid NOT NULL,
 phase text NOT NULL CHECK(phase IN ('PREPARED','SUBMITTED')),
 exact_scope jsonb NOT NULL, actor_id text NOT NULL,
 request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 receipt_hash text NOT NULL CHECK(receipt_hash ~ '^[a-f0-9]{64}$'),
 payload jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,request_id,phase),
 CHECK(exact_scope->>'tenant_id'=tenant_id::text),
 CHECK((payload->>'contract') IS NOT DISTINCT FROM 'source-journal-production/1'),
 CHECK(payload ? 'receipt_hash' AND payload->>'receipt_hash'=receipt_hash),
 CHECK(payload ? 'rows' AND jsonb_typeof(payload->'rows')='array')
);
ALTER TABLE journal_production_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_production_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY journal_production_exact_scope ON journal_production_attempts
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON journal_production_attempts TO finai_runtime;
CREATE TRIGGER immutable_journal_production_attempt BEFORE UPDATE OR DELETE OR TRUNCATE
 ON journal_production_attempts FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
INSERT INTO schema_migrations VALUES(63);
COMMIT;
