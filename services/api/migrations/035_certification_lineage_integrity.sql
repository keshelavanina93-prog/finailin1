BEGIN;
-- Typed, reviewed control definitions may be shared with bootstrap definitions.
ALTER TABLE resource_versions DROP CONSTRAINT resource_versions_check1;
ALTER TABLE resource_versions ADD CONSTRAINT resource_versions_platform_type_check
 CHECK(access_entity<>'__PLATFORM__' OR object_type IN
 ('SchemaDefinition','SemanticContract','LinkType','CertificationContract'));
CREATE FUNCTION guard_certification_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root uuid; field text; versions uuid[]; edges integer; item jsonb;
 ancestor resource_versions%ROWTYPE; event resource_lifecycle_events%ROWTYPE;
BEGIN
 IF NEW.payload->'contract_attributes'->>'subject_schema_id' IS NULL AND
 NEW.payload->'subject_schema' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Bootstrap certification cannot invent a subject schema pin';
 END IF;
 FOREACH field IN ARRAY ARRAY['subject_upstream','contract_upstream'] LOOP
   root := CASE WHEN field='subject_upstream' THEN NEW.subject_version_id ELSE NEW.contract_version_id END;
   WITH RECURSIVE lineage(version_id) AS (
     SELECT target_version_id FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND version_id=root
     UNION SELECT d.target_version_id FROM resource_dependencies d JOIN lineage l ON d.version_id=l.version_id
     WHERE d.tenant_id=NEW.tenant_id
   ) SELECT coalesce(array_agg(version_id),'{}'::uuid[]) INTO versions FROM lineage WHERE version_id<>root;
   SELECT count(*) INTO edges FROM (SELECT DISTINCT version_id,target_resource_id,target_version_id
   FROM resource_dependencies WHERE tenant_id=NEW.tenant_id AND
   (version_id=root OR version_id=ANY(versions))) d;
   IF jsonb_typeof(NEW.payload->field) IS DISTINCT FROM 'array' OR cardinality(versions)>999 OR edges>5000
   OR jsonb_array_length(NEW.payload->field)<>cardinality(versions)
   OR (SELECT count(DISTINCT value->>'version_id') FROM jsonb_array_elements(NEW.payload->field))<>cardinality(versions)
   THEN RAISE EXCEPTION 'Incomplete certification lineage proof'; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.payload->field) LOOP
     SELECT * INTO ancestor FROM resource_versions WHERE tenant_id=NEW.tenant_id
     AND version_id=(item->>'version_id')::uuid;
     SELECT * INTO event FROM resource_lifecycle_events WHERE tenant_id=NEW.tenant_id
     AND version_id=ancestor.version_id ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
     IF ancestor.version_id IS NULL OR NOT(ancestor.version_id=ANY(versions))
     OR ancestor.resource_id::text IS DISTINCT FROM item->>'resource_id'
     OR ancestor.content_hash IS DISTINCT FROM item->>'content_hash'
     OR ancestor.access_entity IS DISTINCT FROM item->>'access_entity'
     OR ancestor.authority_state<>'APPROVED'
     OR g8_effective_version_id(NEW.tenant_id,ancestor.resource_id,statement_timestamp()) IS DISTINCT FROM ancestor.version_id
     OR event.event_id::text IS DISTINCT FROM item->>'event_id'
     OR (NEW.access_entity<>'__TENANT__' AND ancestor.access_entity NOT IN (NEW.access_entity,'__PLATFORM__'))
     OR (event.event_id IS NOT NULL AND (event.payload->>'target_state' IN ('REVOKED','SUPERSEDED')
         OR event.payload->>'availability_state' IS DISTINCT FROM 'AVAILABLE'))
     THEN RAISE EXCEPTION 'Certification lineage authority unavailable or proof mismatch'; END IF;
   END LOOP;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER certification_lineage_integrity BEFORE INSERT ON certification_receipts
 FOR EACH ROW EXECUTE FUNCTION guard_certification_lineage();
INSERT INTO schema_migrations VALUES(35);
COMMIT;
