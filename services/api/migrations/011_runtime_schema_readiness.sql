BEGIN;
GRANT SELECT ON schema_migrations TO finai_runtime;
INSERT INTO schema_migrations VALUES (11);
COMMIT;
