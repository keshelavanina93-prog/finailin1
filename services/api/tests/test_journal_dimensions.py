"""Synthetic canonical analytical policies; no authentic journal acceptance claim."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.journal_dimensions import LineDimensions, PolicyDefinition
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import account_dimensions, resources
from finai_api.services import journal_dimensions as core
from finai_api.services.workspace import WorkspaceError


def dimension_case(retained):
    reader, publish = retained

    def resource(kind, attrs, **kwargs):
        return item(kind, attrs, **kwargs).model_copy(update={"evidence_class": "USER_ASSERTED"})

    company = resource("LegalEntity", {})
    chart = resource(
        "LocalChartOfAccounts", {"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)}
    )
    account = resource(
        "LocalAccount", {"chart_id": str(chart.resource_id), "account_code": "SYNTHETIC"}
    )
    nodes = publish(company, chart, account)
    return reader, publish, resource, company, chart, account, nodes


def test_exact_policy_and_provenance_contract():
    ref = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    with pytest.raises(ValueError):
        PolicyDefinition(
            contract="account-dimension-policy/1", reason="Explicit review reason", rules=[ref, ref]
        )
    with pytest.raises(ValueError):
        LineDimensions(
            contract="journal-line-dimensions/1",
            policy=ref,
            assignments=[
                {
                    "member": ref,
                    "provenance": {
                        "kind": "SOURCE_ASSIGNMENT",
                        "assignment": ref,
                        "side": "DEBIT",
                        "reason": "Not source proven",
                    },
                }
            ],
        )


@DB
def test_effective_complete_rules_and_explicit_policy(retained):
    reader, publish, resource, company, chart, account, nodes = dimension_case(retained)
    with resources.resource_connection(reader) as conn:
        core.complete(conn, reader, nodes[2], [], datetime.now(UTC))
    dimension = resource("DimensionDefinition", {"code": "SYNTHETIC_" + uuid4().hex})
    publish(dimension)
    key = f"account-dimension:{account.resource_id}:{dimension.resource_id}"
    rule = resource(
        "AccountDimensionRule",
        {
            "account_id": str(account.resource_id),
            "dimension_id": str(dimension.resource_id),
            "required": True,
        },
        resource_id=canonical_id(reader.scope.tenant_id, "AccountDimensionRule", key),
    ).model_copy(update={"identity_key": key})
    first = publish(rule)[0]
    refs = [VersionReference(resource_id=rule.resource_id, version_id=first["version_id"])]
    with resources.resource_connection(reader) as conn:
        with pytest.raises(WorkspaceError):
            core.complete(conn, reader, nodes[2], [], datetime.now(UTC))
        core.complete(conn, reader, nodes[2], refs, datetime.now(UTC))
    future = rule.model_copy(
        update={
            "expected_version_id": UUID(first["version_id"]),
            "valid_from": datetime.now(UTC) + timedelta(days=30),
            "attributes": {**rule.attributes, "required": False},
        }
    )
    publish(future)
    with resources.resource_connection(reader) as conn:
        selected = account_dimensions.rules_for_account(conn, reader, nodes[2])
        assert [str(r["version_id"]) for r in selected] == [first["version_id"]]
        core.complete(conn, reader, nodes[2], refs, datetime.now(UTC))
    identity, key = core.policy_identity(reader.scope.tenant_id, account.resource_id)
    policy = resource(
        "AccountDimensionPolicy",
        {
            "account_id": str(account.resource_id),
            "chart_id": str(chart.resource_id),
            "legal_entity_id": str(company.resource_id),
            "definition": {
                "contract": "account-dimension-policy/1",
                "reason": "Synthetic complete retained rule review",
                "rules": [r.model_dump(mode="json") for r in refs],
            },
        },
        resource_id=identity,
    ).model_copy(update={"identity_key": key})
    saved = publish(policy)[0]
    assert saved["attributes"]["definition"]["rules"][0]["version_id"] == first["version_id"]
    member = resource(
        "DimensionMember", {"dimension_id": str(dimension.resource_id), "code": "SYNTHETIC-MEMBER"}
    )
    member_row = publish(member)[0]
    from finai_api.services import source_documents

    document = source_documents.retain_document(
        reader.model_copy(update={"permissions": ("ontology_read", "ingest")}),
        "SYNTHETIC analytical fixture.txt",
        b"SYNTHETIC row3 Y3 member; no authentic accounting",
    )
    evidence = resource(
        "SourceEvidence", {"sha256": document["sha256"], "source_system": "SYNTHETIC"}
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})

    def source(kind, attrs):
        return resource(kind, {**attrs, "evidence_id": str(evidence.resource_id)}).model_copy(
            update={"evidence_class": "SOURCE_BOUND"}
        )

    row = source("SourceRecord", {"coordinate": "SYNTHETIC!3"})
    cell = source("SourceRecord", {"coordinate": "SYNTHETIC!Y3"})
    other_account = resource(
        "LocalAccount", {"chart_id": str(chart.resource_id), "account_code": "SYNTHETIC-OTHER"}
    )
    context = source(
        "CompanyDimension",
        {
            "legal_entity_id": str(company.resource_id),
            "dimension_id": str(dimension.resource_id),
            "source_record_id": str(cell.resource_id),
            "source_column": "Y",
            "source_header": "SYNTHETIC",
        },
    )
    observation = source(
        "SourceJournalMovement",
        {
            "legal_entity_id": str(company.resource_id),
            "debit_account_id": str(account.resource_id),
            "credit_account_id": str(other_account.resource_id),
            "source_record_id": str(row.resource_id),
            "posting_date": "2026-01-01",
            "document_reference": "SYNTHETIC",
            "amount": "1",
            "source_family": "SYNTHETIC",
            "source_row_key": "SYNTHETIC!3",
            "unit_status": "UNESTABLISHED",
            "source_details": {"cells": {"Y": {"type": 1, "value": "SYNTHETIC-MEMBER"}}},
        },
    )
    attribution = source(
        "SourceDimensionAssignment",
        {
            "observation_id": str(observation.resource_id),
            "company_dimension_id": str(context.resource_id),
            "member_id": str(member.resource_id),
            "source_record_id": str(cell.resource_id),
        },
    )
    published = publish(evidence, row, cell, other_account, context, observation, attribution)
    source_row = published[-1]
    member_ref = {"resource_id": str(member.resource_id), "version_id": member_row["version_id"]}
    policy_ref = {"resource_id": str(identity), "version_id": saved["version_id"]}
    assignment = {
        "member": member_ref,
        "provenance": {"kind": "USER_ASSERTED", "reason": "Synthetic operator assignment"},
    }
    line = resource(
        "JournalLine",
        {
            "account_id": str(account.resource_id),
            "side": "DEBIT",
            "source_record_id": str(row.resource_id),
            "dimension_policy_id": str(identity),
            "dimensions": {
                "contract": "journal-line-dimensions/1",
                "policy": policy_ref,
                "assignments": [assignment],
            },
        },
    )
    from types import SimpleNamespace

    from finai_api.services.account_dimension_policy import _reader

    with resources.resource_connection(reader) as conn:
        at = datetime.now(UTC)
        target = _reader(conn, reader, at)

        def validate(candidate):
            core.validate_line(
                conn, reader, candidate, target, SimpleNamespace(mutations=[candidate]), at
            )

        validate(line)
        for changes in [
            {"account_id": str(other_account.resource_id)},
            {
                "dimensions": {
                    **line.attributes["dimensions"],
                    "policy": {**policy_ref, "version_id": str(uuid4())},
                }
            },
        ]:
            with pytest.raises(WorkspaceError):
                validate(line.model_copy(update={"attributes": {**line.attributes, **changes}}))
        for assignments in [
            [],
            [assignment, assignment],
            [{**assignment, "member": {**member_ref, "version_id": str(uuid4())}}],
        ]:
            with pytest.raises(WorkspaceError):
                validate(
                    line.model_copy(
                        update={
                            "attributes": {
                                **line.attributes,
                                "dimensions": {
                                    **line.attributes["dimensions"],
                                    "assignments": assignments,
                                },
                            }
                        }
                    )
                )
        declared = {
            "kind": "REVIEWED_SOURCE_ATTRIBUTION",
            "reason": "Synthetic reviewed side attribution",
            "side": "DEBIT",
            "assignment": {
                "resource_id": str(attribution.resource_id),
                "version_id": source_row["version_id"],
            },
        }
        attributed = line.model_copy(
            update={
                "attributes": {
                    **line.attributes,
                    "dimensions": {
                        **line.attributes["dimensions"],
                        "assignments": [{**assignment, "provenance": declared}],
                    },
                }
            }
        )
        validate(attributed)

        def unavailable(identity, owner, relation):
            if relation == "DIMENSION_SOURCE_EVIDENCE":
                raise WorkspaceError(404, "Synthetic unavailable retained evidence")
            return target(identity, owner, relation)

        with pytest.raises(WorkspaceError):
            core.validate_attribution(
                conn,
                reader,
                attributed,
                LineDimensions.model_validate(attributed.attributes["dimensions"]).assignments[0],
                member_row,
                target(str(dimension.resource_id)),
                nodes[2],
                unavailable,
                None,
            )
        for changes in [{"side": "CREDIT"}, {"source_record_id": str(cell.resource_id)}]:
            with pytest.raises(WorkspaceError):
                validate(
                    attributed.model_copy(
                        update={"attributes": {**attributed.attributes, **changes}}
                    )
                )
        with pytest.raises(WorkspaceError):
            validate(
                line.model_copy(update={"attributes": {**line.attributes, "dimensions": None}})
            )
