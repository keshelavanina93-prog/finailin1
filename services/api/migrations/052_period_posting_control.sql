BEGIN;
-- One control identity for a business tuple, including across policy boundaries.
CREATE UNIQUE INDEX period_control_identity ON canonical_identities(tenant_id,identity_key)
 WHERE object_type='PeriodControl';

CREATE FUNCTION g8_period_pin(pins jsonb, relation_name text, identity uuid)
RETURNS uuid LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE result uuid; matches integer;
BEGIN
 IF jsonb_typeof(pins) IS DISTINCT FROM 'array' OR identity IS NULL THEN RETURN NULL; END IF;
 SELECT count(*) INTO matches FROM jsonb_array_elements(pins) p
 WHERE p->>'relation'=relation_name;
 IF matches<>1 THEN RETURN NULL; END IF;
 SELECT (p->>'version_id')::uuid INTO result FROM jsonb_array_elements(pins) p
 WHERE p->>'relation'=relation_name AND p->>'resource_id'=identity::text;
 RETURN result;
END $$;

CREATE FUNCTION g8_period_version_available(tenant uuid, version uuid)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE event jsonb;
BEGIN
 SELECT payload INTO event FROM public.resource_lifecycle_events
 WHERE tenant_id=tenant AND version_id=version ORDER BY recorded_at DESC,event_id DESC LIMIT 1;
 RETURN event IS NULL OR (
  coalesce(event->>'target_state','') NOT IN ('REVOKED','SUPERSEDED')
  AND event->>'availability_state'='AVAILABLE'
 );
END $$;

