BEGIN;
CREATE OR REPLACE FUNCTION g8_fields_readable(schema_attributes jsonb, properties jsonb, permissions jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE field record; needed jsonb;
BEGIN
 -- Most source schemas have no field-specific restrictions. Check that in C-backed
 -- JSONPath before entering the per-field PL/pgSQL loop. Restricted schemas retain
 -- exactly the existing validation, including malformed permission-list rejection.
 IF jsonb_typeof(coalesce(schema_attributes->'fields','{}'::jsonb))='object'
  AND NOT jsonb_path_exists(coalesce(schema_attributes,'{}'::jsonb),'$.fields.* ? (@.type() != "object")')
  AND NOT jsonb_path_exists(coalesce(schema_attributes,'{}'::jsonb),'$.fields.*.read_permissions')
 THEN RETURN true; END IF;
 FOR field IN SELECT key,value FROM jsonb_each(coalesce(schema_attributes->'fields','{}'::jsonb)) LOOP
  IF properties ? field.key AND field.value ? 'read_permissions' THEN
   IF jsonb_typeof(field.value->'read_permissions') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   FOR needed IN SELECT value FROM jsonb_array_elements(field.value->'read_permissions') LOOP
    IF jsonb_typeof(needed)<>'string' OR NOT (permissions @> jsonb_build_array(needed)) THEN RETURN false; END IF;
   END LOOP;
  END IF;
 END LOOP;
 RETURN true;
END $$;

INSERT INTO schema_migrations VALUES(29);
COMMIT;
