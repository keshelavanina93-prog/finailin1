BEGIN;
-- Scope and exact artifact equality precede the stable reverse-chronological page key.
CREATE INDEX artifact_retention_history ON artifact_retention_evaluations
 (tenant_id,exact_scope,(payload->'artifact'->'reference'),recorded_at DESC,evaluation_id DESC);
INSERT INTO schema_migrations VALUES(41);
COMMIT;
