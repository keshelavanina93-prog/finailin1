"""Prepare a measure-free SEG account table using existing reviewed objects.

Default is read-only. --apply is reserved for a frozen implementation: it uses
ordinary separate-actor review and one version-keyed normal-operator invocation.
No account, company, schema, source record or accounting interpretation is created.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid5

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, function_invocations, resources
from finai_api.services.accounting_source_document import read_source
from finai_api.services.semantic_analysis_support import Resolver, pin
from finai_api.services.workbook_source import read_workbook
from finai_api.services.workspace import WorkspaceError
from psycopg.types.json import Jsonb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    grants = [
        Principal.model_validate(v)
        for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    maker = next(
        p
        for p in grants
        if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
    )
    checker = next(
        p
        for p in grants
        if p.actor_id != maker.actor_id
        and p.scope == maker.scope
        and {"ontology_admin", "ontology_review"} <= set(p.permissions)
    )
    operator = next(
        p
        for p in grants
        if p.scope == maker.scope
        and {"ingest", "ontology_read"} <= set(p.permissions)
        and "ontology_admin" not in p.permissions
    )
    company_id = UUID("365aa5d9-c2ec-52e1-867a-50fe3415f486")
    chart_id = UUID("8156f21a-d5c0-5a45-9ec1-2b4513e73071")
    chart_source_sha = (
        "607e37da8aa8e05687c9898cc1577db070c082ece8281c7bd3a43e725aac73df"
    )
    chart_evidence_id = "0074068a-99ea-5a03-8e61-15f7430b04d4"
    base_source_sha = "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
    resolver = Resolver(operator, {"function": {}, "static_dependencies": []})

    def read(identity):
        return resources.get_resource(operator, UUID(str(identity)))["resource"]

    def exact_field(row, name, kind):
        result = resolver.field(row, name)
        assert result["object_type"] == kind
        assert result["authority_state"] == "APPROVED"
        return result

    def exact_schema(row):
        matches = [
            d
            for d in resolver.dependencies(pin(row))
            if d["relation"] == "USES_SCHEMA"
            and str(d["version_id"]) == str(row["schema_version_id"])
            and d["object_type"] == "SchemaDefinition"
        ]
        assert len(matches) == 1
        return matches[0]

    company, chart = read(company_id), read(chart_id)
    assert (
        company["object_type"] == "LegalEntity"
        and company["authority_state"] == "APPROVED"
    )
    assert (
        chart["object_type"] == "LocalChartOfAccounts"
        and chart["authority_state"] == "APPROVED"
    )
    assert pin(exact_field(chart, "legal_entity_id", "LegalEntity")) == pin(company)
    assert (
        exact_schema(chart)["attributes"]["fields"]["legal_entity_id"]["target_type"]
        == "LegalEntity"
    )
    with function_invocations._database(operator) as cursor:
        originals = cursor.execute(
            "SELECT receipt_id FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
            "AND source_sha256=%s LIMIT 2",
            (
                operator.scope.tenant_id,
                Jsonb(operator.scope.model_dump(mode="json")),
                chart_source_sha,
            ),
        ).fetchall()
    assert len(originals) == 1, (
        "Original chart receipt must be unambiguous in this exact scope"
    )
    metadata, content = read_source(operator, originals[0]["receipt_id"])
    assert metadata["source_sha256"] == sha256(content).hexdigest() == chart_source_sha
    workbook = read_workbook(content)
    sheets = {sheet["name"]: sheet["cells"] for sheet in workbook["sheets"]}
    accounts = [
        r.model_dump(mode="json")
        for r in resources.list_resources(operator, "LocalAccount", "", 0, limit=1000)
        if r.attributes.get("chart_id") == str(chart_id)
    ]
    assert len(accounts) == 38, (
        "Re-review the retained subject if its membership changed"
    )
    accounts.sort(key=lambda r: r["attributes"]["account_code"])
    schema_versions, evidence_versions, verified = set(), set(), []
    for account in accounts:
        assert (
            account["authority_state"] == "APPROVED"
            and account["evidence_class"] == "SOURCE_BOUND"
        )
        assert pin(exact_field(account, "chart_id", "LocalChartOfAccounts")) == pin(
            chart
        )
        schema = exact_schema(account)
        assert (
            schema["attributes"]["fields"]["chart_id"]["target_type"]
            == "LocalChartOfAccounts"
        )
        schema_versions.add(str(schema["version_id"]))
        use_evidence = exact_field(account, "evidence_id", "SourceEvidence")
        assert use_evidence["attributes"]["sha256"] == base_source_sha
        definitions = [
            d
            for d in resolver.dependencies(pin(account))
            if d["relation"].startswith("BOUND_SOURCE:")
            and d["object_type"] == "SourceAccountDefinition"
        ]
        assert len(definitions) == 1
        definition = definitions[0]
        assert definition["authority_state"] == "APPROVED"
        record = exact_field(definition, "source_record_id", "SourceRecord")
        evidence = exact_field(definition, "evidence_id", "SourceEvidence")
        assert pin(exact_field(record, "evidence_id", "SourceEvidence")) == pin(
            evidence
        )
        assert str(evidence["resource_id"]) == chart_evidence_id
        assert evidence["attributes"]["sha256"] == chart_source_sha
        evidence_versions.add(str(evidence["version_id"]))
        sheet_name, address = record["attributes"]["coordinate"].rsplit("!", 1)
        cell = sheets[sheet_name][address]
        assert cell["formula"] is None
        assert (
            cell["value"]
            == definition["attributes"]["account_code"]
            == account["attributes"]["account_code"]
        )
        verified.append(
            {
                "account": pin(account).model_dump(mode="json"),
                "definition": pin(definition).model_dump(mode="json"),
                "coordinate": record["attributes"]["coordinate"],
            }
        )
    assert len(schema_versions) == len(evidence_versions) == 1
    set_id = uuid5(
        company_id, "semantic-analysis:reviewed-local-accounts:object-set/v1"
    )
    function_id = uuid5(
        company_id, "semantic-analysis:reviewed-local-accounts:function/v1"
    )
    manifest = function_execution.manifest()
    definition = {
        key: manifest[key]
        for key in (
            "implementation_id",
            "determinism",
            "code_sha256",
            "dependency_sha256",
        )
    }
    definition["derived_property_ids"] = []
    plans = [
        (
            set_id,
            "ObjectSetDefinition",
            "SEG reviewed local accounts",
            {
                "definition": {
                    "object_type": "LocalAccount",
                    "filters": [{"field": "chart_id", "value": str(chart_id)}],
                }
            },
        ),
        (
            function_id,
            "FunctionDefinition",
            "SEG reviewed account definitions",
            {"object_set_id": str(set_id), "definition": definition},
        ),
    ]
    reason = (
        "Present existing reviewed SEG LocalAccount definitions through their exact company chart "
        "and bound original chart definitions. This is an object table with no approved measure, "
        "aggregation, financial classification, complete-chart claim or business effect. "
        "The original account chart and separate Base usage evidence remain distinct."
    )
    publications = []
    for identity, kind, name, attributes in plans:
        prior = resources.current_resources(maker, [identity]).get(str(identity))
        if args.apply and (not prior or prior["attributes"] != attributes):
            proposal = ResourceProposal(
                title="Review measure-free SEG account definitions",
                rationale=reason,
                access_entity=maker.scope.legal_entity_id,
                mutations=[
                    ResourceMutation(
                        resource_id=identity,
                        expected_version_id=prior["version_id"] if prior else None,
                        object_type=kind,
                        identity_key="semantic-object-analysis:" + str(identity),
                        display_name=name,
                        attributes=attributes,
                        valid_from=datetime.now(UTC),
                        evidence_class="USER_ASSERTED",
                    )
                ],
                source_versions={
                    identity: {
                        UUID(str(row["resource_id"])): UUID(str(row["version_id"]))
                        for row in [company, chart, *accounts]
                    }
                },
            )
            resources.propose(maker, proposal)
            resources.review(
                checker,
                proposal.proposal_id,
                ResourceReview(decision="APPROVED", rationale=reason),
            )
            publications.append(str(proposal.proposal_id))
    result = {
        "mode": "APPLIED" if args.apply else "READ_ONLY_PREPARATION",
        "company": pin(company).model_dump(mode="json"),
        "chart": pin(chart).model_dump(mode="json"),
        "object_set_id": str(set_id),
        "function_id": str(function_id),
        "expected_object_count": len(accounts),
        "measure": None,
        "financial_authority_established": False,
        "chart_completeness_established": False,
        "original_chart_receipt": metadata["document_id"],
        "original_chart_sha256": chart_source_sha,
        "separate_base_use_sha256": base_source_sha,
        "verified_objects": verified,
        "publication_proposals": publications,
        "requires_frozen_source_before_apply": True,
    }
    if args.apply:
        function = read(function_id)
        frozen_at = datetime.fromisoformat(str(function["system_from"]))
        invocation = FunctionInvocation(
            request_id=uuid5(
                UUID(str(function["version_id"])),
                "semantic-object-analysis/operator-v1:" + operator.actor_id,
            ),
            function={"resource_id": function_id, "version_id": function["version_id"]},
            valid_at=frozen_at,
            known_at=frozen_at,
            offset=0,
            limit=100,
        )
        try:
            history = function_invocations.history(operator, invocation.request_id)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            history = function_invocations.invoke(operator, invocation)
        if history["status"] == "INTENT_RETAINED":
            history = function_invocations.invoke(operator, invocation)
        assert history["status"] == "SUCCEEDED", history["receipt"].get("failure_code")
        output = history["output"]
        assert not output.get("group_counts") and not output.get("derived_values")
        assert len(output["objects"]) == 38 and output.get("next_offset") is None
        assert {str(o["resource_id"]) for o in output["objects"]} == {
            r["resource_id"] for r in accounts
        }
        result["invocation"] = {
            "invocation_id": history["invocation_id"],
            "receipt_hash": history["receipt_hash"],
            "run_id": output["run_id"],
            "function": output["function"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
