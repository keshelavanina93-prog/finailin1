from finai_api.services.regulatory_licence_context import bind_assessment


def test_missing_or_other_company_licence_cannot_activate_obligation():
    assessment = {"applicability": "APPLICABLE", "effective_obligation": True}
    refs = {
        "legal_entity_id": {"resource_id": "sgg", "version_id": "c1"},
        "licence_id": {"resource_id": "licence", "version_id": "l1"},
    }
    holder = {
        "references": {
            "source_id": {"resource_id": "sog", "version_id": "c2"},
            "target_id": refs["licence_id"],
        }
    }
    assert not bind_assessment(assessment, refs, [], True)["effective_obligation"]
    assert not bind_assessment(assessment, refs, [holder], True)["effective_obligation"]
    holder["references"]["source_id"] = refs["legal_entity_id"]
    assert bind_assessment(assessment, refs, [holder], True)["effective_obligation"]
    assert not bind_assessment(assessment, refs, [holder], False)["effective_obligation"]
    holder["references"]["target_id"] = {"resource_id": "licence", "version_id": "l2"}
    assert not bind_assessment(assessment, refs, [holder], True)["effective_obligation"]
