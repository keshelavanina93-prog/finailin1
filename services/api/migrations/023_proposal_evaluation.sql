BEGIN;
CREATE FUNCTION enforce_proposal_evaluation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p resource_proposals%ROWTYPE;
DECLARE evidence jsonb;
BEGIN
    IF NEW.decision='APPROVED' THEN
        SELECT * INTO p FROM resource_proposals
            WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.proposal_id;
        evidence := p.payload->'validation'->'evaluation';
        IF evidence->>'status' IS DISTINCT FROM 'PASS' OR
           evidence->>'evaluator' IS DISTINCT FROM 'canonical-structural-contract/v1' OR
           evidence->>'proposal_hash' IS DISTINCT FROM p.request_hash OR
           coalesce(evidence->>'binding_hash','') !~ '^[a-f0-9]{64}$' THEN
            RAISE EXCEPTION 'Matching retained proposal evaluation is required';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER proposal_evaluation_required BEFORE INSERT ON resource_decisions
FOR EACH ROW EXECUTE FUNCTION enforce_proposal_evaluation();
INSERT INTO schema_migrations VALUES (23);
COMMIT;
