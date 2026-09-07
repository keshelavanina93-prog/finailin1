BEGIN;
CREATE FUNCTION guard_grouped_observation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; grouping_schema resource_versions%ROWTYPE;
 config jsonb; fields jsonb;
BEGIN
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=(NEW.request->'function'->>'resource_id')::uuid
 AND version_id=(NEW.request->'function'->>'version_id')::uuid;
 config := definition.attributes->'definition'->'group_count';
 IF config IS NULL OR config='null'::jsonb THEN
  IF NEW.plan ? 'group_count' THEN RAISE EXCEPTION 'Undeclared observation grouping'; END IF;
  RETURN NEW;
 END IF;
 fields := config->'fields';
 IF definition.attributes->'definition'->>'implementation_id'
  IS DISTINCT FROM 'ontology.object-set-derived/v1'
 OR jsonb_typeof(fields) IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Typed observation grouping required'; END IF;
 IF jsonb_array_length(fields) NOT BETWEEN 1 AND 4
 OR jsonb_array_length(fields)<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(fields))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(fields) f WHERE jsonb_typeof(f)<>'string')
 OR NEW.request->'offset' IS DISTINCT FROM '0'::jsonb
 THEN RAISE EXCEPTION 'Complete bounded observation grouping required'; END IF;
 SELECT v.* INTO grouping_schema FROM resource_dependencies d JOIN resource_versions v
 ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
 AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
 AND d.version_id=definition.version_id AND d.relation='FUNCTION_GROUP_SCHEMA'
 AND v.resource_id=(config->>'schema_id')::uuid;
 IF grouping_schema.version_id IS NULL OR grouping_schema.object_type<>'SchemaDefinition'
 OR grouping_schema.authority_state<>'APPROVED'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(fields) f WHERE
   (grouping_schema.attributes->'fields'->f->>'kind'
    IN ('text','identifier','integer','decimal','boolean','reference','date','datetime')) IS NOT TRUE)
 OR NEW.plan->'group_count' IS DISTINCT FROM jsonb_build_object(
  'fields',fields,'schema',jsonb_build_object('resource_id',grouping_schema.resource_id::text,
   'version_id',grouping_schema.version_id::text,'content_hash',grouping_schema.content_hash))
 THEN RAISE EXCEPTION 'Exact observation grouping schema required'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER grouped_observation_intent BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_grouped_observation_intent();

CREATE FUNCTION guard_grouped_observation_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; retained fact_calculation_runs%ROWTYPE;
 grouped jsonb; expected jsonb; source_count integer; schema_type text;
BEGIN
 IF NEW.status<>'SUCCEEDED' THEN RETURN NEW; END IF;
 SELECT * INTO intent FROM function_invocations
 WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 SELECT * INTO retained FROM fact_calculation_runs
 WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 grouped := retained.payload->'group_counts';
 IF NOT(intent.plan ? 'group_count') THEN
  IF grouped IS NOT NULL THEN RAISE EXCEPTION 'Undeclared grouped observation result'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(retained.payload->'objects') IS DISTINCT FROM 'array'
 OR jsonb_typeof(grouped->'groups') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Retained grouping objects and groups required'; END IF;
 source_count := jsonb_array_length(retained.payload->'objects');
 IF grouped->>'contract' IS DISTINCT FROM 'grouped-observation-counts/1'
 OR grouped->>'authority' IS DISTINCT FROM 'OBSERVATION_COUNTS_ONLY'
 OR grouped->>'coverage' IS DISTINCT FROM 'COMPLETE_BOUNDED_OBJECT_SET'
 OR grouped->'schema' IS DISTINCT FROM intent.plan->'group_count'->'schema'
 OR grouped->'fields' IS DISTINCT FROM intent.plan->'group_count'->'fields'
 OR grouped->'object_count' IS DISTINCT FROM to_jsonb(source_count)
 OR retained.payload->'total' IS DISTINCT FROM to_jsonb(source_count)
 OR retained.payload->'query'->'offset' IS DISTINCT FROM '0'::jsonb
 OR retained.payload->'next_offset' IS DISTINCT FROM 'null'::jsonb
 OR source_count>least((intent.request->>'limit')::integer,200)
 OR source_count<>(SELECT count(DISTINCT value->>'resource_id')
   FROM jsonb_array_elements(retained.payload->'objects'))
 THEN RAISE EXCEPTION 'Observation counts require the complete bounded set'; END IF;
 SELECT i.identity_key INTO schema_type FROM canonical_identities i
 WHERE i.tenant_id=NEW.tenant_id
 AND i.resource_id=(grouped->'schema'->>'resource_id')::uuid AND i.object_type='SchemaDefinition';
 IF schema_type IS NULL OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(retained.payload->'objects') o
  LEFT JOIN resource_versions v ON v.tenant_id=NEW.tenant_id
   AND v.resource_id=(o->>'resource_id')::uuid AND v.version_id=(o->>'version_id')::uuid
  LEFT JOIN canonical_identities i ON i.tenant_id=v.tenant_id AND i.resource_id=v.resource_id
  WHERE v.version_id IS NULL OR v.object_type IS DISTINCT FROM schema_type
   OR v.schema_version_id::text IS DISTINCT FROM grouped->'schema'->>'version_id'
   OR (to_jsonb(v)-'tenant_id' || jsonb_build_object('identity_key',i.identity_key)) IS DISTINCT FROM o
   OR v.system_from>(intent.request->>'known_at')::timestamptz)
 THEN RAISE EXCEPTION 'Observation grouping requires exact canonical source versions'; END IF;
 WITH keyed AS (
  SELECT o AS object, (
   SELECT jsonb_agg(jsonb_build_object('field',field,'state',
    CASE WHEN NOT(o->'attributes' ? field) THEN 'MISSING'
     WHEN o->'attributes'->field='null'::jsonb THEN 'NULL' ELSE 'VALUE' END)
    || CASE WHEN o->'attributes' ? field AND o->'attributes'->field<>'null'::jsonb
       THEN jsonb_build_object('value',o->'attributes'->field) ELSE '{}'::jsonb END
    ORDER BY ordinal)
   FROM jsonb_array_elements_text(grouped->'fields') WITH ORDINALITY f(field,ordinal)
  ) AS key
  FROM jsonb_array_elements(retained.payload->'objects') o
 ), counts AS (
  SELECT jsonb_build_object('key',key,'count',count(*),'contributors',
   jsonb_agg(jsonb_build_object('resource_id',object->>'resource_id',
    'version_id',object->>'version_id','content_hash',object->>'content_hash')
    ORDER BY object->>'resource_id',object->>'version_id')) AS value
  FROM keyed GROUP BY key
 ) SELECT coalesce(jsonb_agg(value),'[]'::jsonb) INTO expected FROM counts;
 IF jsonb_array_length(grouped->'groups')<>jsonb_array_length(expected)
 OR EXISTS(SELECT value FROM jsonb_array_elements(grouped->'groups')
   EXCEPT SELECT value FROM jsonb_array_elements(expected))
 OR EXISTS(SELECT value FROM jsonb_array_elements(expected)
   EXCEPT SELECT value FROM jsonb_array_elements(grouped->'groups'))
 THEN RAISE EXCEPTION 'Observation groups must partition the exact retained objects'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER grouped_observation_result BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_grouped_observation_result();
INSERT INTO schema_migrations VALUES(50);
COMMIT;
