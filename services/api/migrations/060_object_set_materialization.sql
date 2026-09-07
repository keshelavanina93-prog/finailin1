BEGIN;

-- Public Object Set pages remain bounded at 200. This separately reviewed
-- Function mode retains a complete partition of original canonical objects.
CREATE FUNCTION g8_validate_object_materialization(output jsonb, plan jsonb, tenant uuid)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE material jsonb; config jsonb; page jsonb; source_object jsonb;
 original resource_versions%ROWTYPE; identity_key text; first_metadata jsonb;
 common_metadata jsonb; projected jsonb := '{}'::jsonb; metadata_key text;
 pins jsonb := '[]'::jsonb; expected_pins jsonb; expected_counts jsonb;
 object_count integer; page_count integer; page_index integer := 0;
 seen_count integer := 0; page_size integer; count_in_page integer;
BEGIN
 material := output->'materialization'; config := plan->'materialization';
 IF config IS NULL THEN
  IF material IS NOT NULL THEN RAISE EXCEPTION 'Undeclared Object Set materialization'; END IF;
  RETURN;
 END IF;
 IF jsonb_typeof(output->'objects') IS DISTINCT FROM 'array'
  OR jsonb_typeof(material->'pages') IS DISTINCT FROM 'array'
  OR material->>'contract' IS DISTINCT FROM 'bounded-object-set-materialization/1'
  OR material->>'coverage' IS DISTINCT FROM 'COMPLETE_BOUNDED_MATERIALIZATION'
  OR output->>'coverage' IS DISTINCT FROM 'COMPLETE_BOUNDED_MATERIALIZATION'
  OR material->>'hash_algorithm' IS DISTINCT FROM 'POSTGRES_JSONB_TEXT_UTF8_SHA256'
  OR material->'object_set' IS DISTINCT FROM plan->'object_set'
  OR material->'max_objects' IS DISTINCT FROM config->'max_objects'
  OR material->'max_pages' IS DISTINCT FROM config->'max_pages'
  OR output->'query'->'offset' IS DISTINCT FROM '0'::jsonb
  OR output->'query'->'limit' IS DISTINCT FROM plan->'request'->'limit'
  OR (output->'query'->>'valid_at')::timestamptz IS DISTINCT FROM
     (plan->'request'->>'valid_at')::timestamptz
  OR (output->'query'->>'known_at')::timestamptz IS DISTINCT FROM
     (plan->'request'->>'known_at')::timestamptz
  OR output->'next_offset' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE EXCEPTION 'Reviewed complete materialization contract required'; END IF;
 object_count := jsonb_array_length(output->'objects');
 page_count := jsonb_array_length(material->'pages');
 page_size := (plan->'request'->>'limit')::integer;
 IF page_count NOT BETWEEN 1 AND (config->>'max_pages')::integer
  OR page_size NOT BETWEEN 1 AND 200
  OR object_count>least((config->>'max_objects')::integer,
    page_size*(config->>'max_pages')::integer)
  OR material->'object_count' IS DISTINCT FROM to_jsonb(object_count)
  OR material->'page_count' IS DISTINCT FROM to_jsonb(page_count)
  OR output->'total' IS DISTINCT FROM to_jsonb(object_count)
  OR object_count<>(SELECT count(DISTINCT value->>'resource_id')
    FROM jsonb_array_elements(output->'objects'))
  OR material IS DISTINCT FROM jsonb_build_object(
    'contract','bounded-object-set-materialization/1',
    'coverage','COMPLETE_BOUNDED_MATERIALIZATION',
    'hash_algorithm','POSTGRES_JSONB_TEXT_UTF8_SHA256',
    'object_set',plan->'object_set','max_objects',config->'max_objects',
    'max_pages',config->'max_pages','object_count',object_count,
    'page_count',page_count,'pages',material->'pages')
 THEN RAISE EXCEPTION 'Materialization exceeds its reviewed partition bounds'; END IF;
 first_metadata := material->'pages'->0->'metadata';
 common_metadata := first_metadata-'interface_values'-'type_group_values';
 FOR metadata_key IN SELECT jsonb_object_keys(first_metadata) LOOP
  IF metadata_key NOT IN ('counts_by_type','filter_schema_versions','traversal_schema_versions',
    'interface_bindings','type_group_bindings','interface_values','type_group_values') THEN
   RAISE EXCEPTION 'Unsupported materialization metadata';
  END IF;
  IF metadata_key IN ('interface_values','type_group_values') THEN
   projected := projected || jsonb_build_object(metadata_key,'[]'::jsonb);
  ELSIF output->metadata_key IS DISTINCT FROM first_metadata->metadata_key THEN
   RAISE EXCEPTION 'Materialization metadata must retain its exact query context';
  END IF;
 END LOOP;
 FOR page IN SELECT value FROM jsonb_array_elements(material->'pages') LOOP
  page_index := page_index+1;
  IF jsonb_typeof(page->'object_pins') IS DISTINCT FROM 'array'
   OR jsonb_typeof(page->'metadata') IS DISTINCT FROM 'object'
   OR page IS DISTINCT FROM jsonb_build_object('query',page->'query','total',page->'total',
     'next_offset',page->'next_offset','object_pins',page->'object_pins',
     'metadata',page->'metadata','page_hash',page->'page_hash')
   OR page->>'page_hash' IS DISTINCT FROM
     encode(sha256(convert_to((page-'page_hash')::text,'UTF8')),'hex')
   OR page->'query' IS DISTINCT FROM
     ((output->'query')||jsonb_build_object('offset',seen_count))
   OR page->'total' IS DISTINCT FROM to_jsonb(object_count)
   OR ((page->'metadata')-'interface_values'-'type_group_values') IS DISTINCT FROM common_metadata
   OR (page->'metadata' ? 'interface_values') IS DISTINCT FROM (projected ? 'interface_values')
   OR (page->'metadata' ? 'type_group_values') IS DISTINCT FROM (projected ? 'type_group_values')
  THEN RAISE EXCEPTION 'Materialization page hash or retained context differs'; END IF;
  count_in_page := jsonb_array_length(page->'object_pins');
  seen_count := seen_count+count_in_page;
  IF count_in_page>page_size OR (page_count>1 AND count_in_page=0)
   OR (page_index<page_count AND count_in_page<>page_size)
   OR page->'next_offset' IS DISTINCT FROM
     (CASE WHEN page_index<page_count THEN to_jsonb(seen_count) ELSE 'null'::jsonb END)
  THEN RAISE EXCEPTION 'Materialization pages must be contiguous and exhausted'; END IF;
  pins := pins || (page->'object_pins');
  FOR metadata_key IN SELECT jsonb_object_keys(projected) LOOP
   IF jsonb_typeof(page->'metadata'->metadata_key) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Materialization projection must remain a retained array';
   END IF;
   projected := projected || jsonb_build_object(metadata_key,
     (projected->metadata_key)||(page->'metadata'->metadata_key));
  END LOOP;
 END LOOP;
 FOR metadata_key IN SELECT jsonb_object_keys(projected) LOOP
  IF output->metadata_key IS DISTINCT FROM projected->metadata_key THEN
   RAISE EXCEPTION 'Materialization projection differs from its retained pages';
  END IF;
 END LOOP;
 SELECT coalesce(jsonb_agg(jsonb_build_object('resource_id',value->'resource_id',
  'version_id',value->'version_id','content_hash',value->'content_hash') ORDER BY ordinal),'[]'::jsonb)
 INTO expected_pins FROM jsonb_array_elements(output->'objects') WITH ORDINALITY AS rows(value,ordinal);
 SELECT coalesce(jsonb_object_agg(kind,n),'{}'::jsonb) INTO expected_counts FROM (
  SELECT value->>'object_type' AS kind,count(*) AS n FROM jsonb_array_elements(output->'objects')
  GROUP BY value->>'object_type') counts;
 IF seen_count<>object_count OR pins IS DISTINCT FROM expected_pins
  OR output->'counts_by_type' IS DISTINCT FROM expected_counts
  OR first_metadata->'counts_by_type' IS DISTINCT FROM expected_counts THEN
  RAISE EXCEPTION 'Materialization partition must cover exactly the retained canonical objects';
 END IF;
 FOR source_object IN SELECT value FROM jsonb_array_elements(output->'objects') LOOP
  SELECT v.* INTO original FROM resource_versions v WHERE v.tenant_id=tenant
   AND v.resource_id=(source_object->>'resource_id')::uuid
   AND v.version_id=(source_object->>'version_id')::uuid;
  SELECT i.identity_key INTO identity_key FROM canonical_identities i WHERE i.tenant_id=tenant
   AND i.resource_id=(source_object->>'resource_id')::uuid;
  IF original.version_id IS NULL OR original.system_from>(plan->'request'->>'known_at')::timestamptz
   OR (to_jsonb(original)-'tenant_id'||jsonb_build_object('identity_key',identity_key))
      IS DISTINCT FROM source_object THEN
   RAISE EXCEPTION 'Materialization requires exact readable canonical versions';
  END IF;
 END LOOP;
