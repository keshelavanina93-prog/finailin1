BEGIN;
-- Review remains the publication authority; retained calculations supply exact values.
CREATE FUNCTION guard_calculated_binding_promotion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE proposal jsonb; mutation jsonb; metadata jsonb; definition jsonb; field jsonb;
 binding resource_versions%ROWTYPE; source_schema resource_versions%ROWTYPE;
 target_schema resource_versions%ROWTYPE; prior resource_versions%ROWTYPE;
 property resource_versions%ROWTYPE; receipt function_invocation_results%ROWTYPE;
 invocation function_invocations%ROWTYPE; output fact_calculation_runs%ROWTYPE;
 source_object jsonb; reference jsonb; property_pin jsonb; value_row jsonb;
 property_references jsonb; expected_properties jsonb := '[]'::jsonb; values_by_pin jsonb := '{}'::jsonb;
 expected_attributes jsonb := '{}'::jsonb; source_version text; matches integer;
BEGIN
 IF NEW.proposal_id IS NULL THEN RETURN NEW; END IF;
 SELECT payload->'request' INTO proposal FROM resource_proposals
  WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
 metadata := proposal->'calculated_bindings'->NEW.resource_id::text;
 IF metadata IS NULL THEN
  IF EXISTS(SELECT 1 FROM jsonb_each(coalesce(
      proposal->'source_versions'->NEW.resource_id::text,'{}'::jsonb)) p
    JOIN resource_versions v ON v.tenant_id=NEW.tenant_id AND v.resource_id=p.key::uuid
     AND v.version_id=(p.value#>>'{}')::uuid WHERE v.object_type='ObjectBinding'
     AND (v.attributes->'definition' ? 'display_property' OR EXISTS(
      SELECT 1 FROM jsonb_array_elements(v.attributes->'definition'->'fields') f
      WHERE f ? 'derived_property')))
  THEN RAISE EXCEPTION 'Calculated binding promotion requires retained calculation evidence'; END IF;
  RETURN NEW;
 END IF;
 SELECT value INTO mutation FROM jsonb_array_elements(proposal->'mutations')
  WHERE value->>'resource_id'=NEW.resource_id::text;
 SELECT * INTO binding FROM resource_versions WHERE tenant_id=NEW.tenant_id
  AND resource_id=(metadata->'binding'->>'resource_id')::uuid
  AND version_id=(metadata->'binding'->>'version_id')::uuid;
 IF binding.object_type IS DISTINCT FROM 'ObjectBinding' OR binding.authority_state<>'APPROVED'
  OR (proposal->'source_versions'->NEW.resource_id::text->>binding.resource_id::text)
     IS DISTINCT FROM binding.version_id::text
 THEN RAISE EXCEPTION 'Calculated binding exact definition is unavailable'; END IF;
 definition := binding.attributes->'definition';
 SELECT v.* INTO source_schema FROM resource_dependencies d JOIN resource_versions v
  ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
  AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
  AND d.version_id=binding.version_id AND d.relation='FIELD:source_schema_id';
 SELECT v.* INTO target_schema FROM resource_dependencies d JOIN resource_versions v
  ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id
  AND v.version_id=d.target_version_id WHERE d.tenant_id=NEW.tenant_id
  AND d.version_id=binding.version_id AND d.relation='FIELD:target_schema_id';
 SELECT * INTO receipt FROM function_invocation_results WHERE tenant_id=NEW.tenant_id
  AND request_id=(metadata->'input_result'->>'invocation_id')::uuid;
 SELECT * INTO invocation FROM function_invocations WHERE tenant_id=NEW.tenant_id
  AND request_id=receipt.request_id;
 SELECT * INTO output FROM fact_calculation_runs WHERE tenant_id=NEW.tenant_id
  AND run_id=receipt.run_id;
 IF receipt.status IS DISTINCT FROM 'SUCCEEDED' OR output.run_id IS NULL
  OR metadata->>'receipt_hash' IS DISTINCT FROM receipt.proof_hash
  OR metadata->>'run_id' IS DISTINCT FROM receipt.run_id
  OR receipt.exact_scope IS DISTINCT FROM current_setting('finai.exact_scope',true)::jsonb
  OR output.exact_scope IS DISTINCT FROM receipt.exact_scope
  OR receipt.exact_scope->>'legal_entity_id' IS DISTINCT FROM NEW.access_entity
  OR ((metadata->'query') - ARRAY['valid_at','known_at']) IS DISTINCT FROM
     ((output.payload->'query') - ARRAY['valid_at','known_at'])
  OR (metadata->'query'->>'valid_at')::timestamptz IS DISTINCT FROM
     (output.payload->'query'->>'valid_at')::timestamptz
  OR (metadata->'query'->>'known_at')::timestamptz IS DISTINCT FROM
     (output.payload->'query'->>'known_at')::timestamptz
 THEN RAISE EXCEPTION 'Calculated binding requires its exact scoped Function receipt and query'; END IF;
 SELECT count(*) INTO matches FROM jsonb_array_elements(output.payload->'objects') o
  WHERE o->>'resource_id'=metadata->'source'->>'resource_id'
   AND o->>'version_id'=metadata->'source'->>'version_id';
 SELECT o INTO source_object FROM jsonb_array_elements(output.payload->'objects') o
  WHERE o->>'resource_id'=metadata->'source'->>'resource_id'
   AND o->>'version_id'=metadata->'source'->>'version_id';
 source_version := metadata->'source'->>'version_id';
 IF matches<>1 OR source_object->>'evidence_class' IS DISTINCT FROM 'SOURCE_BOUND'
  OR source_schema.object_type IS DISTINCT FROM 'SchemaDefinition'
  OR source_object->>'schema_version_id' IS DISTINCT FROM source_schema.version_id::text
  OR target_schema.object_type IS DISTINCT FROM 'SchemaDefinition'
  OR NEW.schema_version_id IS DISTINCT FROM target_schema.version_id
  OR (proposal->'source_versions'->NEW.resource_id::text->>(metadata->'source'->>'resource_id'))
     IS DISTINCT FROM source_version
 THEN RAISE EXCEPTION 'Calculated binding requires its exact original source and schema'; END IF;
 IF definition->>'identity_mode'='CANONICAL_REFERENCE'
  AND source_object->'attributes'->>(definition->>'identity_field') IS DISTINCT FROM NEW.resource_id::text
 THEN RAISE EXCEPTION 'Calculated binding must preserve the original canonical target identity'; END IF;
 SELECT coalesce(jsonb_agg(DISTINCT ref),'[]'::jsonb) INTO property_references FROM (
  SELECT definition->'display_property' ref WHERE definition ? 'display_property'
  UNION ALL SELECT f->'derived_property' FROM jsonb_array_elements(definition->'fields') f
   WHERE f ? 'derived_property') selected;
 IF jsonb_array_length(property_references)=0 THEN RAISE EXCEPTION 'Calculated binding declares no calculated values'; END IF;
 FOR reference IN SELECT value FROM jsonb_array_elements(property_references) LOOP
  SELECT * INTO property FROM resource_versions WHERE tenant_id=NEW.tenant_id
   AND resource_id=(reference->>'resource_id')::uuid AND version_id=(reference->>'version_id')::uuid;
  property_pin := jsonb_build_object('resource_id',property.resource_id::text,
   'version_id',property.version_id::text,'content_hash',property.content_hash);
  IF property.object_type IS DISTINCT FROM 'DerivedProperty' OR property.authority_state<>'APPROVED'
   OR NOT (invocation.plan->'derived_properties' @> jsonb_build_array(property_pin))
  THEN RAISE EXCEPTION 'Calculated binding property is not an exact declared Function output'; END IF;
  SELECT count(*) INTO matches FROM jsonb_array_elements(output.payload->'derived_values') v
   WHERE v->>'object_version_id'=source_version AND v->>'object_id'=source_object->>'resource_id'
    AND v->>'definition_id'=property.resource_id::text AND v->>'definition_version_id'=property.version_id::text;
  SELECT v INTO value_row FROM jsonb_array_elements(output.payload->'derived_values') v
   WHERE v->>'object_version_id'=source_version AND v->>'object_id'=source_object->>'resource_id'
    AND v->>'definition_id'=property.resource_id::text AND v->>'definition_version_id'=property.version_id::text;
  IF matches<>1 OR value_row->>'status' IS DISTINCT FROM 'AVAILABLE'
   OR value_row->'value' IS NULL OR value_row->'value'='null'::jsonb
   OR value_row->>'kind' IS DISTINCT FROM property.attributes->'definition'->>'result_kind'
  THEN RAISE EXCEPTION 'Calculated binding value is missing, unavailable or mistyped'; END IF;
  expected_properties := expected_properties || jsonb_build_array(property_pin);
  values_by_pin := values_by_pin || jsonb_build_object(
   property.resource_id::text || ':' || property.version_id::text,value_row->'value');
 END LOOP;
 IF jsonb_typeof(metadata->'properties') IS DISTINCT FROM 'array'
  OR jsonb_array_length(metadata->'properties')<>jsonb_array_length(expected_properties)
  OR NOT ((metadata->'properties') @> expected_properties
          AND expected_properties @> (metadata->'properties'))
 THEN RAISE EXCEPTION 'Calculated binding retained property provenance differs'; END IF;
 IF definition ? 'display_property' THEN
  reference := definition->'display_property';
  value_row := values_by_pin->((reference->>'resource_id') || ':' || (reference->>'version_id'));
  IF jsonb_typeof(value_row) IS DISTINCT FROM 'string' OR NEW.display_name IS DISTINCT FROM value_row#>>'{}'
  THEN RAISE EXCEPTION 'Calculated binding display differs from the retained value'; END IF;
 ELSIF NEW.display_name IS DISTINCT FROM source_object->'attributes'->>(definition->>'display_field') THEN
  RAISE EXCEPTION 'Calculated binding display differs from the original stored value';
 END IF;
 IF jsonb_array_length(definition->'fields')=0 THEN
  SELECT * INTO prior FROM resource_versions WHERE tenant_id=NEW.tenant_id
   AND resource_id=NEW.resource_id AND version_id=(mutation->>'expected_version_id')::uuid;
  IF definition->>'identity_mode' IS DISTINCT FROM 'CANONICAL_REFERENCE' OR prior.version_id IS NULL
   OR source_object->'attributes'->>(definition->>'identity_field') IS DISTINCT FROM NEW.resource_id::text
  THEN RAISE EXCEPTION 'Display-only binding must preserve an existing canonical target'; END IF;
  expected_attributes := prior.attributes;
 ELSE
  FOR field IN SELECT value FROM jsonb_array_elements(definition->'fields') LOOP
   IF field ? 'derived_property' THEN
    reference := field->'derived_property';
    expected_attributes := expected_attributes || jsonb_build_object(field->>'target_field',
     values_by_pin->((reference->>'resource_id') || ':' || (reference->>'version_id')));
   ELSIF source_object->'attributes' ? (field->>'source_field') THEN
    expected_attributes := expected_attributes || jsonb_build_object(field->>'target_field',
     source_object->'attributes'->(field->>'source_field'));
   END IF;
  END LOOP;
 END IF;
 IF NEW.attributes IS DISTINCT FROM expected_attributes
 THEN RAISE EXCEPTION 'Calculated binding attributes differ from the retained mapping'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calculated_binding_promotion_integrity BEFORE INSERT ON resource_versions
 FOR EACH ROW EXECUTE FUNCTION guard_calculated_binding_promotion();
INSERT INTO schema_migrations VALUES(56);
COMMIT;
