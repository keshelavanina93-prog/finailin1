BEGIN;
CREATE INDEX resource_proposal_recency ON resource_proposals(tenant_id,created_at DESC,proposal_id);
CREATE INDEX resource_identity_type ON canonical_identities(tenant_id,object_type,resource_id);
INSERT INTO schema_migrations VALUES(30);
COMMIT;
