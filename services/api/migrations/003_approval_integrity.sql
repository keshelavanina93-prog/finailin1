BEGIN;
CREATE OR REPLACE FUNCTION validate_construction_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source hydration_runs%ROWTYPE;
BEGIN
    SELECT * INTO source FROM hydration_runs WHERE tenant_id=NEW.tenant_id AND receipt_id=NEW.receipt_id;
    IF NOT FOUND OR source.exact_scope IS DISTINCT FROM NEW.exact_scope THEN
        RAISE EXCEPTION 'Decision scope must match retained evidence';
    END IF;
    IF source.submitted_by IS NULL OR source.submitted_by = NEW.actor_id THEN
        RAISE EXCEPTION 'Identified submitter and independent reviewer required';
    END IF;
    IF length(trim(NEW.reason)) < 10 THEN RAISE EXCEPTION 'Review rationale is required'; END IF;
    IF NEW.decision = 'APPROVED' THEN
        IF jsonb_array_length(source.receipt->'rejects') > 0 OR jsonb_array_length(source.receipt->'candidates') = 0 THEN
            RAISE EXCEPTION 'Construction has rejected rows or no candidates';
        END IF;
        IF source.receipt->>'source_class' = 'TRIAL_BALANCE'
            AND source.receipt->'reconciliation'->>'status' IS DISTINCT FROM 'PASS' THEN
            RAISE EXCEPTION 'Trial balance reconciliation required';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER decision_integrity BEFORE INSERT ON construction_decisions
    FOR EACH ROW EXECUTE FUNCTION validate_construction_decision();

CREATE OR REPLACE FUNCTION validate_accepted_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE approval construction_decisions%ROWTYPE;
DECLARE source hydration_runs%ROWTYPE;
DECLARE candidate jsonb;
BEGIN
    SELECT * INTO approval FROM construction_decisions WHERE tenant_id=NEW.tenant_id AND receipt_id=NEW.receipt_id;
    IF NOT FOUND OR approval.decision <> 'APPROVED' OR approval.exact_scope IS DISTINCT FROM NEW.exact_scope THEN
        RAISE EXCEPTION 'An approved decision in the same exact scope is required';
    END IF;
    SELECT * INTO source FROM hydration_runs WHERE tenant_id=NEW.tenant_id AND receipt_id=NEW.receipt_id;
    IF TG_TABLE_NAME = 'workspace_heads' THEN
        IF source.receipt->>'source_class' IS DISTINCT FROM NEW.source_class THEN
            RAISE EXCEPTION 'Current version source class mismatch';
        END IF;
    ELSE
        candidate := source.receipt->'candidates'->NEW.object_index;
        IF candidate IS NULL OR candidate->>'object_type' IS DISTINCT FROM NEW.object_type
            OR NEW.object_payload->'values' IS DISTINCT FROM candidate->'values'
            OR NEW.object_payload->>'epistemic_state' IS DISTINCT FROM candidate->>'epistemic_state'
            OR NEW.object_payload->'source_row' IS DISTINCT FROM candidate->'source_row' THEN
            RAISE EXCEPTION 'Accepted object must retain the reviewed candidate content';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER head_integrity BEFORE INSERT OR UPDATE ON workspace_heads
    FOR EACH ROW EXECUTE FUNCTION validate_accepted_reference();
CREATE TRIGGER object_integrity BEFORE INSERT ON workspace_objects
    FOR EACH ROW EXECUTE FUNCTION validate_accepted_reference();
INSERT INTO schema_migrations VALUES (3) ON CONFLICT DO NOTHING;
COMMIT;
