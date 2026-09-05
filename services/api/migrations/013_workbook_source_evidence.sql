BEGIN;
ALTER TABLE public.hydration_runs DROP CONSTRAINT scoped_object_evidence;
ALTER TABLE public.hydration_runs ADD CONSTRAINT scoped_object_evidence CHECK (
    source_storage IS NULL OR (
        jsonb_typeof(source_storage)='object' AND
        source_storage ?& ARRAY['backend','bucket','object_key','sha256','byte_length'] AND
        source_storage->>'backend'='S3' AND length(source_storage->>'bucket')>0 AND
        source_storage->>'sha256'=source_sha256 AND
        (source_storage->>'byte_length')::integer BETWEEN 1 AND 16000000 AND
        source_storage->>'object_key' ~ ('^tenant/' || tenant_id::text ||
            '/scope/[a-f0-9]{64}/sha256/' || source_sha256 || '$') AND
        receipt->'source_storage'=source_storage AND
        NOT (request ?| ARRAY['csv_text','xls_base64','xlsx_base64'])
    ) IS TRUE
);
INSERT INTO schema_migrations VALUES (13);
COMMIT;
