BEGIN;

-- Exact lexical boundary for dates and aware datetimes. No calendar-date to
-- instant conversion, local timezone inference, or fractional-second truncation.
CREATE FUNCTION g8_temporal_observation_value(raw text, kind text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE instant_value timestamptz; utc_value timestamp;
BEGIN
 IF kind='date' THEN
  IF raw !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
   OR NOT pg_input_is_valid(raw,'date') THEN
   RAISE EXCEPTION 'Canonical observation date required';
  END IF;
  RETURN to_char(raw::date,'YYYY-MM-DD');
 ELSIF kind='datetime' THEN
  IF raw !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,6})?(Z|[+-](0[0-9]|1[0-5]):[0-5][0-9])$'
   OR NOT pg_input_is_valid(raw,'timestamptz') THEN
   RAISE EXCEPTION 'Exact aware observation datetime required';
  END IF;
  instant_value := raw::timestamptz;
  utc_value := instant_value AT TIME ZONE 'UTC';
  IF utc_value < timestamp '0001-01-01' OR utc_value >= timestamp '10000-01-01' THEN
   RAISE EXCEPTION 'Observation datetime is outside the supported calendar';
  END IF;
  RETURN to_char(utc_value,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
 END IF;
 RAISE EXCEPTION 'Temporal observation kind required';
END $$;

CREATE FUNCTION guard_temporal_observation_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; temporal_schema resource_versions%ROWTYPE;
 config jsonb; field_name text; field_kind text;
BEGIN
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(NEW.request->'function'->>'resource_id')::uuid
  AND version_id=(NEW.request->'function'->>'version_id')::uuid;
 config := definition.attributes->'definition'->'temporal_extent';
 IF config IS NULL OR config='null'::jsonb THEN
  IF NEW.plan ? 'temporal_extent' THEN RAISE EXCEPTION 'Undeclared temporal observation extent'; END IF;
  RETURN NEW;
 END IF;
 field_name := config->>'field';
 IF definition.attributes->'definition'->>'implementation_id'
    IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR jsonb_typeof(config) IS DISTINCT FROM 'object'
  OR jsonb_typeof(config->'field') IS DISTINCT FROM 'string'
  OR length(field_name) NOT BETWEEN 1 AND 128
  OR NEW.request->'offset' IS DISTINCT FROM '0'::jsonb THEN
  RAISE EXCEPTION 'Typed complete temporal observation extent required';
 END IF;
 SELECT v.* INTO temporal_schema FROM resource_dependencies d JOIN resource_versions v
  ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
  AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
  AND d.version_id=definition.version_id AND d.relation='FUNCTION_TEMPORAL_SCHEMA'
  AND v.resource_id=(config->>'schema_id')::uuid;
 field_kind := temporal_schema.attributes->'fields'->field_name->>'kind';
 IF temporal_schema.version_id IS NULL OR temporal_schema.object_type<>'SchemaDefinition'
  OR temporal_schema.authority_state<>'APPROVED'
  OR (field_kind IN ('date','datetime')) IS NOT TRUE
  OR NEW.plan->'temporal_extent' IS DISTINCT FROM jsonb_build_object(
   'field',field_name,'kind',field_kind,'schema',jsonb_build_object(
    'resource_id',temporal_schema.resource_id::text,'version_id',temporal_schema.version_id::text,
    'content_hash',temporal_schema.content_hash)) THEN
  RAISE EXCEPTION 'Exact temporal observation schema required';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER temporal_observation_intent BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_temporal_observation_intent();

CREATE FUNCTION guard_temporal_observation_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; retained fact_calculation_runs%ROWTYPE;
 temporal_schema resource_versions%ROWTYPE; source_version resource_versions%ROWTYPE;
 extent jsonb; expected jsonb; source_object jsonb; normalized jsonb := '[]'::jsonb;
 field_name text; field_kind text; schema_type text; source_identity text; raw text; value text;
 source_count integer; missing_count integer := 0; null_count integer := 0; value_count integer := 0;
 earliest text; latest text; first_witnesses jsonb; last_witnesses jsonb;
BEGIN
 IF NEW.status<>'SUCCEEDED' THEN RETURN NEW; END IF;
 SELECT * INTO intent FROM function_invocations
  WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 SELECT * INTO retained FROM fact_calculation_runs
  WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 extent := retained.payload->'temporal_extent';
 IF NOT(intent.plan ? 'temporal_extent') THEN
  IF extent IS NOT NULL THEN RAISE EXCEPTION 'Undeclared temporal observation result'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(retained.payload->'objects') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Retained temporal observation objects required';
 END IF;
 source_count := jsonb_array_length(retained.payload->'objects');
 IF retained.payload->'total' IS DISTINCT FROM to_jsonb(source_count)
  OR retained.payload->'query'->'offset' IS DISTINCT FROM '0'::jsonb
  OR retained.payload->'next_offset' IS DISTINCT FROM 'null'::jsonb
  OR source_count>least((intent.request->>'limit')::integer,200)
  OR source_count<>(SELECT count(DISTINCT element->>'resource_id')
      FROM jsonb_array_elements(retained.payload->'objects') element) THEN
  RAISE EXCEPTION 'Temporal extent requires the complete bounded Object Set';
 END IF;
 SELECT * INTO temporal_schema FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(intent.plan->'temporal_extent'->'schema'->>'resource_id')::uuid
  AND version_id=(intent.plan->'temporal_extent'->'schema'->>'version_id')::uuid;
 SELECT identity_key INTO schema_type FROM canonical_identities WHERE tenant_id=NEW.tenant_id
  AND resource_id=temporal_schema.resource_id AND object_type='SchemaDefinition';
 field_name := intent.plan->'temporal_extent'->>'field';
 field_kind := intent.plan->'temporal_extent'->>'kind';
 IF schema_type IS NULL OR temporal_schema.authority_state<>'APPROVED'
  OR temporal_schema.attributes->'fields'->field_name->>'kind' IS DISTINCT FROM field_kind THEN
  RAISE EXCEPTION 'Temporal observation schema is unavailable';
 END IF;
 -- Bounded exact lookups retain the original RLS-protected canonical row.
 FOR source_object IN SELECT element FROM jsonb_array_elements(retained.payload->'objects') element LOOP
  SELECT * INTO source_version FROM resource_versions WHERE tenant_id=NEW.tenant_id
   AND resource_id=(source_object->>'resource_id')::uuid
   AND version_id=(source_object->>'version_id')::uuid;
  SELECT identity_key INTO source_identity FROM canonical_identities WHERE tenant_id=NEW.tenant_id
   AND resource_id=(source_object->>'resource_id')::uuid;
  IF source_version.version_id IS NULL OR source_version.object_type IS DISTINCT FROM schema_type
   OR source_version.schema_version_id IS DISTINCT FROM temporal_schema.version_id
   OR (to_jsonb(source_version)-'tenant_id' || jsonb_build_object('identity_key',source_identity))
      IS DISTINCT FROM source_object
   OR source_version.system_from>(intent.request->>'known_at')::timestamptz THEN
   RAISE EXCEPTION 'Temporal extent requires exact canonical source versions';
  END IF;
  IF NOT(source_version.attributes ? field_name) OR source_version.attributes->field_name='null'::jsonb THEN
   IF temporal_schema.attributes->'fields'->field_name->'required'='true'::jsonb THEN
    RAISE EXCEPTION 'Required temporal observation value is absent';
   END IF;
   IF NOT(source_version.attributes ? field_name) THEN missing_count := missing_count+1;
   ELSE null_count := null_count+1; END IF;
  ELSE
   IF jsonb_typeof(source_version.attributes->field_name) IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'Temporal observation must use a canonical string';
   END IF;
   raw := source_version.attributes->>field_name;
   value := g8_temporal_observation_value(raw,field_kind);
   value_count := value_count+1;
   normalized := normalized || jsonb_build_array(jsonb_build_object('value',value,'witness',
    jsonb_build_object('resource_id',source_version.resource_id::text,'version_id',source_version.version_id::text,
     'content_hash',source_version.content_hash,'original_value',raw)));
  END IF;
 END LOOP;
 SELECT min(element->>'value'),max(element->>'value') INTO earliest,latest
  FROM jsonb_array_elements(normalized) element;
 SELECT coalesce(jsonb_agg(element->'witness' ORDER BY element->'witness'->>'resource_id',
   element->'witness'->>'version_id'),'[]'::jsonb) INTO first_witnesses
  FROM jsonb_array_elements(normalized) element WHERE element->>'value'=earliest;
 SELECT coalesce(jsonb_agg(element->'witness' ORDER BY element->'witness'->>'resource_id',
   element->'witness'->>'version_id'),'[]'::jsonb) INTO last_witnesses
  FROM jsonb_array_elements(normalized) element WHERE element->>'value'=latest;
 expected := jsonb_build_object('contract','temporal-observation-extent/1',
  'authority','OBSERVATION_EXTENT_ONLY','coverage','COMPLETE_BOUNDED_OBJECT_SET',
  'schema',intent.plan->'temporal_extent'->'schema','field',field_name,'kind',field_kind,
  'state',CASE WHEN value_count=0 THEN 'NO_VALUES' ELSE 'AVAILABLE' END,
  'object_count',source_count,'value_count',value_count,'missing_count',missing_count,'null_count',null_count,
  'earliest',CASE WHEN earliest IS NULL THEN 'null'::jsonb ELSE
   jsonb_build_object('normalized_value',earliest,'witnesses',first_witnesses) END,
  'latest',CASE WHEN latest IS NULL THEN 'null'::jsonb ELSE
   jsonb_build_object('normalized_value',latest,'witnesses',last_witnesses) END);
 IF extent IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'Temporal extent must match exact source counts, boundaries and witnesses';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER temporal_observation_result BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_temporal_observation_result();
INSERT INTO schema_migrations VALUES(59);
COMMIT;