END $$;

CREATE FUNCTION guard_object_materialization_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE definition resource_versions%ROWTYPE; config jsonb;
BEGIN
 SELECT * INTO definition FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(NEW.request->'function'->>'resource_id')::uuid
  AND version_id=(NEW.request->'function'->>'version_id')::uuid;
 config := nullif(definition.attributes->'definition'->'materialization','null'::jsonb);
 IF config IS NULL THEN
  IF NEW.plan ? 'materialization' THEN RAISE EXCEPTION 'Undeclared materialization plan'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.plan->'materialization' IS DISTINCT FROM config
  OR config IS DISTINCT FROM jsonb_build_object('max_objects',config->'max_objects','max_pages',config->'max_pages')
  OR jsonb_typeof(config->'max_objects') IS DISTINCT FROM 'number'
  OR jsonb_typeof(config->'max_pages') IS DISTINCT FROM 'number'
  OR (config->>'max_objects' ~ '^[0-9]+$') IS NOT TRUE
  OR (config->>'max_pages' ~ '^[0-9]+$') IS NOT TRUE
  OR (config->>'max_objects')::integer NOT BETWEEN 1 AND 1000
  OR (config->>'max_pages')::integer NOT BETWEEN 1 AND 10
  OR NEW.request->'offset' IS DISTINCT FROM '0'::jsonb
  OR NEW.plan->'implementation'->>'implementation_id' IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR coalesce(NEW.plan->'derived_properties','[]'::jsonb)<>'[]'::jsonb
  OR coalesce(NEW.plan->'retained_properties','[]'::jsonb)<>'[]'::jsonb
  OR NEW.plan ? 'group_count'
 THEN RAISE EXCEPTION 'Materialization requires reviewed original-object bounds'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER object_materialization_intent BEFORE INSERT ON function_invocations
 FOR EACH ROW EXECUTE FUNCTION guard_object_materialization_intent();

