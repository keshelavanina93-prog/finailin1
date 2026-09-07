BEGIN;
CREATE OR REPLACE FUNCTION guard_grouped_observation_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; retained fact_calculation_runs%ROWTYPE;
 grouped jsonb; expected jsonb; source_count integer; schema_type text;
 source_object jsonb; source_version resource_versions%ROWTYPE; source_identity text;
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
 IF schema_type IS NULL THEN
  RAISE EXCEPTION 'Observation grouping requires exact canonical source versions';
 END IF;
 -- The bounded JSON page drives exact PK lookups. A join against the page can
 -- instead materialize tenant-wide RLS evaluation before applying these pins.
 FOR source_object IN SELECT value FROM jsonb_array_elements(retained.payload->'objects') LOOP
  SELECT * INTO source_version FROM resource_versions
  WHERE tenant_id=NEW.tenant_id
   AND resource_id=(source_object->>'resource_id')::uuid
   AND version_id=(source_object->>'version_id')::uuid;
  SELECT identity_key INTO source_identity FROM canonical_identities
  WHERE tenant_id=NEW.tenant_id
   AND resource_id=(source_object->>'resource_id')::uuid;
  IF source_version.version_id IS NULL
   OR source_version.object_type IS DISTINCT FROM schema_type
   OR source_version.schema_version_id::text IS DISTINCT FROM grouped->'schema'->>'version_id'
   OR (to_jsonb(source_version)-'tenant_id' || jsonb_build_object('identity_key',source_identity)) IS DISTINCT FROM source_object
   OR source_version.system_from>(intent.request->>'known_at')::timestamptz
  THEN RAISE EXCEPTION 'Observation grouping requires exact canonical source versions'; END IF;
 END LOOP;
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
INSERT INTO schema_migrations VALUES(51);
COMMIT;
