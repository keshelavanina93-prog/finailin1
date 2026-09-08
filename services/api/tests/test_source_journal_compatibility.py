from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_entity_movement_review import fixture

from finai_api.services.source_journal_compatibility import require, validate
from finai_api.services.workspace import WorkspaceError


def compatibility_case(source=None, targets=None):
    if source is None:
        _, source, targets, _ = fixture()
    ids = {"scope": source["scope"]["resource_id"]}
    binding = targets[source["binding"]["resource_id"]]
    scope = targets[ids["scope"]]
    scope["object_type"] = "SourceAccountingScope"
    scope["resource_id"] = ids["scope"]
    scope.setdefault("version_id", str(uuid4()))
    scope["attributes"]["worksheet"] = "Base"
    scope["attributes"]["source_profile"] = "seg_expense_base"
    evidence_id = source.get("evidence", {}).get("resource_id", str(uuid4()))
    scope["attributes"]["evidence_id"] = evidence_id
    targets[evidence_id] = {
        "resource_id": evidence_id,
        "version_id": str(uuid4()),
        "attributes": {"sha256": source["sha256"]},
    }
    attrs = {
        "accounting_binding_id": binding["resource_id"],
        "scope_id": ids["scope"],
        "legal_entity_id": source["company_id"],
        **{k: source["context"][k] for k in ("ledger_id", "book_id", "period_id", "currency_id")},
        "definition": {
            "contract": "source-journal-compatibility/1",
            "source_profile": "seg_expense_base",
            "source_family": "SEG_EXPENSE_BASE",
            "source_sha256": source["sha256"],
            "binding_version_id": binding["version_id"],
            "scope_version_id": scope["version_id"],
            "sheet": "Base",
            "grain": "SOURCE_ROW",
            "amount_field": "source_amount",
            "amount_column": "S",
            "amount_header": "Сумма",
            "amount_semantics": "DEBIT_CREDIT",
            "vat_treatment": "AS_POSTED",
            "row_identity": "RECORDER_AND_LINE",
            "amount_conversion": "NONE",
            "rationale": "Reviewed source-row posting compatibility with no numeric conversion",
        },
    }
    item = SimpleNamespace(resource_id=uuid4(), attributes=attrs)

    def read(key, *_):
        return targets[key]

    return item, binding, scope, read


def test_reviewed_family_keeps_its_name_and_exact_binding_version():
    item, binding, _, read = compatibility_case()

    assert validate(item, read).source_profile == "seg_expense_base"
    binding["version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="version changed"):
        validate(item, read)


@pytest.mark.parametrize("failure", ["kind", "company", "profile", "book", "vat", "grain", "hash"])
def test_compatibility_refuses_cross_context_and_amount_reinterpretation(failure):
    item, binding, scope, read = compatibility_case()
    if failure == "kind":
        binding["object_type"] = "SourceRecord"
    elif failure == "company":
        item.attributes["legal_entity_id"] = str(uuid4())
    elif failure == "profile":
        scope["attributes"]["source_profile"] = "1c_journal"
    elif failure == "book":
        item.attributes["book_id"] = str(uuid4())
    elif failure == "vat":
        binding["attributes"]["vat_treatment"] = "NET"
    elif failure == "grain":
        binding["attributes"]["granularity"] = "SUMMARY"
    else:
        item.attributes["definition"]["source_sha256"] = "b" * 64
    with pytest.raises(WorkspaceError):
        validate(item, read)


def test_unreviewed_or_wrong_binding_authority_cannot_grant_publication():
    item, binding, scope, read = compatibility_case()
    journal = SimpleNamespace(resource_id=uuid4(), attributes={})
    with pytest.raises(WorkspaceError, match="needs reviewed"):
        require(journal, binding, scope, read)
    authority = {
        "resource_id": str(item.resource_id),
        "attributes": item.attributes,
        "object_type": "SourceJournalCompatibility",
        "authority_state": "APPROVED",
        "evidence_class": "USER_ASSERTED",
    }
    journal.attributes["source_compatibility_id"] = str(item.resource_id)

    def target(key, *_):
        return authority if key == str(item.resource_id) else read(key)

    assert require(journal, binding, scope, target).amount_conversion == "NONE"
    authority["authority_state"] = "PROPOSED"
    with pytest.raises(WorkspaceError, match="unavailable"):
        require(journal, binding, scope, target)
