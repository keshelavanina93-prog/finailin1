BEGIN;
CREATE TABLE source_documents (
 tenant_id uuid NOT NULL, document_id text NOT NULL,
 exact_scope jsonb NOT NULL, source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 filename text NOT NULL, storage jsonb NOT NULL, actor_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,document_id),
 CHECK(exact_scope->>'tenant_id'=tenant_id::text)
);
ALTER TABLE source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY source_document_scope ON source_documents
 USING(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb)
 WITH CHECK(tenant_id::text=current_setting('finai.tenant_id',true)
 AND exact_scope=current_setting('finai.exact_scope',true)::jsonb);
GRANT SELECT,INSERT ON source_documents TO finai_runtime;
CREATE TRIGGER immutable_source_document BEFORE UPDATE OR DELETE OR TRUNCATE
 ON source_documents FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation();
INSERT INTO schema_migrations VALUES(26);
COMMIT;
