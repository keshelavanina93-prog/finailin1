BEGIN;
-- A deferred dependency check needs one approved pin, not the complete proposal
-- read projection on every inserted edge. This helper exposes only membership.
-- Source/target RLS, proposal review, version acceptance and all read policies remain.
CREATE OR REPLACE FUNCTION public.g8_approved_dependency_pin(
 tenant uuid, proposal uuid, source_resource uuid, target_resource uuid,
 target_version uuid, relation_name text
) RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE retained jsonb; source_version uuid; source_scope text;
BEGIN
 IF tenant::text IS DISTINCT FROM current_setting('finai.tenant_id',true) THEN RETURN false; END IF;
 SELECT version_id,access_entity INTO source_version,source_scope FROM public.resource_versions
 WHERE tenant_id=tenant AND resource_id=source_resource AND proposal_id=proposal;
 IF source_version IS NULL OR NOT coalesce((
  source_scope='__PLATFORM__' OR source_scope=current_setting('finai.entity_id',true)
  OR current_setting('finai.tenant_access',true)='true'
 ),false) OR NOT public.g8_can_read_version(tenant,source_version) THEN RETURN false; END IF;
 SELECT payload->'validation'->'dependencies'->source_resource::text INTO retained
 FROM public.resource_proposals WHERE tenant_id=tenant AND proposal_id=proposal;
 RETURN retained IS NOT NULL AND EXISTS (
  SELECT 1 FROM jsonb_array_elements(retained) d
  WHERE d->>'resource_id'=target_resource::text AND d->>'version_id'=target_version::text
   AND d->>'relation'=relation_name
 );
END $$;
ALTER FUNCTION public.g8_approved_dependency_pin(uuid,uuid,uuid,uuid,uuid,text)
 OWNER TO finai_policy_reader;
REVOKE ALL ON FUNCTION public.g8_approved_dependency_pin(uuid,uuid,uuid,uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.g8_approved_dependency_pin(uuid,uuid,uuid,uuid,uuid,text) TO finai_runtime;

CREATE OR REPLACE FUNCTION public.enforce_dependency_acceptance() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source public.resource_versions%ROWTYPE;
DECLARE target public.resource_versions%ROWTYPE;
BEGIN
 SELECT * INTO source FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=NEW.version_id;
 SELECT * INTO target FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=NEW.target_version_id;
 IF source.version_id IS NULL OR target.version_id IS NULL OR
  NEW.access_entity IS DISTINCT FROM source.access_entity OR
  NEW.target_resource_id IS DISTINCT FROM target.resource_id OR
  (source.access_entity<>'__TENANT__' AND target.access_entity NOT IN(source.access_entity,'__PLATFORM__')) THEN
  RAISE EXCEPTION 'Dependency cannot broaden its source resource policy';
 END IF;
 IF source.proposal_id IS NOT NULL AND NOT public.g8_approved_dependency_pin(
  NEW.tenant_id,source.proposal_id,source.resource_id,NEW.target_resource_id,NEW.target_version_id,NEW.relation
 ) THEN
  RAISE EXCEPTION 'Dependency must match its approved version pin';
 END IF;
 RETURN NEW;
END $$;
INSERT INTO schema_migrations VALUES(27);
COMMIT;
