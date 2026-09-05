BEGIN;
CREATE TABLE canonical_identities (
    tenant_id uuid NOT NULL, resource_id uuid NOT NULL, object_type text NOT NULL,
    identity_key text NOT NULL, access_entity text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, resource_id),
    UNIQUE (tenant_id, object_type, access_entity, identity_key)
);
CREATE TABLE resource_proposals (
    tenant_id uuid NOT NULL, proposal_id uuid NOT NULL, access_entity text NOT NULL,
    submitted_by text NOT NULL, title text NOT NULL, rationale text NOT NULL,
    request_hash text NOT NULL, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, proposal_id)
);
CREATE TABLE resource_decisions (
    tenant_id uuid NOT NULL, proposal_id uuid NOT NULL, access_entity text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('APPROVED','REJECTED')),
    reviewed_by text NOT NULL, rationale text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, proposal_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES resource_proposals (tenant_id, proposal_id)
);
CREATE TABLE resource_versions (
    tenant_id uuid NOT NULL, resource_id uuid NOT NULL, version_id uuid NOT NULL,
    access_entity text NOT NULL, object_type text NOT NULL, display_name text NOT NULL,
    schema_version_id uuid, attributes jsonb NOT NULL, content_hash text NOT NULL,
    valid_from timestamptz NOT NULL, valid_to timestamptz,
    system_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    authority_state text NOT NULL CHECK (authority_state IN ('APPROVED','REVOKED')),
    evidence_class text NOT NULL CHECK (evidence_class IN ('USER_ASSERTED','SOURCE_BOUND','REFERENCE_TEMPLATE','PLATFORM_DEFINITION')),
    proposal_id uuid,
    PRIMARY KEY (tenant_id, version_id),
    UNIQUE (tenant_id, resource_id, version_id),
    FOREIGN KEY (tenant_id, resource_id) REFERENCES canonical_identities (tenant_id, resource_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES resource_decisions (tenant_id, proposal_id),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (access_entity <> '__PLATFORM__' OR object_type IN ('SchemaDefinition','SemanticContract','LinkType'))
);
CREATE TABLE resource_heads (
    tenant_id uuid NOT NULL, resource_id uuid NOT NULL, version_id uuid NOT NULL, access_entity text NOT NULL,
    PRIMARY KEY (tenant_id, resource_id),
    FOREIGN KEY (tenant_id, resource_id, version_id) REFERENCES resource_versions (tenant_id, resource_id, version_id)
);
CREATE TABLE resource_dependencies (
    tenant_id uuid NOT NULL, version_id uuid NOT NULL, target_resource_id uuid NOT NULL,
    target_version_id uuid NOT NULL, relation text NOT NULL, access_entity text NOT NULL,
    PRIMARY KEY (tenant_id, version_id, target_version_id, relation),
    FOREIGN KEY (tenant_id, version_id) REFERENCES resource_versions (tenant_id, version_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tenant_id, target_resource_id, target_version_id) REFERENCES resource_versions (tenant_id, resource_id, version_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX resource_type_search ON resource_versions (tenant_id, object_type, system_from DESC);
CREATE INDEX resource_history ON resource_versions (tenant_id, resource_id, system_from DESC);
CREATE INDEX resource_attributes ON resource_versions USING gin (attributes);
CREATE INDEX dependency_reverse ON resource_dependencies (tenant_id, target_resource_id);
CREATE OR REPLACE FUNCTION canonical_review_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE author text;
BEGIN
    SELECT submitted_by INTO author FROM resource_proposals
        WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id AND access_entity=NEW.access_entity;
    IF author IS NULL OR author=NEW.reviewed_by THEN RAISE EXCEPTION 'Independent resource reviewer required'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER independent_resource_review BEFORE INSERT ON resource_decisions
    FOR EACH ROW EXECUTE FUNCTION canonical_review_guard();

DO $$ DECLARE target text; BEGIN
    FOREACH target IN ARRAY ARRAY['canonical_identities','resource_proposals','resource_decisions','resource_versions','resource_heads','resource_dependencies'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', target);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', target);
        EXECUTE format('CREATE POLICY resource_access ON %I USING (tenant_id::text=current_setting(''finai.tenant_id'',true) AND (access_entity=current_setting(''finai.entity_id'',true) OR access_entity=''__PLATFORM__'' OR current_setting(''finai.tenant_access'',true)=''true'')) WITH CHECK (tenant_id::text=current_setting(''finai.tenant_id'',true) AND (access_entity=current_setting(''finai.entity_id'',true) OR current_setting(''finai.tenant_access'',true)=''true''))', target);
        EXECUTE format('GRANT SELECT, INSERT ON %I TO finai_runtime', target);
        IF target <> 'resource_heads' THEN
            EXECUTE format('CREATE TRIGGER immutable_resource BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION deny_evidence_mutation()', target);
        END IF;
    END LOOP;
END $$;
GRANT UPDATE ON resource_heads TO finai_runtime;
INSERT INTO schema_migrations VALUES (4);
COMMIT;
