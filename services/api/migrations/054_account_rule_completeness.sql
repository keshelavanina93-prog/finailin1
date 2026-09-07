BEGIN;
-- Visibility-limited lists cannot prove that no required rule exists. This
-- helper returns membership completeness only, never hidden rule identities.
CREATE FUNCTION public.g8_account_rule_set_complete(
 tenant uuid, account uuid, account_version uuid, rule_versions uuid[], at_time timestamptz
) RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE subject public.resource_versions%ROWTYPE; rule public.resource_versions%ROWTYPE;
 actual uuid[] := ARRAY[]::uuid[]; requested uuid[]; caller_entity text;
 tenant_access boolean;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true)
  OR at_time IS NULL OR at_time>clock_timestamp() OR rule_versions IS NULL
  OR cardinality(rule_versions)>32 OR array_position(rule_versions,NULL) IS NOT NULL
  OR cardinality(rule_versions)<>(SELECT count(DISTINCT value) FROM unnest(rule_versions) value)
 THEN RETURN false; END IF;
 caller_entity := current_setting('finai.entity_id',true);
 tenant_access := coalesce(current_setting('finai.tenant_access',true),'')='true';
 SELECT * INTO subject FROM public.resource_versions v WHERE v.tenant_id=tenant
 AND v.resource_id=account AND v.version_id=account_version
 AND v.version_id=public.g8_effective_version_id(tenant,account,at_time);
 IF subject.version_id IS NULL OR subject.object_type IS DISTINCT FROM 'LocalAccount'
  OR subject.authority_state IS DISTINCT FROM 'APPROVED'
  OR (subject.access_entity=caller_entity OR subject.access_entity='__PLATFORM__' OR tenant_access) IS NOT TRUE
  OR public.g8_can_read_version(tenant,account_version) IS NOT TRUE
 THEN RETURN false; END IF;
 FOR rule IN SELECT v.* FROM public.resource_versions v WHERE v.tenant_id=tenant
  AND v.object_type='AccountDimensionRule' AND v.attributes->>'account_id'=account::text
  AND v.version_id=public.g8_effective_version_id(tenant,v.resource_id,at_time)
  AND v.authority_state='APPROVED'
 LOOP
  IF rule.access_entity IS DISTINCT FROM subject.access_entity
   OR (rule.access_entity=caller_entity OR rule.access_entity='__PLATFORM__' OR tenant_access) IS NOT TRUE
   OR public.g8_can_read_version(tenant,rule.version_id) IS NOT TRUE
   OR NOT EXISTS(SELECT 1 FROM public.resource_dependencies d WHERE d.tenant_id=tenant
    AND d.version_id=rule.version_id AND d.relation='FIELD:account_id'
    AND d.target_resource_id=account AND d.target_version_id=account_version)
  THEN RETURN false; END IF;
  actual := array_append(actual,rule.version_id);
  IF cardinality(actual)>32 THEN RETURN false; END IF;
 END LOOP;
 SELECT coalesce(array_agg(value ORDER BY value),ARRAY[]::uuid[]) INTO actual FROM unnest(actual) value;
 SELECT coalesce(array_agg(value ORDER BY value),ARRAY[]::uuid[]) INTO requested FROM unnest(rule_versions) value;
 RETURN actual=requested;
END $$;
ALTER FUNCTION public.g8_account_rule_set_complete(uuid,uuid,uuid,uuid[],timestamptz)
 OWNER TO finai_policy_reader;
REVOKE ALL ON FUNCTION public.g8_account_rule_set_complete(uuid,uuid,uuid,uuid[],timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_account_rule_set_complete(uuid,uuid,uuid,uuid[],timestamptz) TO finai_runtime;
INSERT INTO schema_migrations VALUES(54);
COMMIT;
