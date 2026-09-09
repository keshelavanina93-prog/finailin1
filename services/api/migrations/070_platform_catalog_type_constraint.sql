BEGIN;

ALTER TABLE public.resource_versions DROP CONSTRAINT resource_versions_platform_type_check;
ALTER TABLE public.resource_versions ADD CONSTRAINT resource_versions_platform_type_check
 CHECK(access_entity<>'__PLATFORM__' OR object_type IN
 ('SchemaDefinition','SemanticContract','LinkType','ObjectInterface',
  'ObjectTypeGroup','ObjectTypeImplementation','ObjectSetDefinition',
  'ObjectBinding','DerivedProperty','FactContract',
  'FinanceCapabilityDefinition','FinanceClassificationPolicy',
  'FinanceProjectionDefinition','CertificationContract'));

INSERT INTO schema_migrations VALUES(70);
COMMIT;
