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
