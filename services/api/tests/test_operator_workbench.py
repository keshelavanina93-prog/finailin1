from finai_api.services.operator_workbench import summarize


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
