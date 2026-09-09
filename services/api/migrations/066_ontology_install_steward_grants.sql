BEGIN;

CREATE TABLE public.ontology_install_grant_requests (
    tenant_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    request_id uuid NOT NULL,
    author_id text NOT NULL,
    permission text NOT NULL,
    rationale text NOT NULL,
    request_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, grant_id),
    UNIQUE (tenant_id, request_id),
    CHECK (permission = 'restricted_read')
);

CREATE TABLE public.ontology_install_grant_decisions (
    tenant_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    decision text NOT NULL,
    reviewer_id text NOT NULL,
    rationale text NOT NULL,
    decision_sha256 text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, grant_id),
    UNIQUE (tenant_id, decision_id),
    FOREIGN KEY (tenant_id, grant_id)
        REFERENCES public.ontology_install_grant_requests(tenant_id, grant_id),
    CHECK (decision IN ('APPROVED', 'REJECTED'))
);

ALTER TABLE public.ontology_install_grant_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ontology_install_grant_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE public.ontology_install_grant_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ontology_install_grant_decisions FORCE ROW LEVEL SECURITY;

CREATE POLICY ontology_install_grant_request_access
ON public.ontology_install_grant_requests
USING (
    tenant_id::text = current_setting('finai.tenant_id', true)
    AND (
        current_setting('finai.tenant_access', true) = 'true'
        OR author_id = current_setting('finai.entity_id', true)
    )
)
WITH CHECK (tenant_id::text = current_setting('finai.tenant_id', true));

CREATE POLICY ontology_install_grant_decision_access
ON public.ontology_install_grant_decisions
USING (tenant_id::text = current_setting('finai.tenant_id', true))
WITH CHECK (tenant_id::text = current_setting('finai.tenant_id', true));

CREATE TRIGGER immutable_ontology_install_grant_request
BEFORE UPDATE OR DELETE OR TRUNCATE
ON public.ontology_install_grant_requests FOR EACH STATEMENT
EXECUTE FUNCTION public.deny_evidence_mutation();

CREATE TRIGGER immutable_ontology_install_grant_decision
BEFORE UPDATE OR DELETE OR TRUNCATE
ON public.ontology_install_grant_decisions FOR EACH STATEMENT
EXECUTE FUNCTION public.deny_evidence_mutation();

GRANT SELECT, INSERT ON public.ontology_install_grant_requests TO finai_runtime;
GRANT SELECT, INSERT ON public.ontology_install_grant_decisions TO finai_runtime;

INSERT INTO schema_migrations VALUES(66);
COMMIT;