CREATE FUNCTION guard_object_materialization_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent function_invocations%ROWTYPE; retained fact_calculation_runs%ROWTYPE;
 source_result fact_calculation_runs%ROWTYPE;
BEGIN
 IF NEW.status<>'SUCCEEDED' THEN RETURN NEW; END IF;
 SELECT * INTO intent FROM function_invocations WHERE tenant_id=NEW.tenant_id AND request_id=NEW.request_id;
 SELECT * INTO retained FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id;
 PERFORM g8_validate_object_materialization(retained.payload,intent.plan,NEW.tenant_id);
 IF intent.plan ? 'materialization' AND intent.request ? 'input_result' THEN
  SELECT r.* INTO source_result FROM function_invocation_results f JOIN fact_calculation_runs r
   ON r.tenant_id=f.tenant_id AND r.run_id=f.run_id WHERE f.tenant_id=NEW.tenant_id
   AND f.request_id=(intent.request->'input_result'->>'invocation_id')::uuid;
  IF retained.payload->'materialization' IS DISTINCT FROM source_result.payload->'materialization' THEN
   RAISE EXCEPTION 'Downstream materialization must preserve exact retained pages';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER object_materialization_result BEFORE INSERT ON function_invocation_results
 FOR EACH ROW EXECUTE FUNCTION guard_object_materialization_result();

-- Existing guards retain their legacy branches.
CREATE OR REPLACE FUNCTION guard_function_input_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reference jsonb; source function_invocation_results%ROWTYPE;
 source_intent function_invocations%ROWTYPE; output fact_calculation_runs%ROWTYPE;
BEGIN
 IF NOT (NEW.request ? 'input_result') THEN RETURN NEW; END IF;
 reference := NEW.request->'input_result';
 IF reference IS DISTINCT FROM jsonb_build_object('invocation_id',reference->>'invocation_id')
  OR (reference->>'invocation_id')::uuid=NEW.request_id
 THEN RAISE EXCEPTION 'Invalid retained Function input identity'; END IF;
 SELECT * INTO source FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(reference->>'invocation_id')::uuid;
 SELECT * INTO source_intent FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=source.request_id;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=source.run_id;
 IF source.request_id IS NULL OR source.status IS DISTINCT FROM 'SUCCEEDED'
  OR source.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR source_intent.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR output.run_id IS NULL OR output.exact_scope IS DISTINCT FROM NEW.exact_scope
  OR NEW.plan->'implementation'->>'implementation_id' IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR source_intent.plan->'implementation'->>'implementation_id' IS DISTINCT FROM 'ontology.object-set-derived/v1'
  OR NEW.plan->'object_set' IS DISTINCT FROM source_intent.plan->'object_set'
  OR NEW.request->'valid_at' IS DISTINCT FROM source_intent.request->'valid_at'
  OR NEW.request->'known_at' IS DISTINCT FROM source_intent.request->'known_at'
  OR NEW.request->'offset' IS DISTINCT FROM '0'::jsonb
  OR jsonb_typeof(output.payload->'objects') IS DISTINCT FROM 'array'
  OR NEW.plan->'materialization' IS DISTINCT FROM source_intent.plan->'materialization'
  OR (NEW.plan ? 'materialization' AND NEW.request->'limit' IS DISTINCT FROM source_intent.request->'limit')
  OR (NOT(NEW.plan ? 'materialization') AND
    jsonb_array_length(output.payload->'objects') > (NEW.request->>'limit')::int)
 THEN RAISE EXCEPTION 'Function input requires compatible succeeded exact-scope evidence'; END IF;
 PERFORM g8_validate_object_materialization(output.payload,source_intent.plan,NEW.tenant_id);
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION guard_transformation_budget_intent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE compiled jsonb; budget jsonb; canonical_budget jsonb; estimates jsonb;
 rows_bound bigint; evaluations_bound bigint;
