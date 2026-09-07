BEGIN;
CREATE INDEX transformation_history_page ON workflow_requests
 (tenant_id,exact_scope,created_at DESC,workflow_id DESC)
 WHERE definition_version='transformation-functions/1';
INSERT INTO schema_migrations VALUES(44);
COMMIT;
