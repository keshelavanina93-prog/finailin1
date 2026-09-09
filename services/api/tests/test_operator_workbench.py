import pytest

from finai_api.services.operator_workbench import summarize
from finai_api.services.workspace import WorkspaceError


def test_submitted_company_label_never_establishes_canonical_binding():
    item = summarize("wfr_a", {"definition": {"version": "report-source-process/3"},
                               "report": {"company_label": "SGG", "period": "2024-12"}}, "now")
    assert item["family"] == "source"
    assert item["company_id"] is None
    assert item["company_binding"] == "UNBOUND"


def test_monitor_and_action_families_use_retained_definition_not_title_or_prefix():
    monitor = summarize("opa_a", {"definition": {"version": "regulatory-source-monitor/1"},
                                  "name": "SGG checks"}, "now")
    assert monitor["family"] == "monitor"
    assert monitor["company_id"] is None
    action = summarize("rgm_a", {"definition": {"version": "ontology-action/1"},
                                 "invocation": {"company_id": "company-identity"},
                                 "prepared_proposal": {"title": "Licence binding"}}, "now")
    assert action["family"] == "ontology"
    assert action["company_id"] == "company-identity"
    assert action["title"] == "Licence binding"


def test_investigation_company_comes_from_server_prepared_evidence_not_browser_label():
    company = "00000000-0000-4000-8000-000000000001"
    run = "fcr_" + "a" * 64
    payload = {
        "definition": {"version": "ontology-action/1", "kind": "SOURCE_EXCEPTION_INVESTIGATION",
                       "company_id": company, "exception_run_id": run},
        "invocation": {"exception_run_id": run},
        "prepared_proposal": {"title": "Investigate retained source", "access_entity": company,
            "mutations": [{"object_type": kind, "attributes": {
                "legal_entity_id": company, "definition": {"exception_run_id": run,
                    "evidence": {"company": {"resource_id": company}}}}}
                for kind in ("Finding", "Investigation")]},
    }
    result = summarize("opa_" + "b" * 64, payload, "now")
    assert result["company_id"] == company
    assert result["company_binding"] == "EXPLICIT_RETAINED_EXCEPTION"
    assert result["family"] == "ontology"
    payload["prepared_proposal"]["mutations"][0]["attributes"]["legal_entity_id"] = "foreign"
    with pytest.raises(WorkspaceError):
        summarize("opa_" + "b" * 64, payload, "now")


def resolution_payload():
    from copy import deepcopy
    from uuid import uuid4

    company = str(uuid4())
    prior = {name: {"resource_id": str(uuid4()), "version_id": str(uuid4()),
                    "content_hash": "a" * 64} for name in ("prior_finding", "prior_investigation")}
    proof = {**prior, "unmatched_exception_run_id": "fcr_" + "b" * 64,
             "matched_exception_run_id": "fcr_" + "c" * 64,
             "unmatched_evidence": {"company": {"resource_id": company}},
             "matched_evidence": {"company": {"resource_id": company}}}
    metadata = {"version": "ontology-action/1", "kind": "SOURCE_EXCEPTION_INVESTIGATION",
                "operation": "RESOLVE", "company_id": company, **prior,
                "exception_run_id": proof["unmatched_exception_run_id"],
                "matched_exception_run_id": proof["matched_exception_run_id"]}
    mutations = [{"object_type": kind, "resource_id": prior["prior_" + kind.lower()]["resource_id"],
                  "expected_version_id": prior["prior_" + kind.lower()]["version_id"],
                  "attributes": {"legal_entity_id": company, "definition": {
                      "state": "RESOLVED", "exception_run_id": metadata["exception_run_id"],
                      "evidence": deepcopy(proof["unmatched_evidence"]),
                      "resolution": deepcopy(proof)}}} for kind in ("Finding", "Investigation")]
    return {"definition": metadata, "prepared_proposal": {
        "access_entity": company, "title": "Resolve source reconciliation finding",
        "mutations": mutations}}


def test_resolution_stays_in_same_explicit_company_queue():
    payload = resolution_payload()
    result = summarize("opa_" + "d" * 64, payload, "now")
    assert result["company_id"] == payload["definition"]["company_id"]
    assert result["company_binding"] == "EXPLICIT_RETAINED_EXCEPTION"


@pytest.mark.parametrize("field", ["matched_company", "old_company", "matched_run",
                                    "different_proofs", "prior_pair", "expected_head"])
def test_resolution_queue_refuses_unbound_or_mixed_proof(field):
    payload = resolution_payload()
    mutations = payload["prepared_proposal"]["mutations"]
    if field in ("matched_company", "old_company"):
        evidence = "matched_evidence" if field == "matched_company" else "unmatched_evidence"
        for mutation in mutations:
            mutation["attributes"]["definition"]["resolution"][evidence]["company"][
                "resource_id"] = "foreign"
    elif field == "matched_run":
        payload["definition"]["matched_exception_run_id"] = "fcr_" + "f" * 64
    elif field == "different_proofs":
        mutations[1]["attributes"]["definition"]["resolution"]["matched_exception_run_id"] = "bad"
    elif field == "prior_pair":
        payload["definition"]["prior_finding"] = payload["definition"]["prior_investigation"]
    else:
        mutations[0]["expected_version_id"] = "foreign"
    with pytest.raises(WorkspaceError):
        summarize("opa_" + "d" * 64, payload, "now")