CREATE FUNCTION g8_period_context_matches(tenant uuid, attrs jsonb, pins jsonb, at_time timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE field_name text; wanted_type text; target public.resource_versions%ROWTYPE;
 version uuid; refs jsonb := '{}'::jsonb; nodes jsonb := '{}'::jsonb; pair text[];
BEGIN
 FOREACH field_name IN ARRAY ARRAY['legal_entity_id','ledger_id','book_id','period_id','chart_id','currency_id','calendar_id'] LOOP
  wanted_type := CASE field_name WHEN 'legal_entity_id' THEN 'LegalEntity' WHEN 'ledger_id' THEN 'Ledger'
   WHEN 'book_id' THEN 'AccountingBook' WHEN 'period_id' THEN 'FiscalPeriod'
   WHEN 'chart_id' THEN 'LocalChartOfAccounts' WHEN 'currency_id' THEN 'Currency' ELSE 'FiscalCalendar' END;
  version := public.g8_period_pin(pins,'FIELD:'||field_name,(attrs->>field_name)::uuid);
  SELECT v.* INTO target FROM public.resource_versions v JOIN public.resource_heads h
   USING(tenant_id,resource_id,version_id) WHERE v.tenant_id=tenant AND v.version_id=version
   AND v.resource_id=(attrs->>field_name)::uuid;
  IF target.version_id IS NULL OR target.object_type IS DISTINCT FROM wanted_type
   OR target.authority_state IS DISTINCT FROM 'APPROVED' OR target.evidence_class='REFERENCE_TEMPLATE'
   OR target.system_from>at_time OR target.valid_from>at_time OR (target.valid_to IS NOT NULL AND target.valid_to<=at_time)
   OR public.g8_effective_version_id(tenant,target.resource_id,at_time) IS DISTINCT FROM target.version_id
   OR public.g8_period_version_available(tenant,target.version_id) IS NOT TRUE
  THEN RETURN false; END IF;
  refs := refs || jsonb_build_object(field_name,version::text);
  nodes := nodes || jsonb_build_object(field_name,target.attributes);
 END LOOP;
 -- The seven resources must be one exact, coherent accounting context.
 FOREACH pair SLICE 1 IN ARRAY ARRAY[
  ARRAY['ledger_id','legal_entity_id'], ARRAY['ledger_id','chart_id'],
  ARRAY['ledger_id','currency_id'], ARRAY['ledger_id','calendar_id'],
  ARRAY['book_id','ledger_id'], ARRAY['period_id','calendar_id'], ARRAY['chart_id','legal_entity_id']
 ] LOOP
  IF nodes->pair[1]->>pair[2] IS DISTINCT FROM attrs->>pair[2] OR NOT EXISTS(
   SELECT 1 FROM public.resource_dependencies d WHERE d.tenant_id=tenant
   AND d.version_id=(refs->>pair[1])::uuid AND d.relation='FIELD:'||pair[2]
   AND d.target_resource_id=(attrs->>pair[2])::uuid AND d.target_version_id=(refs->>pair[2])::uuid
  ) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION guard_period_posting_control() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE at_time timestamptz; proposal jsonb; pins jsonb; control_pins jsonb; expected_key text;
 identity_key text; control public.resource_versions%ROWTYPE; binding public.resource_versions%ROWTYPE;
 scope_node public.resource_versions%ROWTYPE; parent public.resource_versions%ROWTYPE;
 parent_attrs jsonb; prior public.resource_versions%ROWTYPE; control_version uuid; binding_version uuid;
 scope_version uuid; field_name text; parent_version uuid;
BEGIN
 IF NEW.object_type NOT IN ('PeriodControl','JournalEntry','JournalLine') THEN RETURN NEW; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('canonical:'||NEW.tenant_id::text,0));
 at_time := clock_timestamp();
 SELECT payload INTO proposal FROM public.resource_proposals
 WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
 pins := proposal->'validation'->'dependencies'->NEW.resource_id::text;
 IF NEW.object_type='PeriodControl' THEN
  expected_key := 'company:'||(NEW.attributes->>'legal_entity_id')||':ledger:'||(NEW.attributes->>'ledger_id')
   ||':book:'||(NEW.attributes->>'book_id')||':period:'||(NEW.attributes->>'period_id');
  SELECT i.identity_key INTO identity_key FROM public.canonical_identities i
  WHERE i.tenant_id=NEW.tenant_id AND i.resource_id=NEW.resource_id;
  IF expected_key IS NULL OR identity_key IS DISTINCT FROM expected_key
   OR NEW.authority_state IS DISTINCT FROM 'APPROVED' OR NEW.evidence_class='REFERENCE_TEMPLATE'
   OR NEW.valid_to IS NOT NULL OR NEW.valid_from>at_time
   OR NEW.attributes->'definition'->>'contract' IS DISTINCT FROM 'period-posting-control/1'
   OR (NEW.attributes->'definition'->>'state' IN ('OPEN','LOCKED')) IS NOT TRUE
   OR (length(btrim(NEW.attributes->'definition'->>'reason')) BETWEEN 10 AND 2000) IS NOT TRUE
   OR NOT public.g8_period_context_matches(NEW.tenant_id,NEW.attributes,pins,at_time)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(proposal->'request'->'mutations') m
    WHERE m->>'object_type' IN ('JournalEntry','JournalLine'))
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(proposal->'request'->'mutations') m
    WHERE m->>'resource_id' IN (NEW.attributes->>'legal_entity_id',NEW.attributes->>'ledger_id',
     NEW.attributes->>'book_id',NEW.attributes->>'period_id',NEW.attributes->>'chart_id',
     NEW.attributes->>'currency_id',NEW.attributes->>'calendar_id'))
  THEN RAISE EXCEPTION 'Period control requires an independently reviewed current accounting context'; END IF;
  SELECT v.* INTO prior FROM public.resource_heads h JOIN public.resource_versions v
   USING(tenant_id,resource_id,version_id) WHERE h.tenant_id=NEW.tenant_id AND h.resource_id=NEW.resource_id;
  FOREACH field_name IN ARRAY ARRAY['legal_entity_id','ledger_id','book_id','period_id'] LOOP
   IF prior.version_id IS NOT NULL AND prior.attributes->>field_name IS DISTINCT FROM NEW.attributes->>field_name
   THEN RAISE EXCEPTION 'Period control business tuple is immutable'; END IF;
  END LOOP;
  RETURN NEW;
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(proposal->'request'->'mutations') m
  WHERE m->>'object_type'='PeriodControl') THEN
  RAISE EXCEPTION 'Period control and journal publication require separate reviewed proposals';
 END IF;
 -- Read the exact approved pin, then require that it is still the current OPEN head.
 SELECT (p->>'resource_id')::uuid INTO control.resource_id FROM jsonb_array_elements(pins) p
 WHERE p->>'relation'='PERIOD_POSTING_CONTROL' LIMIT 1;
 control_version := public.g8_period_pin(pins,'PERIOD_POSTING_CONTROL',control.resource_id);
 SELECT v.* INTO control FROM public.resource_versions v JOIN public.resource_heads h
 USING(tenant_id,resource_id,version_id) WHERE v.tenant_id=NEW.tenant_id AND v.version_id=control_version;
 SELECT jsonb_agg(jsonb_build_object('resource_id',d.target_resource_id,'version_id',d.target_version_id,'relation',d.relation))
 INTO control_pins FROM public.resource_dependencies d WHERE d.tenant_id=NEW.tenant_id AND d.version_id=control.version_id;
 IF control.version_id IS NULL OR control.object_type IS DISTINCT FROM 'PeriodControl'
  OR control.authority_state IS DISTINCT FROM 'APPROVED' OR control.evidence_class='REFERENCE_TEMPLATE'
  OR control.attributes->'definition'->>'state' IS DISTINCT FROM 'OPEN'
  OR control.valid_from>at_time OR control.valid_to IS NOT NULL OR control.system_from>at_time
  OR public.g8_period_version_available(NEW.tenant_id,control.version_id) IS NOT TRUE
  OR NOT public.g8_period_context_matches(NEW.tenant_id,control.attributes,control_pins,at_time)
 THEN RAISE EXCEPTION 'Current reviewed OPEN period control required for journal publication'; END IF;

 binding_version := public.g8_period_pin(pins,'FIELD:accounting_binding_id',(NEW.attributes->>'accounting_binding_id')::uuid);
 SELECT * INTO binding FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=binding_version;
 IF binding.version_id IS NULL OR binding.object_type IS DISTINCT FROM 'SourceAccountingBinding'
 THEN RAISE EXCEPTION 'Journal period control requires its exact source accounting binding'; END IF;
 FOREACH field_name IN ARRAY ARRAY['ledger_id','book_id','period_id','currency_id'] LOOP
  IF binding.attributes->>field_name IS DISTINCT FROM control.attributes->>field_name OR NOT EXISTS(
   SELECT 1 FROM public.resource_dependencies d WHERE d.tenant_id=NEW.tenant_id AND d.version_id=binding.version_id
   AND d.relation='FIELD:'||field_name AND d.target_resource_id=(control.attributes->>field_name)::uuid
   AND d.target_version_id=public.g8_period_pin(control_pins,'FIELD:'||field_name,(control.attributes->>field_name)::uuid)
  ) THEN RAISE EXCEPTION 'Journal binding and period control context disagree'; END IF;
 END LOOP;
 SELECT d.target_version_id INTO scope_version FROM public.resource_dependencies d
 WHERE d.tenant_id=NEW.tenant_id AND d.version_id=binding.version_id AND d.relation='FIELD:scope_id'
 AND d.target_resource_id=(binding.attributes->>'scope_id')::uuid;
 SELECT * INTO scope_node FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=scope_version;
 IF scope_node.version_id IS NULL OR scope_node.object_type IS DISTINCT FROM 'SourceAccountingScope'
 THEN RAISE EXCEPTION 'Journal period control requires its exact source scope'; END IF;
 FOREACH field_name IN ARRAY ARRAY['legal_entity_id','chart_id'] LOOP
  IF scope_node.attributes->>field_name IS DISTINCT FROM control.attributes->>field_name OR NOT EXISTS(
   SELECT 1 FROM public.resource_dependencies d WHERE d.tenant_id=NEW.tenant_id AND d.version_id=scope_node.version_id
   AND d.relation='FIELD:'||field_name AND d.target_resource_id=(control.attributes->>field_name)::uuid
   AND d.target_version_id=public.g8_period_pin(control_pins,'FIELD:'||field_name,(control.attributes->>field_name)::uuid)
  ) THEN RAISE EXCEPTION 'Journal source scope and period control context disagree'; END IF;
 END LOOP;
 parent_attrs := NEW.attributes;
 IF NEW.object_type='JournalLine' THEN
  parent_version := public.g8_period_pin(pins,'FIELD:journal_id',(NEW.attributes->>'journal_id')::uuid);
  SELECT * INTO parent FROM public.resource_versions WHERE tenant_id=NEW.tenant_id AND version_id=parent_version;
  IF parent.version_id IS NOT NULL AND parent.object_type='JournalEntry' THEN parent_attrs := parent.attributes;
  ELSE
   SELECT m->'attributes' INTO parent_attrs FROM jsonb_array_elements(proposal->'request'->'mutations') m
   WHERE m->>'resource_id'=NEW.attributes->>'journal_id' AND m->>'object_type'='JournalEntry';
  END IF;
  IF parent_attrs IS NULL OR parent_attrs->>'accounting_binding_id' IS DISTINCT FROM NEW.attributes->>'accounting_binding_id'
  THEN RAISE EXCEPTION 'Journal line period control requires the same parent binding'; END IF;
 END IF;
 FOREACH field_name IN ARRAY ARRAY['legal_entity_id','ledger_id','period_id'] LOOP
  IF parent_attrs->>field_name IS DISTINCT FROM control.attributes->>field_name
  THEN RAISE EXCEPTION 'Journal and period control business context disagree'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER g8_period_posting_control BEFORE INSERT ON resource_versions
 FOR EACH ROW EXECUTE FUNCTION guard_period_posting_control();
REVOKE ALL ON FUNCTION g8_period_pin(jsonb,text,uuid),
 g8_period_version_available(uuid,uuid),g8_period_context_matches(uuid,jsonb,jsonb,timestamptz),guard_period_posting_control() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION g8_period_pin(jsonb,text,uuid),
 g8_period_version_available(uuid,uuid),g8_period_context_matches(uuid,jsonb,jsonb,timestamptz),guard_period_posting_control() TO finai_runtime;
INSERT INTO schema_migrations VALUES(52);
COMMIT;
