BEGIN;
-- Compatible platform LinkType expansion required by the company-first ontology contract.
-- Preserve every previous version and leave tenant-customized definitions untouched.
DO $$
DECLARE current_record record;
DECLARE next_version uuid;
DECLARE next_attributes jsonb;
BEGIN
    FOR current_record IN
        SELECT v.* FROM resource_heads h
        JOIN resource_versions v USING (tenant_id,resource_id,version_id)
        JOIN canonical_identities i USING (tenant_id,resource_id)
        WHERE i.object_type='LinkType' AND i.identity_key='USES_DOMAIN_PACK'
          AND v.evidence_class='PLATFORM_DEFINITION'
          AND NOT (v.attributes->'sources' ? 'LegalEntity')
    LOOP
        next_version := gen_random_uuid();
        next_attributes := jsonb_set(current_record.attributes,'{sources}',
            '["BusinessDomain","LegalEntity","BusinessUnit","LicensedOperator"]'::jsonb);
        INSERT INTO resource_versions
            (tenant_id,resource_id,version_id,access_entity,object_type,display_name,
             attributes,content_hash,valid_from,authority_state,evidence_class)
        VALUES (current_record.tenant_id,current_record.resource_id,next_version,
            current_record.access_entity,current_record.object_type,current_record.display_name,
            next_attributes,encode(sha256(convert_to(next_attributes::text,'UTF8')),'hex'),
            clock_timestamp(),'APPROVED','PLATFORM_DEFINITION');
        UPDATE resource_heads SET version_id=next_version
            WHERE tenant_id=current_record.tenant_id AND resource_id=current_record.resource_id;
    END LOOP;
END $$;
INSERT INTO schema_migrations VALUES (6);
COMMIT;
