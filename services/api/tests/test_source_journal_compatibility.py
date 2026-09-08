from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_entity_movement_review import fixture

from finai_api.services.source_journal_compatibility import validate
from finai_api.services.workspace import WorkspaceError


def test_reviewed_family_keeps_its_name_and_exact_binding_version():
    _, source, targets, ids = fixture()
    binding = targets[source["binding"]["resource_id"]]
    scope = targets[ids["scope"]]
    scope["object_type"] = "SourceAccountingScope"
    scope["resource_id"] = ids["scope"]
    scope["version_id"] = str(uuid4())
    scope["attributes"]["worksheet"] = "Base"
    evidence_id = str(uuid4())
    scope["attributes"]["evidence_id"] = evidence_id
    targets[evidence_id] = {"attributes": {"sha256": "a" * 64}}
    attrs = {
        "accounting_binding_id": binding["resource_id"],
        "scope_id": ids["scope"],
        "legal_entity_id": source["company_id"],
        **{k: source["context"][k] for k in ("ledger_id", "book_id", "period_id", "currency_id")},
        "definition": {
            "contract": "source-journal-compatibility/1",
            "source_profile": "seg_expense_base",
            "source_family": "SEG_EXPENSE_BASE",
            "source_sha256": "a" * 64,
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

    assert validate(item, read).source_profile == "seg_expense_base"
    binding["version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="version changed"):
        validate(item, read)