BEGIN
 IF NEW.definition_version<>'transformation-functions/1' THEN RETURN NEW; END IF;
 compiled := NEW.payload->'compiled_plan'; budget := compiled->'resource_budget';
 SELECT attributes->'resource_budget' INTO canonical_budget FROM resource_versions
 WHERE tenant_id=NEW.tenant_id
 AND version_id=(compiled->'request'->'transformation'->>'version_id')::uuid
 AND resource_id=(compiled->'request'->'transformation'->>'resource_id')::uuid;
 IF budget IS NULL OR budget IS DISTINCT FROM canonical_budget
 OR compiled->>'result_bytes_accounting' IS DISTINCT FROM 'POSTGRES_JSONB_TEXT_UTF8_V1'
 OR jsonb_typeof(budget->'max_returned_rows') IS DISTINCT FROM 'number'
 OR jsonb_typeof(budget->'max_derived_evaluations') IS DISTINCT FROM 'number'
 OR jsonb_typeof(budget->'max_published_result_bytes') IS DISTINCT FROM 'number'
 THEN RAISE EXCEPTION 'Reviewed transformation resource budget required'; END IF;
 IF (budget->>'max_returned_rows')::bigint NOT BETWEEN 1 AND 6400
 OR (budget->>'max_derived_evaluations')::bigint NOT BETWEEN 0 AND 51200
 OR (budget->>'max_published_result_bytes')::bigint NOT BETWEEN 1 AND 16000000
 THEN RAISE EXCEPTION 'Transformation resource budget exceeds installed limits'; END IF;
 SELECT sum((CASE WHEN v.attributes->'definition' ? 'materialization' THEN
 least((v.attributes->'definition'->'materialization'->>'max_objects')::bigint,
 (n.value->'invocation'->>'limit')::bigint *
 (v.attributes->'definition'->'materialization'->>'max_pages')::bigint)
 ELSE (n.value->'invocation'->>'limit')::bigint END)),
 sum((CASE WHEN v.attributes->'definition' ? 'materialization' THEN
 least((v.attributes->'definition'->'materialization'->>'max_objects')::bigint,
 (n.value->'invocation'->>'limit')::bigint *
 (v.attributes->'definition'->'materialization'->>'max_pages')::bigint)
 ELSE (n.value->'invocation'->>'limit')::bigint END) *
     jsonb_array_length(coalesce(v.attributes->'definition'->'derived_property_ids','[]'::jsonb)))
 INTO rows_bound,evaluations_bound
 FROM jsonb_array_elements(compiled->'nodes') n
 JOIN resource_versions v ON v.tenant_id=NEW.tenant_id
 AND v.resource_id=(n.value->'function'->>'resource_id')::uuid
 AND v.version_id=(n.value->'function'->>'version_id')::uuid;
 estimates := jsonb_build_object('returned_rows',rows_bound,'derived_evaluations',evaluations_bound);
 IF rows_bound IS NULL OR evaluations_bound IS NULL
 OR estimates IS DISTINCT FROM compiled->'estimated_work'
 OR rows_bound>(budget->>'max_returned_rows')::bigint
 OR evaluations_bound>(budget->>'max_derived_evaluations')::bigint
 THEN RAISE EXCEPTION 'Transformation estimated work exceeds reviewed budget'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION guard_temporal_observation_result() RETURNS trigger LANGUAGE plpgsql AS $$
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
  OR source_count>(CASE WHEN intent.plan ? 'materialization' THEN
    least((intent.plan->'materialization'->>'max_objects')::integer,
     (intent.request->>'limit')::integer * (intent.plan->'materialization'->>'max_pages')::integer)
    ELSE least((intent.request->>'limit')::integer,200) END)
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
  'authority','OBSERVATION_EXTENT_ONLY','coverage',
  CASE WHEN intent.plan ? 'materialization' THEN 'COMPLETE_BOUNDED_MATERIALIZATION'
   ELSE 'COMPLETE_BOUNDED_OBJECT_SET' END,
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
INSERT INTO schema_migrations VALUES(60);
COMMIT;
