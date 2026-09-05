BEGIN;
ALTER TABLE resource_versions ADD CONSTRAINT proposal_or_platform_definition CHECK
    (proposal_id IS NOT NULL OR (evidence_class='PLATFORM_DEFINITION' AND access_entity='__PLATFORM__'));
CREATE OR REPLACE FUNCTION enforce_resource_acceptance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE identity canonical_identities%ROWTYPE;
DECLARE decision resource_decisions%ROWTYPE;
BEGIN
    SELECT * INTO identity FROM canonical_identities WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id;
    IF NOT FOUND OR identity.object_type<>NEW.object_type OR identity.access_entity<>NEW.access_entity THEN
        RAISE EXCEPTION 'Canonical identity type and access boundary are immutable';
    END IF;
    IF NEW.proposal_id IS NOT NULL THEN
        SELECT * INTO decision FROM resource_decisions WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
        IF NOT FOUND OR decision.decision<>'APPROVED' OR decision.access_entity<>NEW.access_entity THEN
            RAISE EXCEPTION 'An approved resource proposal in the same policy context is required';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER approved_resource_version BEFORE INSERT ON resource_versions
    FOR EACH ROW EXECUTE FUNCTION enforce_resource_acceptance();
INSERT INTO schema_migrations VALUES (5);
COMMIT;
